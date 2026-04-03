import os
from anthropic import AsyncAnthropic
from memory_manager import MemoryManager
from skills import get_all_anthropic_tools, execute_skill

anthropic_client = None

conversational_tools_anthropic = get_all_anthropic_tools()

def get_anthropic_client() -> AsyncAnthropic:
    """Lazy instantiates the fallback Claude client if an Anthropic API Key is found."""
    global anthropic_client
    if anthropic_client is None:
        api_key = os.environ.get("claude_code_api_key") or os.environ.get("ANTHROPIC_API_KEY")
        anthropic_client = AsyncAnthropic(api_key=api_key)
    return anthropic_client

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
        max_tokens=256,
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
