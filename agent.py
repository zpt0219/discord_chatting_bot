import os
import json
import datetime
from anthropic import AsyncAnthropic
from memory_manager import MemoryManager

# Try to import OpenAI for the local llama.cpp server compatibility
try:
    from openai import AsyncOpenAI
except ImportError:
    pass

# ===============================================
# SERVER CONFIGURATION
# ===============================================
# We use a locally hosted Llama.cpp server as our primary fast inference engine.
# It uses an OpenAI-compatible API structure, so we interact with it using the AsyncOpenAI python package.
LOCAL_LLAMA_BASE_URL = "http://127.0.0.1:8888/v1"
LOCAL_LLAMA_API_KEY = "dummy_key" # Local servers typically ignore the key

# Global clients mapped to None initially so we can instantiate them lazily
anthropic_client = None
openai_client = None

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
# EXTERNAL SKILL IMPORTS
# ===============================================
# We import our gracefully separated skills from the 'skills' module package.
# This keeps agent.py clean and purely focused on LLM routing logic.
from skills import get_all_openai_tools, get_all_anthropic_tools, execute_skill
conversational_tools_openai = get_all_openai_tools()
conversational_tools_anthropic = get_all_anthropic_tools()

# ===============================================
# CLIENT FACTORIES
# ===============================================

def get_anthropic_client() -> AsyncAnthropic:
    """Lazy instantiates the fallback Claude client if an Anthropic API Key is found."""
    global anthropic_client
    if anthropic_client is None:
        api_key = os.environ.get("claude_code_api_key") or os.environ.get("ANTHROPIC_API_KEY")
        anthropic_client = AsyncAnthropic(api_key=api_key)
    return anthropic_client

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
        max_tokens=256,
        temperature=0.7,
        tools=conversational_tools_openai,
        timeout=120.0 # High timeout for slower local generation
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
            max_tokens=256,
            temperature=0.7,
            timeout=120.0
        )
        message_obj = response_two.choices[0].message
    
    # Final safety check: if the local model generated absolutely nothing, throw an error to trigger Claude Fallback
    reply = message_obj.content
    if reply and reply.strip():
        return reply.strip()
    raise Exception("Empty text returned by local model")

async def _generate_with_claude(formatted_system: str, chat_history: list) -> str:
    """
    Helper to generate a response using Anthropic Claude.
    Used for complex queries or as a robust fallback system.
    """
    c = get_anthropic_client()
    
    # STEP 1: Initial call passing tools
    claude_res = await c.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=256,
        temperature=0.7,
        system=formatted_system,
        tools=conversational_tools_anthropic,
        messages=chat_history
    )
    
    # STEP 2: Intercept tool use
    if claude_res.stop_reason == "tool_use":
        tool_call = next(block for block in claude_res.content if block.type == "tool_use")
        result_text = execute_skill(tool_call.name)
        
        # Layout Anthropic's strict multi-turn tool format memory block
        temp_history = list(chat_history)
        temp_history.append({"role": "assistant", "content": claude_res.content})
        temp_history.append({
            "role": "user", 
            "content": [{"type": "tool_result", "tool_use_id": tool_call.id, "content": result_text}]
        })
        
        # STEP 3: Final Synthesis
        claude_res_two = await c.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=256,
            temperature=0.7,
            system=formatted_system,
            tools=conversational_tools_anthropic,
            messages=temp_history
        )
        final_reply = claude_res_two.content[0].text
    else:
        final_reply = claude_res.content[0].text
    
    # Fail cleanly even if Claude fails
    if final_reply and final_reply.strip():
        return final_reply.strip()
    return "*(The bot seems to have lost its train of thought...)*"

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
        tool_choice={"type": "function", "function": {"name": "update_memory"}},
        temperature=0.0, # Zero temperature is critical for strict JSON background formatting
        timeout=120.0
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


async def _extract_with_claude(memory: MemoryManager, prompt: str):
    """Fallback extraction using Claude in case the Local Model fails the strict JSON schema."""
    anthropic_tools = [{
        "name": "update_memory",
        "description": "Updates persistent memory based on the latest conversation turns.",
        "input_schema": {
            "type": "object",
            "properties": {
                "new_facts_about_owner": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "bot_name": {
                    "type": "string"
                },
                "new_bot_traits": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            }
        }
    }]
    
    c = get_anthropic_client()
    response = await c.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=250,
        temperature=0.0,
        tools=anthropic_tools,
        tool_choice={"type": "tool", "name": "update_memory"},
        messages=[{"role": "user", "content": prompt}]
    )
    
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
