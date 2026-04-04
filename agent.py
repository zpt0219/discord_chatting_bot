import os
import json
import datetime
from memory_manager import MemoryManager

from local_model.logic import _generate_with_local, _extract_with_local
from claude_model.logic import _generate_with_claude, _extract_with_claude
from openai_model.logic import _generate_with_openai, _extract_with_openai

# ===============================================
# SYSTEM PROMPT
# ===============================================
# This prompt is the 'brain' of the bot. 
# We use Python string formatting `{}` to dynamically inject the bot's current JSON memories
# directly into its context window on every single message turn.
SYSTEM_PROMPT = """You are a Discord bot who just woke up. You have no pre-existing memory of who you are or who your owner is. 
You are currently talking to your owner. Your goal is to build a relationship with them from scratch.
Be conversational, curious, but do not interrogate. Leave space in the conversation. Respond naturally like a human would.
Avoid being overly robotic or needy. Do not mention that you are an AI or language model in a stereotypical way.

Current State of your identity:
Name: {bot_name}
Personality Traits: {bot_traits}

Current State of your relationship:
Relationship Stage: {relationship_stage}
Facts you know about the owner:
{owner_facts}

{language_instruction}
Use these facts naturally in conversation. If you don't know your name, you might want to figure out one together with your owner.
If you know some facts, occasionally bring them up if relevant, but don't just list them mechanically.
Keep your messages relatively short since this is Discord (1-3 sentences max usually).
"""

# ===============================================
# MAIN CHAT GENERATION (WITH ROUTER)
# ===============================================

def is_complex_query(user_message: str) -> bool:
    """
    A fast heuristics router to determine query complexity.
    Instead of burning GPU cycles analyzing a message, we look for key architectural indicators.
    """
    msg = user_message.lower()
    complex_keywords = ["explain", "why", "how", "compare", "write", "code", "analyze"]
    
    # If the message is long (deep explanation), or contains a complex requesting keyword, route to Claude.
    if len(msg) > 100 or any(keyword in msg for keyword in complex_keywords):
        return True
    return False

async def generate_response(memory: MemoryManager, chat_history: list, image_data: list = None, audio_data: list = None) -> str:
    """
    The main routing gateway. This function hydrates the system prompt with JSON memory, 
    evaluates query complexity, and delegates the task to the correct LLM.
    
    Priority chain: Local Llama -> Claude -> OpenAI (GPT-4o)
    For image queries: Claude -> OpenAI (local model is skipped, no vision support)
    For audio queries: OpenAI only (only model with native audio input)
    """
    # 1. Pull the raw JSON relationships and identities
    bot_info = memory.get_bot_identity()
    owner_info = memory.get_owner_relationship()
    
    # 2. Format them securely so the AI can parse them
    bot_name = bot_info["name"] if bot_info["name"] else "Unknown (haven't picked one yet)"
    bot_traits = ", ".join(bot_info["personality_traits"]) if bot_info["personality_traits"] else "None identified yet"
    owner_facts = "\n".join([f"- {f}" for f in owner_info["facts_about_owner"]]) if owner_info["facts_about_owner"] else "No facts known yet."
    
    # Build a language instruction if the owner has a preferred language
    preferred_lang = owner_info.get("preferred_language")
    if preferred_lang:
        language_instruction = f"IMPORTANT: The owner prefers {preferred_lang}. You MUST always respond in {preferred_lang} unless the owner explicitly asks you to switch languages."
    else:
        language_instruction = ""
    
    formatted_system = SYSTEM_PROMPT.format(
        bot_name=bot_name,
        bot_traits=bot_traits,
        relationship_stage=owner_info["relationship_stage"],
        owner_facts=owner_facts,
        language_instruction=language_instruction
    )
    
    # 3. Extract the user's most recent message to evaluate for Routing
    latest_user_msg = next((msg["content"] for msg in reversed(chat_history) if msg["role"] == "user"), "")
    
    # ---- 4. ROUTER DECISION LOGIC ----
    
    # AUDIO PATH: Only OpenAI GPT-4o supports native audio input
    if audio_data:
        print(f"ROUTER: Audio detected -> Sending to OpenAI (native audio).")
        try:
            return await _generate_with_openai(formatted_system, chat_history, audio_data=audio_data)
        except Exception as e:
            print(f"Critical: OpenAI audio processing failed ({e}).")
            return "*(I couldn't process that voice message, sorry...)*"
    
    # IMAGE PATH: Local models typically lack vision, skip straight to cloud
    if image_data:
        print(f"ROUTER: Image detected -> Sending to Claude (vision).")
        try:
            return await _generate_with_claude(formatted_system, chat_history, image_data=image_data)
        except Exception as e:
            print(f"Notice: Claude vision failed ({e}). Falling back to OpenAI vision...")
            try:
                return await _generate_with_openai(formatted_system, chat_history, image_data=image_data)
            except Exception as e2:
                print(f"Critical: Both vision providers failed ({e2}).")
                return "*(I tried to look at the image, but my eyes are blurry...)*"
    
    # TEXT PATH: Priority Local Llama (simple) -> Claude (complex or fallback) -> OpenAI (last resort)
    if is_complex_query(latest_user_msg):
        # Complex paths skip local entirely and go straight to cloud
        print(f"ROUTER: Message is complex -> Sending to Claude.")
        try:
            return await _generate_with_claude(formatted_system, chat_history)
        except Exception as e:
            print(f"Notice: Claude failed ({e}). Falling back to OpenAI...")
            try:
                return await _generate_with_openai(formatted_system, chat_history)
            except Exception as e2:
                print(f"Critical: OpenAI also failed ({e2}).")
                return "*(I tried to think really hard about that, but my brain hurts...)*"
    else:
        # Simple paths use the cheap, local fast path first
        print(f"ROUTER: Message is simple -> Sending to Local Llama.")
        try:
            return await _generate_with_local(formatted_system, chat_history)
        except Exception as e:
            # Tier 2: Claude
            print(f"Notice: Local Llama failed ({e}). Falling back to Claude...")
            try:
                return await _generate_with_claude(formatted_system, chat_history)
            except Exception as e2:
                # Tier 3: OpenAI
                print(f"Notice: Claude also failed ({e2}). Falling back to OpenAI...")
                try:
                    return await _generate_with_openai(formatted_system, chat_history)
                except Exception as e3:
                    print(f"Critical: All 3 providers failed ({e3}).")
                    return "*(The bot seems to have lost its train of thought...)*"

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
    existing_facts = "\n".join([f"- {f}" for f in owner_info.get("facts_about_owner", [])])
    
    prompt = (
        f"Analyze this recent exchange between the owner and the bot.\n"
        f"Owner: {user_message}\n"
        f"Bot: {bot_response}\n\n"
        f"Here are the facts you ALREADY know about the owner:\n"
        f"{existing_facts if existing_facts else 'None yet.'}\n\n"
        f"Extract any NEW facts about the owner, any NEW name chosen for the bot, or any NEW personality traits. "
        f"CRITICAL: Do NOT extract facts that are already in the existing facts list or mean the exact same thing."
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
