import os

def get_openai_schema():
    return {
        "type": "function",
        "function": {
            "name": "show_identity_portrait",
            "description": "Call this whenever the user asks what the bot looks like, asks for a portrait, or a photo of the bot. It will trigger sending the bot's official head portrait image to the conversation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "The facial expression to show. Options: 'default', 'happy', 'thinking'.",
                        "enum": ["default", "happy", "thinking"]
                    }
                },
                "required": []
            }
        }
    }

def get_anthropic_schema():
    return {
        "name": "show_identity_portrait",
        "description": "Call this whenever the user asks what the bot looks like, asks for a portrait, or a photo of the bot. It will trigger sending the bot's official head portrait image to the conversation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "The facial expression to show. Options: 'default', 'happy', 'thinking'.",
                    "enum": ["default", "happy", "thinking"]
                }
            },
            "required": []
        }
    }

def execute(arguments=None):
    """
    Returns the path to the portrait image using a generic ATTACH tag.
    The agent will relay this path to Discord automagically.
    """
    print(f"DEBUG: Identity tool called with arguments: {arguments}")
    expr = "default"
    if arguments and "expression" in arguments:
        expr = arguments["expression"]
        
    if expr == "happy":
        path = "assets/bot_portrait_happy.png"
    elif expr == "thinking":
        path = "assets/bot_portrait_thinking.png"
    else:
        path = "assets/bot_portrait.png"
        
    return f"[ATTACH:{path}]"
