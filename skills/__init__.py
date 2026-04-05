from .time_skill import get_openai_schema as time_openai
from .time_skill import get_anthropic_schema as time_anthropic
from .time_skill import execute as time_execute

from .weather_skill import get_openai_schema as weather_openai
from .weather_skill import get_anthropic_schema as weather_anthropic
from .weather_skill import execute as weather_execute

from .search_skill import get_openai_schema as search_openai
from .search_skill import get_anthropic_schema as search_anthropic
from .search_skill import execute as search_execute

from .identity_skill import get_openai_schema as identity_openai
from .identity_skill import get_anthropic_schema as identity_anthropic
from .identity_skill import execute as identity_execute

from .brain_skill import get_openai_schema as brain_openai
from .brain_skill import get_anthropic_schema as brain_anthropic
from .brain_skill import execute as brain_execute

from .link_reader_skill import get_openai_schema as link_reader_openai
from .link_reader_skill import get_anthropic_schema as link_reader_anthropic
from .link_reader_skill import execute as link_reader_execute

from .news_skill import get_openai_schema as news_openai
from .news_skill import get_anthropic_schema as news_anthropic
from .news_skill import execute as news_execute

from .reminder_skill import get_openai_schema as reminder_openai
from .reminder_skill import get_anthropic_schema as reminder_anthropic
from .reminder_skill import execute as reminder_execute

import re

# =======================================================
# SKILL ROUTER ARCHITECTURE
# =======================================================
# This file acts as the central switchboard for all bot tools (skills).
# When you want to add a new skill to the bot (like checking weather, fetching crypto prices, etc.),
# you create a new file in this directory and import its schemas and execution logic here.

# Shared list that captures file attachment paths from tool results.
# agent.py reads and clears this after each generation cycle.
pending_attachments = []

def get_all_openai_tools():
    """
    Aggregates all OpenAI formatted tool schemas from the skills folder.
    This is passed to the Local Llama Server when booting up its message context window.
    """
    return [
        time_openai(),
        weather_openai(),
        search_openai(),
        identity_openai(),
        brain_openai(),
        link_reader_openai(),
        news_openai(),
        reminder_openai()
    ]

def get_all_anthropic_tools():
    """
    Aggregates all Anthropic formatted tool schemas from the skills folder.
    This is passed to the Claude API to ensure seamless fallback compatibility if the local server fails.
    """
    return [
        time_anthropic(),
        weather_anthropic(),
        search_anthropic(),
        identity_anthropic(),
        brain_anthropic(),
        link_reader_anthropic(),
        news_anthropic(),
        reminder_anthropic()
    ]

async def execute_skill(name: str, arguments: dict = None, memory: 'MemoryManager' = None) -> str:
    """
    The central python executable router.
    When an LLM (either Local or Claude) decides it wants to use a tool, it halts text generation
    and passes the requested tool's 'name' to this function. This function maps that name 
    to the correct python script in this folder, executes it, and returns the real-world data back to the LLM.
    
    If the tool result contains [ATTACH:path], the path is captured into pending_attachments
    so agent.py can attach the file to the Discord message, regardless of whether the LLM
    echoes the tag in its final response.
    """
    if name == "get_current_time":
        result = time_execute(arguments)
    elif name == "get_weather":
        result = weather_execute(arguments)
    elif name == "search_web":
        result = search_execute(arguments)
    elif name == "show_identity_portrait":
        result = identity_execute(arguments)
    elif name == "get_my_profile":
        # Pass shared memory to brain skill if available
        if memory:
            from .brain_skill import execute_with_memory
            result = execute_with_memory(memory)
        else:
            result = brain_execute(arguments)
    elif name == "read_url_content":
        result = await link_reader_execute(arguments)
    elif name == "get_current_news":
        result = news_execute(arguments)
    elif name == "set_reminder":
        result = reminder_execute(arguments, memory)
    else:
        return f"Skill execution failed: Unknown tool '{name}'."
    
    # Intercept [ATTACH:path] tags from ANY tool result
    match = re.search(r"\[ATTACH:(.*?)\]", result)
    if match:
        pending_attachments.append(match.group(1).strip())
        print(f"SKILL ROUTER: Captured attachment -> {match.group(1).strip()}")
    
    return result

