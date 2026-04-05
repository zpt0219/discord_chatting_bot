import os
import json
import datetime
from memory_manager import MemoryManager

from models.local_model_logic import _generate_with_local, _extract_with_local, LOCAL_LLAMA_BASE_URL
from models.claude_model_logic import _generate_with_claude, _extract_with_claude
from models.openai_model_logic import _generate_with_openai, _extract_with_openai

import settings
from prompts import SYSTEM_PROMPT

# ===============================================
# MAIN CHAT GENERATION (WITH ROUTER)
# ===============================================

def is_complex_query(user_message: str) -> bool:
    """
    A fast heuristics router to determine query complexity.
    """
    msg = user_message.lower()
    
    # Thresholds are now adjustable in settings.py
    len_threshold = settings.ROUTER_COMPLEXITY_LEN_THRESHOLD
    keywords = settings.ROUTER_COMPLEX_KEYWORDS
    
    # If the message is long (deep explanation), or contains a complex requesting keyword, route to Claude.
    if len(msg) > len_threshold or any(keyword in msg for keyword in keywords):
        return True
    return False

async def generate_response(memory: MemoryManager, chat_history: list, image_data: list = None, audio_data: list = None) -> dict:
    """
    The Strategic Router & Context Hydrator.
    
    1. CONTEXT: Gathers categorized facts (Identity, Interests, etc.) from the Knowledge Store.
    2. HYDRATION: Injects persistent memory into the shared System Prompt.
    3. ROUTING: Evaluates media types and query complexity to select the optimal model tier.
    
    Returns: {"text": str, "attachment": str|None}
    """
    # 1. Fetch persistent context from the Categorized Knowledge Store
    bot_info = memory.get_bot_identity()
    owner_info = memory.get_owner_relationship()
    
    # 2. Format localized relationship facts for the prompt injection
    facts_dict = owner_info.get("facts", {})
    facts_list = []
    category_labels = {
        "identity": "👤 Identity",
        "interests": "🌟 Interests & Hobbies",
        "preferences": "⚙️ Bot Preferences",
        "routine": "📅 Daily Routine & Work",
        "other": "📝 Other Facts"
    }
    
    for cat, label in category_labels.items():
        cat_facts = facts_dict.get(cat, [])
        if cat_facts:
            facts_list.append(f"{label}:")
            facts_list.extend([f"  - {f}" for f in cat_facts])
    
    facts_str = "\n".join(facts_list) if facts_list else "I don't know anything about my owner yet."
    memories_str = "\n".join([f"- {m}" for m in owner_info.get("summarized_memories", [])])
    
    # 3. Handle language preference
    pref_lang = owner_info.get("preferred_language")
    lang_instr = f"IMPORTANT: Your owner prefers to speak in {pref_lang}. Please respond ONLY in {pref_lang}." if pref_lang else ""
    
    # 4. Fill the system prompt template with the latest reality
    formatted_system = SYSTEM_PROMPT.format(
        bot_name=bot_info.get("name") or "[Unknown/Not chosen yet]",
        bot_traits=", ".join(bot_info.get("personality_traits", [])) or "None identified yet.",
        relationship_stage=owner_info.get("relationship_stage", "stranger"),
        owner_facts=facts_str or "I don't know anything about my owner yet.",
        summarized_memories=memories_str or "I don't have any long-term memories of our past conversations yet.",
        language_instruction=lang_instr
    )
    
    # 3. Extract the user's most recent message to evaluate for Routing
    latest_user_msg = next((msg["content"] for msg in reversed(chat_history) if msg["role"] == "user"), "")
    
    # ---- 4. HIERARCHICAL ROUTER DECISION ----
    
    # TIER 0: AUDIO PATH
    # Only OpenAI GPT-4o currently supports native audio-to-text-to-audio flows reliably.
    if audio_data:
        print(f"ROUTER: Audio detected -> Sending to OpenAI (Tier 3).")
        try:
            res = await _generate_with_openai(memory, formatted_system, chat_history, audio_data=audio_data)
            return {"text": res, "attachment": None}
        except Exception as e:
            print(f"Critical: OpenAI audio processing failed ({e}).")
            return {"text": "*(I couldn't process that voice message, sorry...)*", "attachment": None}
    
    # TIER 1-2: IMAGE PATH
    # Local models lack reliable vision; skip straight to Claude (Primary) or OpenAI (Fallback).
    if image_data:
        print(f"ROUTER: Image detected -> Sending to Claude (Tier 2 Vision).")
        try:
            res = await _generate_with_claude(memory, formatted_system, chat_history, image_data=image_data)
            return {"text": res, "attachment": None}
        except Exception as e:
            print(f"Notice: Claude vision failed ({e}). Falling back to Tier 3 (OpenAI)...")
            try:
                res = await _generate_with_openai(memory, formatted_system, chat_history, image_data=image_data)
                return {"text": res, "attachment": None}
            except Exception as e2:
                print(f"Critical: Both vision providers failed ({e2}).")
                return {"text": "*(I tried to look at the image, but my eyes are blurry...)*", "attachment": None}
    
    # TEXT PATH: Priority Local Llama (simple) -> Claude (complex or fallback) -> OpenAI (last resort)
    # If the local server URL is missing, we bypass Tier 1 entirely
    if not is_complex_query(latest_user_msg) and LOCAL_LLAMA_BASE_URL:
        # Simple paths use the cheap, local fast path first
        print(f"ROUTER: Message is simple -> Sending to Local Llama.")
        try:
            res = await _generate_with_local(memory, formatted_system, chat_history)
        except Exception as e:
            # Tier 2: Claude
            print(f"Notice: Local Llama failed ({e}). Falling back to Claude...")
            try:
                res = await _generate_with_claude(memory, formatted_system, chat_history)
            except Exception as e2:
                # Tier 3: OpenAI
                print(f"Notice: Claude also failed ({e2}). Falling back to OpenAI...")
                try:
                    res = await _generate_with_openai(memory, formatted_system, chat_history)
                except Exception as e3:
                    print(f"Critical: All 3 providers failed ({e3}).")
                    res = "*(The bot seems to have lost its train of thought...)*"
    else:
        # Complex paths (or if local is disabled) skip local entirely and go straight to cloud
        provider = "Claude" if not is_complex_query(latest_user_msg) else "Claude (Complex)"
        print(f"ROUTER: Sending to {provider}.")
        try:
            res = await _generate_with_claude(memory, formatted_system, chat_history)
        except Exception as e:
            print(f"Notice: Claude failed ({e}). Falling back to OpenAI...")
            try:
                res = await _generate_with_openai(memory, formatted_system, chat_history)
            except Exception as e2:
                print(f"Critical: OpenAI also failed ({e2}).")
                res = "*(I tried to think really hard about that, but my brain hurts...)*"
                    
    # ---- 5. POST-PROCESS ATTACHMENTS (GENERIC RELAY) ----
    import re
    from skills import pending_attachments
    attachment_path = None
    
    # Check if any tool captured an attachment during this generation cycle
    if pending_attachments:
        attachment_path = pending_attachments.pop(0)
        print(f"AGENT: Attaching file -> {attachment_path}")
    
    # Also clean up any [ATTACH:] tags that might have leaked into the LLM's text
    res = re.sub(r"\[ATTACH:.*?\]", "", res).strip()
        
    return {"text": res, "attachment": attachment_path}


