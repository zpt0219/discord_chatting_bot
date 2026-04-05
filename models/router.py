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

async def get_model_response(memory, formatted_system, chat_history, image_data=None, audio_data=None) -> str:
    """
    Orchestrates the tiered response generation (Llama -> Claude -> OpenAI).
    """
    latest_user_msg = next((msg["content"] for msg in reversed(chat_history) if msg["role"] == "user"), "")
    
    # TIER 0: AUDIO PATH (OpenAI Only)
    if audio_data:
        print(f"ROUTER: Audio detected -> Sending to OpenAI (Tier 3).")
        try:
            return await _generate_with_openai(memory, formatted_system, chat_history, audio_data=audio_data)
        except Exception as e:
            print(f"Critical: OpenAI audio processing failed ({e}).")
            return "*(I couldn't process that voice message, sorry...)*"
    
    # TIER 1-2: IMAGE PATH (Claude -> OpenAI)
    if image_data:
        print(f"ROUTER: Image detected -> Sending to Claude (Tier 2 Vision).")
        try:
            return await _generate_with_claude(memory, formatted_system, chat_history, image_data=image_data)
        except Exception as e:
            print(f"Notice: Claude vision failed ({e}). Falling back to Tier 3 (OpenAI)...")
            try:
                return await _generate_with_openai(memory, formatted_system, chat_history, image_data=image_data)
            except Exception as e2:
                print(f"Critical: Both vision providers failed ({e2}).")
                return "*(I tried to look at the image, but my eyes are blurry...)*"
    
    # TIER 1-3: TEXT PATH
    if not is_complex_query(latest_user_msg) and LOCAL_LLAMA_BASE_URL:
        print(f"ROUTER: Message is simple -> Sending to Local Llama.")
        try:
            return await _generate_with_local(memory, formatted_system, chat_history)
        except Exception as e:
            print(f"Notice: Local Llama failed ({e}). Falling back to Claude...")
            try:
                return await _generate_with_claude(memory, formatted_system, chat_history)
            except Exception as e2:
                print(f"Notice: Claude also failed ({e2}). Falling back to OpenAI...")
                try:
                    return await _generate_with_openai(memory, formatted_system, chat_history)
                except Exception as e3:
                    print(f"Critical: All 3 providers failed ({e3}).")
                    return "*(The bot seems to have lost its train of thought...)*"
    else:
        provider = "Claude" if not is_complex_query(latest_user_msg) else "Claude (Complex)"
        print(f"ROUTER: Sending to {provider}.")
        try:
            return await _generate_with_claude(memory, formatted_system, chat_history)
        except Exception as e:
            print(f"Notice: Claude failed ({e}). Falling back to OpenAI...")
            try:
                return await _generate_with_openai(memory, formatted_system, chat_history)
            except Exception as e2:
                print(f"Critical: OpenAI also failed ({e2}).")
                return "*(I tried to think really hard about that, but my brain hurts...)*"

async def get_memory_extraction(memory, prompt):
    """
    Orchestrates the tiered background memory extraction.
    """
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
                raise e3
