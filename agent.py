import os
import json
import datetime
from memory_manager import MemoryManager

from local_model.logic import _generate_with_local, _extract_with_local
from claude_model.logic import _generate_with_claude, _extract_with_claude

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
Relationship Stage: {relationship_stage} (0=just met, 1=acquaintance, 2=friend)
Facts you know about the owner:
{owner_facts}

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

async def generate_response(memory: MemoryManager, chat_history: list) -> str:
    """
    The main routing gateway. This function hydrates the system prompt with JSON memory, 
    evaluates query complexity, and delegates the task to the correct LLM.
    """
    # 1. Pull the raw JSON relationships and identities
    bot_info = memory.get_bot_identity()
    owner_info = memory.get_owner_relationship()
    
    # 2. Format them securely so the AI can parse them
    bot_name = bot_info["name"] if bot_info["name"] else "Unknown (haven't picked one yet)"
    bot_traits = ", ".join(bot_info["personality_traits"]) if bot_info["personality_traits"] else "None identified yet"
    owner_facts = "\n".join([f"- {f}" for f in owner_info["facts_about_owner"]]) if owner_info["facts_about_owner"] else "No facts known yet."
    
    formatted_system = SYSTEM_PROMPT.format(
        bot_name=bot_name,
        bot_traits=bot_traits,
        relationship_stage=owner_info["relationship_stage"],
        owner_facts=owner_facts
    )
    
    # 3. Extract the user's most recent message to evaluate for Routing
    latest_user_msg = next((msg["content"] for msg in reversed(chat_history) if msg["role"] == "user"), "")
    
    # ---- 4. ROUTER DECISION LOGIC ----
    if is_complex_query(latest_user_msg):
        # Complex paths require zero tolerance for latency/hallucination, go right to Cloud
        print(f"ROUTER: Message is complex -> Sending to Claude.")
        try:
            return await _generate_with_claude(formatted_system, chat_history)
        except Exception as e:
            print(f"Claude completely failed ({e}).")
            return "*(I tried to think really hard about that, but my brain hurts...)*"
    else:
        # Simple paths use the cheap, local fast path
        print(f"ROUTER: Message is simple -> Sending to Local Llama.")
        try:
            return await _generate_with_local(formatted_system, chat_history)
        except Exception as e:
            # But we gracefully degrade!
            # If the local server is turned off, times out, or hallucinates an empty response,
            # we seamlessly catch it and send it to Claude so the Discord Bot never appears 'offline'.
            print(f"Notice: Local Llama rejected the query or crashed ({e}). Falling back to Claude...")
            try:
                return await _generate_with_claude(formatted_system, chat_history)
            except Exception as e2:
                return "*(The bot seems to have lost its train of thought...)*"

# ===============================================
# BACKGROUND EXTRACTION (MEMORY UPDATES)
# ===============================================

async def extract_and_update_memory(memory: MemoryManager, user_message: str, bot_response: str):
    """
    Main entry point triggered seamlessly by bot.py in an async background loop.
    It feeds the last message to the tool extractors without slowing down the active conversation.
    """
    prompt = f"Analyze this recent exchange between the owner and the bot.\nOwner: {user_message}\nBot: {bot_response}\n\nExtract any NEW facts about the owner, any NEW name chosen for the bot, or any NEW personality traits the bot has shown."

    try:
        await _extract_with_local(memory, prompt)
    except Exception as e:
        print(f"Notice: Local Llama tool extraction failed ({e}). Falling back to Claude...")
        try:
            await _extract_with_claude(memory, prompt)
        except Exception as e2:
            print(f"Critical: Both local and fallback Claude memory extractions failed: {e2}")
