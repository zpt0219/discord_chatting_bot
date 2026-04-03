import json
from memory_manager import MemoryManager
from skills import get_all_openai_tools, execute_skill

try:
    from openai import AsyncOpenAI
except ImportError:
    pass

LOCAL_LLAMA_BASE_URL = "http://127.0.0.1:8888/v1"
LOCAL_LLAMA_API_KEY = "dummy_key"

openai_client = None

conversational_tools_openai = get_all_openai_tools()

def get_openai_client() -> 'AsyncOpenAI':
    """Lazy instantiates the local Llama.cpp client using OpenAI's wrapper format."""
    global openai_client
    if openai_client is None:
        try:
            from openai import AsyncOpenAI
            # Tell the OpenAI library to point to our local llama.cpp server
            openai_client = AsyncOpenAI(base_url=LOCAL_LLAMA_BASE_URL, api_key=LOCAL_LLAMA_API_KEY)
        except ImportError:
            pass
    return openai_client

async def _generate_with_local(formatted_system: str, chat_history: list) -> str:
    """
    Helper function to generate a response using the Local Llama Server.
    Includes a 2-step tool execution loop for seamless skill usage.
    """
    local_client = get_openai_client()
    if not local_client:
        raise Exception("Local client unavailable. OpenAI python package may not be installed.")
        
    # Prepend the dynamic memory system prompt to the user's historical Discord chat
    openai_messages = [{"role": "system", "content": formatted_system}] + chat_history
    
    # STEP 1: Ask the LLM to generate a response (providing the tools)
    response = await local_client.chat.completions.create(
        model="local-model", # Llama.cpp ignores this, but the OpenAI SDK requires it
        messages=openai_messages,
        max_tokens=8192,
        temperature=0.7,
        tools=conversational_tools_openai,
        timeout=300.0 # Increased timeout for slower local generation
    )
    
    message_obj = response.choices[0].message
    
    # STEP 2: Did the LLM decide to pause and call a tool?
    if message_obj.tool_calls:
        tool_call = message_obj.tool_calls[0]
        
        # Execute the matched python skill payload locally
        result_text = execute_skill(tool_call.function.name)
        
        # Inject the tool request reasoning back into the conversational loop
        openai_messages.append({
            "role": "assistant",
            "content": message_obj.content,
            "tool_calls": [tool_call.model_dump()]
        })
        
        # Inject the real-world output of the python script back to the LLM
        openai_messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "name": tool_call.function.name,
            "content": result_text
        })
        
        # STEP 3: Ask the LLM to generate the final chat response now that it has the tool's data
        response_two = await local_client.chat.completions.create(
            model="local-model",
            messages=openai_messages,
            max_tokens=8192,
            temperature=0.7,
            timeout=300.0
        )
        message_obj = response_two.choices[0].message
    
    # Final safety check: if the local model generated absolutely nothing, throw an error to trigger Claude Fallback
    reply = message_obj.content
    if reply and reply.strip():
        return reply.strip()
    raise Exception("Empty text returned by local model")


async def _extract_with_local(memory: MemoryManager, prompt: str):
    """
    Forces the local Llama model to output a strict JSON layout by utilizing
    the tool_choice schema parameter. This is used in the background to glean facts.
    """
    local_client = get_openai_client()
    if not local_client:
        raise Exception("OpenAI pip library not fully installed.")
        
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
                        "items": {"type": "string"},
                        "description": "Any new factual statements learned about the owner. Rephrase concisely. Omit if none."
                    },
                    "bot_name": {
                        "type": "string",
                        "description": "The name the bot has chosen or been given. Only include if explicitly decided."
                    },
                    "new_bot_traits": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Any new personality traits the bot exhibited or adopted. Omit if none."
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
                    memory.add_facts_about_owner(args["new_facts_about_owner"])
                
                bot_updates = {}
                if "bot_name" in args and args["bot_name"]:
                    bot_updates["name"] = args["bot_name"]
                if bot_updates:
                    memory.update_bot_identity(bot_updates)
                    
                if "new_bot_traits" in args and args["new_bot_traits"]:
                    memory.add_personality_traits(args["new_bot_traits"])
