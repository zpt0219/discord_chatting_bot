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

def _extract_text_from_content(content) -> str:
    """
    Extracts plain text from any content format:
    - Plain string -> returned as-is
    - List of dicts (e.g. [{"type": "text", "text": "..."}]) -> extracts text fields
    - List of Anthropic SDK objects (e.g. TextBlock, ToolUseBlock) -> extracts .text attributes
    - Anything else -> str() conversion
    """
    if isinstance(content, str):
        return content
    
    if isinstance(content, list):
        text_parts = []
        for block in content:
            # Handle plain dicts like {"type": "text", "text": "..."}
            if isinstance(block, dict):
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            # Handle plain strings in a list
            elif isinstance(block, str):
                text_parts.append(block)
            # Handle Anthropic SDK objects (TextBlock, ToolUseBlock, etc.)
            elif hasattr(block, "type"):
                if getattr(block, "type", None) == "text" and hasattr(block, "text"):
                    text_parts.append(block.text)
                # Skip tool_use, tool_result, and any other block types
        return " ".join(text_parts) if text_parts else ""
    
    # Fallback: convert to string
    return str(content) if content else ""


def _sanitize_history_for_claude(chat_history: list) -> list:
    """
    Claude's API is extremely strict about message formatting:
    1. Roles MUST strictly alternate: user -> assistant -> user -> assistant
    2. Every tool_use block MUST have a tool_result immediately after
    3. Content must be plain strings, not complex objects
    
    This function sanitizes raw chat history (especially from Discord sync)
    to satisfy these requirements by forcing ALL content to plain strings.
    """
    sanitized = []
    for msg in chat_history:
        role = msg.get("role", "user") if isinstance(msg, dict) else "user"
        content = msg.get("content", "") if isinstance(msg, dict) else str(msg)
        
        # Force content to be a plain string no matter what its original type is
        content = _extract_text_from_content(content)
        
        if not content.strip():
            continue
            
        # Merge consecutive messages from the same role
        if sanitized and sanitized[-1]["role"] == role:
            sanitized[-1]["content"] += "\n" + content
        else:
            sanitized.append({"role": role, "content": content})
    
    # Claude requires the first message to be from 'user'
    while sanitized and sanitized[0]["role"] != "user":
        sanitized.pop(0)
    
    # Claude requires the last message to be from 'user'
    while sanitized and sanitized[-1]["role"] != "user":
        sanitized.pop()
    
    return sanitized


def _purge_orphaned_tool_blocks(messages: list) -> list:
    """
    Nuclear safety net: Scans the messages array for any content that contains
    tool_use blocks without paired tool_result blocks. Strips them entirely.
    This catches edge cases that the sanitizer might miss (e.g., Anthropic SDK objects).
    """
    def _has_tool_use(content):
        """Check if content contains tool_use blocks in any format."""
        if isinstance(content, str):
            return False
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    return True
                if hasattr(block, "type") and getattr(block, "type", None) == "tool_use":
                    return True
        return False
    
    def _has_tool_result(content):
        """Check if content contains tool_result blocks."""
        if isinstance(content, str):
            return False
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    return True
        return False
    
    cleaned = []
    for i, msg in enumerate(messages):
        content = msg.get("content", "") if isinstance(msg, dict) else ""
        
        if _has_tool_use(content):
            # Check if the NEXT message has a matching tool_result
            next_msg = messages[i + 1] if i + 1 < len(messages) else None
            next_content = next_msg.get("content", "") if isinstance(next_msg, dict) else ""
            
            if _has_tool_result(next_content):
                # Proper pairing exists, keep both
                cleaned.append(msg)
            else:
                # Orphaned tool_use! Convert to plain text
                text = _extract_text_from_content(content)
                if text.strip():
                    cleaned.append({"role": msg.get("role", "assistant"), "content": text})
                print(f"WARNING: Purged orphaned tool_use block from message {i}")
        else:
            cleaned.append(msg)
    
    return cleaned


async def _generate_with_claude(formatted_system: str, chat_history: list, image_data: list = None) -> str:
    """
    Helper to generate a response using Anthropic Claude.
    Used for complex queries or as a robust fallback system.
    Supports vision: pass image_data to analyze images.
    """
    c = get_anthropic_client()
    
    # Sanitize raw chat history to meet Claude's strict formatting rules
    clean_history = _sanitize_history_for_claude(chat_history)
    
    # If image data is provided, inject it into the last user message as multimodal content blocks
    if image_data and clean_history:
        last_msg = clean_history[-1]
        if last_msg["role"] == "user":
            # Build the content as a list of blocks: image(s) first, then text
            content_blocks = []
            for img in image_data:
                content_blocks.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": img["media_type"],
                        "data": img["base64"]
                    }
                })
            # Append the user's text after the images
            text = last_msg["content"] if last_msg["content"] != "[sent an image]" else "What is in this image?"
            content_blocks.append({"type": "text", "text": text})
            clean_history[-1] = {"role": "user", "content": content_blocks}
    
    # Final safety check: validate that no orphaned tool_use blocks exist in the messages
    clean_history = _purge_orphaned_tool_blocks(clean_history)
    
    # STEP 1: Initial call passing tools
    claude_res = await c.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=256,
        temperature=0.7,
        system=formatted_system,
        tools=conversational_tools_anthropic,
        messages=clean_history
    )
    
    # STEP 2: Intercept tool use (handle multiple tools if needed)
    if claude_res.stop_reason == "tool_use":
        tool_results = []
        for block in claude_res.content:
            if getattr(block, "type", None) == "tool_use":
                result_text = await execute_skill(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_text
                })
        
        # Layout Anthropic's strict multi-turn tool format memory block
        temp_history = list(clean_history)
        temp_history.append({"role": "assistant", "content": claude_res.content})
        temp_history.append({"role": "user", "content": tool_results})
        
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
                    "items": {
                        "type": "object",
                        "properties": {
                            "category": {
                                "type": "string",
                                "enum": ["identity", "interests", "preferences", "routine", "other"],
                                "description": "Relationship category (identity, interests, preferences, routine, or other)."
                            },
                            "text": {
                                "type": "string",
                                "description": "The fact itself to remember."
                            }
                        },
                        "required": ["category", "text"]
                    }
                },
                "bot_name": {
                    "type": "string"
                },
                "new_bot_traits": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "preferred_language": {
                    "type": "string",
                    "description": "The language the owner wants the bot to speak in. Only include if the owner explicitly asks to switch languages."
                },
                "new_summarized_memory": {
                    "type": "string",
                    "description": "A high-level abstraction or summary of a significant conversation segment. Omit if the exchange is mundane."
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
            
            if "new_summarized_memory" in args and args["new_summarized_memory"]:
                memory.add_summarized_memory(args["new_summarized_memory"])
