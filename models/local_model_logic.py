import os
import json
from memory_manager import MemoryManager
from skills import get_all_openai_tools, execute_skill

try:
    from openai import AsyncOpenAI
except ImportError:
    pass

LOCAL_LLAMA_BASE_URL = os.getenv("LOCAL_LLM_SERVER", "")
LOCAL_LLAMA_API_KEY = "dummy_key"

openai_client = None

conversational_tools_openai = get_all_openai_tools()

def get_openai_client() -> 'AsyncOpenAI':
    """Lazy instantiates the local Llama.cpp client using OpenAI's wrapper format."""
    global openai_client
    
    # Dynamically check for the env var if it wasn't caught at module-level (import order safety)
    url = LOCAL_LLAMA_BASE_URL or os.getenv("LOCAL_LLM_SERVER", "")
    if not url:
        return None
        
    if openai_client is None:
        try:
            from openai import AsyncOpenAI
            # Tell the OpenAI library to point to our local llama.cpp server
            openai_client = AsyncOpenAI(base_url=url, api_key=LOCAL_LLAMA_API_KEY)
        except ImportError:
            pass
    return openai_client

async def _generate_with_local(memory: MemoryManager, formatted_system: str, chat_history: list, attachments_list: list = None) -> str:
    """
    Helper function to generate a response using the Local Llama Server.
    Includes a 2-step tool execution loop for seamless skill usage.
    """
    local_client = get_openai_client()
    if not local_client:
        raise Exception("Local Llama server is not configured in .env (LOCAL_LLM_SERVER) or 'openai' library is missing.")
        
    # Prepend the dynamic memory system prompt to the user's historical Discord chat
    openai_messages = [{"role": "system", "content": formatted_system}] + list(chat_history)
    current_turn = 0
    max_turns = 5
    
    while current_turn < max_turns:
        current_turn += 1
        
        response = await local_client.chat.completions.create(
            model="local-model",
            messages=openai_messages,
            max_tokens=8192,
            temperature=0.7,
            tools=conversational_tools_openai,
            timeout=300.0
        )
        
        message_obj = response.choices[0].message
        
        # Standardize message format for history
        assistant_msg = {
            "role": "assistant",
            "content": message_obj.content
        }
        if message_obj.tool_calls:
            assistant_msg["tool_calls"] = [tc.model_dump() for tc in message_obj.tool_calls]
            
        openai_messages.append(assistant_msg)
        
        if message_obj.tool_calls:
            for tool_call in message_obj.tool_calls:
                # Execute the skill
                args = {}
                if tool_call.function.arguments:
                    try: args = json.loads(tool_call.function.arguments)
                    except: pass
                
                result_text = await execute_skill(tool_call.function.name, args, memory=memory, attachments_list=attachments_list)
                
                # Append tool result
                openai_messages.append({
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
        # Limit reached
        final_reply = openai_messages[-1].get("content") or "*(Thinking timed out...)*"
        return final_reply.strip()
    
    raise Exception("Empty text returned by local model")


async def _extract_with_local(memory: MemoryManager, prompt: str):
    """
    Forces the local Llama model to output a strict JSON layout by utilizing
    the tool_choice schema parameter. This is used in the background to glean facts.
    """
    local_client = get_openai_client()
    if not local_client:
        raise Exception("Local Llama server is not configured in .env (LOCAL_LLM_SERVER) or 'openai' library is missing.")
        
    # We define a strict update schema that forces arrays for facts
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
                                    "description": "Biological/social identity, hobby/interest, bot behavior preference, or daily schedule."
                                },
                                "text": {
                                    "type": "string",
                                    "description": "The fact itself. Rephrase concisely."
                                }
                            },
                            "required": ["category", "text"]
                        },
                        "description": "Any new factual statements learned about the owner. Categorize each one. Omit if none."
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
                        "description": "The language the owner wants the bot to speak in. Only include if the owner explicitly asks to switch languages (e.g. 'speak English', 'use Chinese')."
                    },
                    "new_key_memory": {
                        "type": "string",
                        "description": "A highly concise, one-sentence snapshot of a significant conversation segment. Omit if the exchange is mundane. Avoid long narratives."
                    }
                }
            }
        }
    }]
    
    # We use tool_choice to explicitly 'force' the model to return this JSON tool blob
    response = await local_client.chat.completions.create(
        model="local-model",
        messages=[{"role": "user", "content": prompt}],
        tools=openai_tools,
        tool_choice="required", # Local server expects a string value like 'required' instead of the strict OpenAI object schema
        temperature=0.0, # Zero temperature is critical for strict JSON background formatting
        timeout=300.0
    )
    
    tool_calls = response.choices[0].message.tool_calls
    if tool_calls:
        for tool_call in tool_calls:
            if tool_call.function.name == "update_memory":
                # Parse the raw JSON payload successfully
                args = json.loads(tool_call.function.arguments)
                
                # Update underlying JSON Data logic safely
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
