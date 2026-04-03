from .time_skill import get_openai_schema as time_openai
from .time_skill import get_anthropic_schema as time_anthropic
from .time_skill import execute as time_execute

from .weather_skill import get_openai_schema as weather_openai
from .weather_skill import get_anthropic_schema as weather_anthropic
from .weather_skill import execute as weather_execute

# =======================================================
# SKILL ROUTER ARCHITECTURE
# =======================================================
# This file acts as the central switchboard for all bot tools (skills).
# When you want to add a new skill to the bot (like checking weather, fetching crypto prices, etc.),
# you create a new file in this directory and import its schemas and execution logic here.

def get_all_openai_tools():
    """
    Aggregates all OpenAI formatted tool schemas from the skills folder.
    This is passed to the Local Llama Server when booting up its message context window.
    """
    return [
        time_openai(),
        weather_openai()
    ]

def get_all_anthropic_tools():
    """
    Aggregates all Anthropic formatted tool schemas from the skills folder.
    This is passed to the Claude API to ensure seamless fallback compatibility if the local server fails.
    """
    return [
        time_anthropic(),
        weather_anthropic()
    ]

def execute_skill(name: str, arguments: dict = None) -> str:
    """
    The central python executable router.
    When an LLM (either Local or Claude) decides it wants to use a tool, it halts text generation
    and passes the requested tool's 'name' to this function. This function maps that name 
    to the correct python script in this folder, executes it, and returns the real-world data back to the LLM.
    """
    if name == "get_current_time":
        return time_execute(arguments)
    elif name == "get_weather":
        return weather_execute(arguments)
        
    return f"Skill execution failed: Unknown tool '{name}'."
