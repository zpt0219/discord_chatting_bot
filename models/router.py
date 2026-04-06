import settings
from models.local_model_logic import _generate_with_local, _extract_with_local, LOCAL_LLAMA_BASE_URL
from models.claude_model_logic import _generate_with_claude, _extract_with_claude
from models.openai_model_logic import _generate_with_openai, _extract_with_openai

# ===============================================
# TIERED LLM ROUTER
# ===============================================

def is_complex_query(user_message: str) -> bool:
    """
    A fast heuristics router to determine query complexity.
    """
    msg = user_message.lower()
    len_threshold = settings.ROUTER_COMPLEXITY_LEN_THRESHOLD
    keywords = settings.ROUTER_COMPLEX_KEYWORDS
    
    if len(msg) > len_threshold or any(keyword in msg for keyword in keywords):
        return True
    return False

async def get_model_response(memory, formatted_system, chat_history, image_data=None) -> str:
    """
    Orchestrates the tiered response generation (Llama -> OpenAI -> Claude).
    """
    latest_user_msg = next((msg["content"] for msg in reversed(chat_history) if msg["role"] == "user"), "")
    
    # TIER 1-2: IMAGE PATH (OpenAI -> Claude)
    if image_data:
        print(f"ROUTER: Image detected -> Sending to OpenAI (Tier 2 Vision).")
        try:
            return await _generate_with_openai(memory, formatted_system, chat_history, image_data=image_data)
        except Exception as e:
            print(f"Notice: OpenAI vision failed ({e}). Falling back to Tier 3 (Claude)...")
            try:
                return await _generate_with_claude(memory, formatted_system, chat_history, image_data=image_data)
            except Exception as e2:
                print(f"Critical: Both vision providers failed ({e2}).")
                return settings.ERROR_MSG_VISION
    
    # TIER 1-3: TEXT PATH
    if not is_complex_query(latest_user_msg) and LOCAL_LLAMA_BASE_URL:
        print(f"ROUTER: Message is simple -> Sending to Local Llama.")
        try:
            return await _generate_with_local(memory, formatted_system, chat_history)
        except Exception as e:
            print(f"Notice: Local Llama failed ({e}). Falling back to OpenAI...")
            try:
                return await _generate_with_openai(memory, formatted_system, chat_history)
            except Exception as e2:
                print(f"Notice: OpenAI also failed ({e2}). Falling back to Claude...")
                try:
                    return await _generate_with_claude(memory, formatted_system, chat_history)
                except Exception as e3:
                    print(f"Critical: All 3 providers failed ({e3}).")
                    return settings.ERROR_MSG_GENERIC
    else:
        provider = "OpenAI" if not is_complex_query(latest_user_msg) else "OpenAI (Complex)"
        print(f"ROUTER: Sending to {provider}.")
        try:
            return await _generate_with_openai(memory, formatted_system, chat_history)
        except Exception as e:
            print(f"Notice: OpenAI failed ({e}). Falling back to Claude...")
            try:
                return await _generate_with_claude(memory, formatted_system, chat_history)
            except Exception as e2:
                print(f"Critical: Claude also failed ({e2}).")
                return settings.ERROR_MSG_GENERIC

async def get_memory_extraction(memory, prompt):
    """
    Orchestrates the tiered background memory extraction.
    """
    try:
        await _extract_with_local(memory, prompt)
    except Exception as e:
        print(f"Notice: Local Llama tool extraction failed ({e}). Falling back to OpenAI...")
        try:
            await _extract_with_openai(memory, prompt)
        except Exception as e2:
            print(f"Notice: OpenAI extraction also failed ({e2}). Falling back to Claude...")
            try:
                await _extract_with_claude(memory, prompt)
            except Exception as e3:
                print(f"Critical: All 3 extraction providers failed: {e3}")
                # We do not raise here to avoid disrupting the main process
