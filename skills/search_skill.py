from duckduckgo_search import DDGS

# =======================================================
# SEARCH SKILL (TOOL CALLING)
# =======================================================
# Grants the LLM access to real-time internet searches.

def get_openai_schema():
    """Defines the tool for the Local OpenAI SDK (Llama.cpp)."""
    return {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Searches the internet for current events, facts, or information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query to look up on the internet."
                    }
                },
                "required": ["query"]
            }
        }
    }

def get_anthropic_schema():
    """Defines the tool for the Claude Router Fallback layout."""
    return {
        "name": "search_web",
        "description": "Searches the internet for current events, facts, or information.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to look up on the internet."
                }
            },
            "required": ["query"]
        }
    }

def execute(arguments: dict = None) -> str:
    """
    Executes the web search using DuckDuckGo and returns concise text snippets.
    """
    print(f"DEBUG: Search tool called with arguments: {arguments}")
    if not arguments or "query" not in arguments:
        return "Search failed: No query string provided."
        
    query = arguments["query"]
    
    try:
        results = DDGS().text(query, max_results=3)
        if not results:
            return f"No search results found online for '{query}'."
            
        formatted_results = []
        for index, r in enumerate(results):
            title = r.get("title", "No Title")
            body = r.get("body", "No Snippet")
            link = r.get("href", "")
            formatted_results.append(f"Result {index+1}: {title} - {body} ({link})")
            
        final_text = "\n".join(formatted_results)
        return f"Internet search results for '{query}':\n{final_text}"
        
    except Exception as e:
        return f"Could not perform internet search for '{query}'. Tool failed with error: {str(e)}"
