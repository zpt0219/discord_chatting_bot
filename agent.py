import os
import json
import datetime
import asyncio
from memory_manager import MemoryManager

from models.router import get_model_response, get_memory_extraction

import settings
from prompts import SYSTEM_PROMPT, MEMORY_EXTRACTION_PROMPT

# ===============================================
# MAIN CHAT GENERATION (WITH ROUTER)
# ===============================================


async def generate_response(memory: MemoryManager, chat_history: list, image_data: list = None, attachments_list: list = None) -> dict:
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
    # 3. Handle Fact Injection with Context Window Protection
    # Large knowledge stores can overwhelm small local models.
    # We limit per-category and total character count.
    facts_dict = owner_info.get("facts", {})
    category_labels = {
        "identity": "👤 Identity",
        "interests": "🌟 Interests",
        "preferences": "⚙️ Preferences",
        "routine": "📅 Routine",
        "key_memories": "🧠 Key Memories",
        "other": "📂 Other facts"
    }
    
    facts_list = []
    total_chars = 0
    
    for cat, label in category_labels.items():
        cat_facts = facts_dict.get(cat, [])
        if cat_facts:
            # Take ONLY the most recent facts (last N)
            recent_facts = cat_facts[-settings.MAX_FACTS_PER_CATEGORY:]
            
            # Format this category's block
            block_lines = [f"{label}:"]
            block_lines.extend([f"  - {f}" for f in recent_facts])
            block_text = "\n".join(block_lines)
            
            # Global Character Ceiling Check
            if total_chars + len(block_text) > settings.MAX_FACTS_TOTAL_CHARS:
                print(f"DEBUG: Fact injection reached ceiling. Skipping '{cat}' category.")
                break
                
            facts_list.append(block_text)
            total_chars += len(block_text) + 1
            
    facts_str = "\n".join(facts_list) if facts_list else "(No specific personal facts saved yet.)"
    
    # 3. Format recent raw history for the system prompt (last 5 turns)
    raw_history_list = []
    for msg in chat_history[-5:]:
        role_label = "Owner" if msg["role"] == "user" else "Bot"
        raw_history_list.append(f"{role_label}: {msg['content']}")
    raw_history_str = "\n".join(raw_history_list) if raw_history_list else "(No recent exchanges yet.)"
    
    # 3. Handle language preference
    pref_lang = owner_info.get("preferred_language")
    lang_instr = f"IMPORTANT: Your owner prefers to speak in {pref_lang}. Please respond ONLY in {pref_lang}." if pref_lang else ""
    
    # 4. Handle real-time awareness (Today's date and time)
    now = datetime.datetime.now()
    current_time_str = now.strftime("%A, %B %d, %Y, %I:%M %p")
    
    # 5. Fill the system prompt template with the latest reality
    formatted_system = SYSTEM_PROMPT.format(
        bot_name=bot_info.get("name") or "[Unknown/Not chosen yet]",
        bot_traits=", ".join(bot_info.get("personality_traits", [])) or "None identified yet.",
        current_time=current_time_str,
        relationship_stage=owner_info.get("relationship_stage", "stranger"),
        raw_history=raw_history_str,
        owner_facts=facts_str or "I don't know anything about my owner yet.",
        language_instruction=lang_instr
    )
    
    # 3. ROUTE TO MODELS (Tiered Router)
    # We pass the attachments_list down so tools called during the model loop can populate it.
    res = await get_model_response(
        memory, formatted_system, chat_history,
        image_data=image_data, attachments_list=attachments_list
    )
    
    # 4. POST-PROCESS ATTACHMENTS (GENERIC RELAY)
    import re
    attachment_path = None
    
    # Check if any tool captured an attachment during this generation cycle
    if attachments_list:
        attachment_path = attachments_list[0]
        print(f"AGENT: Using first attachment -> {attachment_path}")
    
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
    existing_memories = "\n".join([f"- {m}" for m in owner_facts.get("key_memories", [])])
    
    prompt = MEMORY_EXTRACTION_PROMPT.format(
        user_message=user_message,
        bot_response=bot_response,
        existing_facts=existing_facts if existing_facts else "None yet.",
        existing_traits=existing_traits if existing_traits else "None yet.",
        existing_memories=existing_memories if existing_memories else "None yet."
    )

    try:
        # Wrap background extraction in a strict timeout to prevent hangs
        await asyncio.wait_for(get_memory_extraction(memory, prompt), timeout=30.0)
    except asyncio.TimeoutError:
        print("WARNING: Background memory extraction timed out (30s). Skipping.")
    except Exception as e:
        print(f"ERROR: Background memory extraction failed: {e}")
    finally:
        # Sequential Writeback: Update timestamp only after abstraction logic is complete.
        # This prevents race conditions by ensuring only one write happens per conversation turn.
        memory.record_owner_reply()
        print(f"MEMORY: Background extraction complete and timestamp archived.")