# ===============================================
# BACKGROUND EXTRACTION (MEMORY UPDATES)
# ===============================================

async def extract_and_update_memory(memory: MemoryManager, user_message: str, bot_response: str):
    """
    Main entry point triggered seamlessly by bot.py in an async background loop.
    It feeds the last message to the tool extractors without slowing down the active conversation.
    
    Extraction priority: Local Llama -> Claude -> OpenAI
    """
    owner_info = memory.get_owner_relationship()
    bot_info = memory.get_bot_identity()
    
    owner_facts = owner_info.get("facts", {})
    facts_context = []
    for cat, flist in owner_facts.items():
        if flist:
            facts_context.append(f"[{cat.upper()}]:")
            facts_context.extend([f"  - {f}" for f in flist])
    
    existing_facts = "\n".join(facts_context)
    existing_traits = ", ".join(bot_info.get("personality_traits", []))
    existing_memories = "\n".join([f"- {m}" for m in owner_info.get("summarized_memories", [])])
    
    prompt = (
        f"Analyze this recent exchange between the owner and the bot.\n"
        f"Owner: {user_message}\n"
        f"Bot: {bot_response}\n\n"
        f"Everything ALREADY known about the owner (by category):\n"
        f"{existing_facts if existing_facts else 'None yet.'}\n\n"
        f"Traits ALREADY known about the bot:\n"
        f"{existing_traits if existing_traits else 'None yet.'}\n\n"
        f"Long-term memories ALREADY archived:\n"
        f"{existing_memories if existing_memories else 'None yet.'}\n\n"
        f"Task:\n"
        f"1. Extract any NEW specific facts about the owner and CATEGORIZE them:\n"
        f"   - 'identity': Name, age, job, role, social status.\n"
        f"   - 'interests': Hobbies, likes, dislikes, favorite media.\n"
        f"   - 'preferences': How the owner wants the bot to act or speak.\n"
        f"   - 'routine': Daily schedule, habits, current activities.\n"
        f"   - 'other': Anything else.\n"
        f"2. Identify any NEW personality traits the bot exhibited.\n"
        f"3. Generate a one-sentence high-level 'memory abstraction' for the 'new_summarized_memory' field if this interaction introduced or significantly developed a topic.\n"
        f"CRITICAL: \n"
        f"1. Do NOT extract facts that are already listed above. If a new fact is just a better/updated version of an existing one, extract it and we will handle the update.\n"
        f"2. Keep personality traits SIMPLE (one or two words).\n"
    )

    try:
        await _extract_with_local(memory, prompt)
    except Exception as e:
        print(f"Notice: Local Llama tool extraction failed ({e}). Falling back to Claude...")
        try:
            await _extract_with_claude(memory, prompt)
        except Exception as e2:
            print(f"Notice: Claude extraction also failed ({e2}). Falling back to OpenAI...")
            try:
                await _extract_with_openai(memory, prompt)
            except Exception as e3:
                print(f"Critical: All 3 extraction providers failed: {e3}")
    finally:
        # Sequential Writeback: Update timestamp only after abstraction logic is complete.
        # This prevents race conditions by ensuring only one write happens per conversation turn.
        memory.record_owner_reply()
        print(f"MEMORY: Background extraction complete and timestamp archived.")
