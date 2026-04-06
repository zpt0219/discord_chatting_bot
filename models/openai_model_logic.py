import os
import json
from memory_manager import MemoryManager
from skills import get_all_openai_tools, execute_skill

try:
    from openai import AsyncOpenAI
except ImportError:
    pass

# ===============================================
# OPENAI CLOUD MODEL (THIRD-TIER FALLBACK)
# ===============================================
# This module connects to OpenAI's cloud API (e.g., GPT-4o) as a last-resort
# fallback when both the local Llama server and Claude are unavailable.
# It uses the same OpenAI SDK as the local model, but pointed at OpenAI's real servers.

openai_cloud_client = None

conversational_tools_openai = get_all_openai_tools()

def get_openai_cloud_client() -> 'AsyncOpenAI':
    """Lazy instantiates the OpenAI cloud client using the OPENAI_API_KEY env var."""
    global openai_cloud_client
    if openai_cloud_client is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise Exception("OPENAI_API_KEY not found in environment variables.")
        try:
            from openai import AsyncOpenAI
            openai_cloud_client = AsyncOpenAI(api_key=api_key)
        except ImportError:
            raise Exception("OpenAI python package is not installed.")
    return openai_cloud_client


async def _generate_with_openai(memory: MemoryManager, formatted_system: str, chat_history: list, image_data: list = None) -> str:
    """
    Tier 3 / Fallback Specialist: Generates a response using OpenAI's GPT-4o.
    - PRIMARY: Handles all advanced fallback tasks if Claude is unavailable.
    - FALLBACK: Acts as the last-resort text provider if Local Llama and Claude both fail.
    - FALLBACK: Acts as the secondary vision provider if Claude fails.
    """
    client = get_openai_cloud_client()

    openai_messages = [{"role": "system", "content": formatted_system}] + list(chat_history)
    
    # If image data is provided, inject it into the last user message as multimodal content blocks
    if image_data and openai_messages:
        for i in range(len(openai_messages) - 1, -1, -1):
            if openai_messages[i]["role"] == "user":
                text = openai_messages[i]["content"]
                if text == "[sent an image]":
                    text = "What is in this image?"
                content_blocks = [{"type": "text", "text": text}]
                for img in image_data:
                    content_blocks.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{img['media_type']};base64,{img['base64']}"
                        }
                    })
                openai_messages[i] = {"role": "user", "content": content_blocks}
                break

    # RECURSIVE TOOL LOOP: Support multi-step research or planning (max 5 turns)
    messages = openai_messages
    current_turn = 0
    max_turns = 5

    while current_turn < max_turns:
        current_turn += 1
        
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            max_tokens=1024,
            temperature=0.7,
            tools=conversational_tools_openai,
            timeout=60.0
        )
        
        message_obj = response.choices[0].message
        
        # OpenAI requires tool_calls to be dumped if being sent back in history
        assistant_msg = {
            "role": "assistant",
            "content": message_obj.content
        }
        if message_obj.tool_calls:
            assistant_msg["tool_calls"] = [tc.model_dump() for tc in message_obj.tool_calls]
        
        messages.append(assistant_msg)

        if message_obj.tool_calls:
            # 1. Execute all requested tools
            for tool_call in message_obj.tool_calls:
                args = {}
                if tool_call.function.arguments:
                    try: args = json.loads(tool_call.function.arguments)
                    except: pass

                result_text = await execute_skill(tool_call.function.name, args, memory=memory)

                # 2. Append tool result for the next turn
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_call.function.name,
                    "content": result_text
                })
        else:
            # Turn complete!
            reply = message_obj.content
            if reply and reply.strip():
                return reply.strip()
            break
    else:
        # Loop limit reached
        final_reply = messages[-1].get("content") or "*(Thinking timed out...)*"
        return final_reply.strip()

    raise Exception("Empty or invalid response from OpenAI cloud model")


async def _extract_with_openai(memory: MemoryManager, prompt: str):
    """
    Background memory extraction using OpenAI's cloud API.
    Used as a last-resort fallback when both local and Claude extraction fail.
    """
    client = get_openai_cloud_client()

    openai_tools = [{
        "type": "function",
        "function": {
            "name": "update_memory",
            "description": "Updates persistent memory based on the latest conversation turns.",
            "parameters": {
                "type": "object",
                "properties": {
                    "new_facts_about_owner": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "category": {
                                    "type": "string",
                                    "enum": ["identity", "interests", "preferences", "routine", "other"],
                                    "description": "Category: identity, interests, preferences, routine, or other."
                                },
                                "text": {
                                    "type": "string",
                                    "description": "The fact itself to remember."
                                }
                            },
                            "required": ["category", "text"]
                        },
                        "description": "Any new factual statements learned about the owner. Categorize each one."
                    },
                    "bot_name": {
                        "type": "string",
                        "description": "The name the bot has chosen or been given. Only include if explicitly decided."
                    },
                    "new_bot_traits": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Any new personality traits the bot exhibited or adopted. Omit if none."
                    },
                    "preferred_language": {
                        "type": "string",
                        "description": "The language the owner wants the bot to speak in. Only include if the owner explicitly asks to switch languages."
                    },
                    "new_key_memory": {
                        "type": "string",
                        "description": "A highly concise, one-sentence snapshot of a significant conversation segment. Omit if the exchange is mundane. Avoid long narratives."
                    }
                }
            }
        }
    }]

    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        tools=openai_tools,
        tool_choice={"type": "function", "function": {"name": "update_memory"}},
        temperature=0.0,
        timeout=60.0
    )

    tool_calls = response.choices[0].message.tool_calls
    if tool_calls:
        for tool_call in tool_calls:
            if tool_call.function.name == "update_memory":
                args = json.loads(tool_call.function.arguments)

                if "new_facts_about_owner" in args and args["new_facts_about_owner"]:
                    memory.add_categorized_facts(args["new_facts_about_owner"])

                bot_updates = {}
                if "bot_name" in args and args["bot_name"]:
                    bot_updates["name"] = args["bot_name"]
                if bot_updates:
                    memory.update_bot_identity(bot_updates)

                if "new_bot_traits" in args and args["new_bot_traits"]:
                    memory.add_personality_traits(args["new_bot_traits"])

                if "preferred_language" in args and args["preferred_language"]:
                    memory.update_preferred_language(args["preferred_language"])
                
                if "new_key_memory" in args and args["new_key_memory"]:
                    memory.add_key_memory(args["new_key_memory"])
