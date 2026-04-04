import urllib.request

# =======================================================
# WEATHER SKILL (TOOL CALLING)
# =======================================================
# Grants the LLM access to real-world weather data without needing an API key
# by utilizing the incredible free open-source wttr.in service.

def get_openai_schema():
    """Defines the tool for the Local OpenAI SDK (Llama.cpp)."""
    return {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Checks the current real-world weather for a specified location.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "The city name, e.g. 'San Francisco', 'New York', or 'London'"
                    }
                },
                "required": ["location"]
            }
        }
    }

def get_anthropic_schema():
    """Defines the tool for the Claude Router Fallback layout."""
    return {
        "name": "get_weather",
        "description": "Checks the current real-world weather for a specified location.",
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "The city name, e.g. 'San Francisco', 'New York', or 'London'"
                }
            },
            "required": ["location"]
        }
    }

def execute(arguments: dict = None) -> str:
    """
    Pings wttr.in for formatted short-text weather data.
    Defaults to San Francisco if the LLM hallucinated the arguments variable.
    """
    print(f"DEBUG: Weather tool called with arguments: {arguments}")
    location = "San Francisco"
    if arguments and "location" in arguments:
        location = arguments["location"]
        
    try:
        # Format=4 returns a concise, single-line weather string (e.g., San Francisco: ⛅️ +11°C)
        # We must replace spaces with plus signs for the URL parameters
        escaped_loc = location.replace(" ", "+")
        req = urllib.request.Request(
            f"https://wttr.in/{escaped_loc}?format=4", 
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        
        with urllib.request.urlopen(req, timeout=5) as response:
            weather_data = response.read().decode('utf-8').strip()
            return f"The current weather data found online: {weather_data}"
            
    except Exception as e:
        return f"Could not fetch weather data online for '{location}'. Tool failed."
