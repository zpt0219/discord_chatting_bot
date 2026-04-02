import os
from anthropic import AsyncAnthropic
from memory_manager import MemoryManager

# We will initialize the client dynamically when needed to ensure env vars are loaded.
client = None

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

def get_client() -> AsyncAnthropic:
    global client
    if client is None:
        api_key = os.environ.get("claude_code_api_key") or os.environ.get("ANTHROPIC_API_KEY")
        client = AsyncAnthropic(api_key=api_key)
    return client

async def generate_response(memory: MemoryManager, chat_history: list) -> str:
    """
    chat_history is a list of dicts: [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
    """
    bot_info = memory.get_bot_identity()
    owner_info = memory.get_owner_relationship()
    
    bot_name = bot_info["name"] if bot_info["name"] else "Unknown (you haven't picked one yet)"
    bot_traits = ", ".join(bot_info["personality_traits"]) if bot_info["personality_traits"] else "None identified yet"
    owner_facts = "\n".join([f"- {f}" for f in owner_info["facts_about_owner"]]) if owner_info["facts_about_owner"] else "No facts known yet."
    
    formatted_system = SYSTEM_PROMPT.format(
        bot_name=bot_name,
        bot_traits=bot_traits,
        relationship_stage=owner_info["relationship_stage"],
        owner_facts=owner_facts
    )
    
    c = get_client()
    response = await c.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=256,
        temperature=0.7,
        system=formatted_system,
        messages=chat_history
    )
    
    return response.content[0].text

async def extract_and_update_memory(memory: MemoryManager, user_message: str, bot_response: str):
    """
    Analyzes the latest interaction in the background and extracts facts to update memory.
    """
    tools = [
        {
            "name": "update_memory",
            "description": "Updates persistent memory based on the latest conversation turns.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "new_facts_about_owner": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Any new factual statements learned about the owner. Rephrase concisely (e.g., 'Likes climbing', 'Lives in New York'). Omit if none."
                    },
                    "bot_name": {
                        "type": "string",
                        "description": "The name the bot has chosen or been given. Only include if explicitly decided in this turn."
                    },
                    "new_bot_traits": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Any new personality traits the bot exhibited or adopted (e.g., 'Sarcastic', 'Curious'). Omit if none."
                    }
                }
            }
        }
    ]
    
    prompt = f"""Analyze this recent exchange between the owner and the bot.
Owner: {user_message}
Bot: {bot_response}

Extract any NEW facts about the owner, any NEW name chosen for the bot, or any NEW personality traits the bot has shown.
If there's nothing new to extract, call the tool with empty arrays. Do not duplicate facts you might already guess."""

    try:
        c = get_client()
        response = await c.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=250,
            temperature=0.0,
            tools=tools,
            tool_choice={"type": "tool", "name": "update_memory"},
            messages=[{"role": "user", "content": prompt}]
        )
        
        # Parse the tool use block
        for block in response.content:
            if block.type == "tool_use" and block.name == "update_memory":
                args = block.input
                if "new_facts_about_owner" in args and args["new_facts_about_owner"]:
                    memory.add_facts_about_owner(args["new_facts_about_owner"])
                
                bot_updates = {}
                if "bot_name" in args and args["bot_name"]:
                    bot_updates["name"] = args["bot_name"]
                if bot_updates:
                    memory.update_bot_identity(bot_updates)
                    
                if "new_bot_traits" in args and args["new_bot_traits"]:
                    memory.add_personality_traits(args["new_bot_traits"])
                    
    except Exception as e:
        print(f"Failed to extract memory: {e}")
