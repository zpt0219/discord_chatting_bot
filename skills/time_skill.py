import datetime

# =======================================================
# TIME SKILL (TOOL CALLING)
# =======================================================
# This encapsulates a single 'capability' for our agent. 
# AI models cannot inherently tell time because their knowledge cutoff is frozen, 
# so we give them this tool to temporarily escape their sandbox and check the host computer's clock.

def get_openai_schema():
    """
    The strict JSON Schema defining this tool for the Local OpenAI SDK (used by Llama.cpp).
    OpenAI formatting requires 'type': 'function' and nests the properties inside 'parameters'.
    """
    return {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "Checks the current real-world date and time.",
            "parameters": {
                "type": "object",
                "properties": {} # No inputs (like location) are required to check local system time
            }
        }
    }

def get_anthropic_schema():
    """
    The strict JSON Schema defining this tool for the Claude API.
    Anthropic formatting requires the properties to be nested inside an 'input_schema' block.
    By keeping both isolated here, the agent.py router can grab whatever it needs instantly.
    """
    return {
        "name": "get_current_time",
        "description": "Checks the current real-world date and time.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    }

def execute(arguments: dict = None) -> str:
    """
    The actual python payload that executes when the LLM triggers the tool.
    It returns a natural string describing the date and time, which the LLM will 
    read and then incorporate into its next conversational reply to the user.
    """
    print(f"DEBUG: Time tool called with arguments: {arguments}")
    return datetime.datetime.now().strftime("The current date and time is: %A, %B %d, %Y %I:%M %p")
