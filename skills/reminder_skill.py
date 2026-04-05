import time

# =======================================================
# REMINDER SKILL (TOOL CALLING)
# =======================================================

def get_openai_schema():
    return {
        "type": "function",
        "function": {
            "name": "set_reminder",
            "description": "Sets a reminder for the owner to trigger after a certain number of minutes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "minutes": {
                        "type": "integer",
                        "description": "How many minutes from now to trigger the reminder."
                    },
                    "message": {
                        "type": "string",
                        "description": "The reminder message to send to the owner."
                    }
                },
                "required": ["minutes", "message"]
            }
        }
    }

def get_anthropic_schema():
    return {
        "name": "set_reminder",
        "description": "Sets a reminder for the owner to trigger after a certain number of minutes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "minutes": {
                    "type": "integer",
                    "description": "How many minutes from now to trigger the reminder."
                },
                "message": {
                    "type": "string",
                    "description": "The reminder message to send to the owner."
                }
            },
            "required": ["minutes", "message"]
        }
    }

def execute(arguments: dict = None, memory=None) -> str:
    """
    Executes the reminder setting logic.
    Requires the shared MemoryManager instance from bot.py.
    """
    print("DEBUG: Reminder tool called with arguments:", arguments)
    if not arguments or "minutes" not in arguments or "message" not in arguments:
        return "Reminder failed: Missing 'minutes' or 'message' field."
        
    minutes = arguments["minutes"]
    message = arguments["message"]
    
    if not memory:
        return "Reminder failed: Memory system unavailable for tool execution."
        
    try:
        target_time = memory.add_reminder(minutes, message)
        readable_time = time.strftime('%H:%M:%S', time.localtime(target_time))
        return f"OK. I've set a reminder for you in {minutes} minute(s). I will DM you the message '{message}' at {readable_time}."
    except Exception as e:
        return f"Could not set reminder. Tool failed with error: {str(e)}"
