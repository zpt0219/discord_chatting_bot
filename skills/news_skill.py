from duckduckgo_search import DDGS

# =======================================================
# NEWS SKILL (TOOL CALLING)
# =======================================================

def get_openai_schema():
    return {
        "type": "function",
        "function": {
            "name": "get_current_news",
            "description": "Searches the internet for the latest news headlines and stories on a given topic.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search term (e.g., 'AI news', 'World news')."
                    }
                },
                "required": ["query"]
            }
        }
    }

def get_anthropic_schema():
    return {
        "name": "get_current_news",
        "description": "Searches the internet for the latest news headlines and stories on a given topic.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search term (e.g., 'AI news', 'World news')."
                }
            },
            "required": ["query"]
        }
    }

def execute(arguments: dict = None) -> str:
    """
    Executes the news search using DuckDuckGo and returns concise headlines.
    Falls back to text search if no news headlines are found or if the news engine fails.
    """
    print(f"DEBUG: News tool called with arguments: {arguments}")
    if not arguments or "query" not in arguments:
        return "News search failed: No query string provided."
        
    query = arguments["query"]
    results = []
    
    # 1. Try dedicated news search. Note: older versions used 'engine', 
    # but newer duckduckgo_search versions (v6+) usually do not.
    try:
        print(f"DEBUG: Attempting news search for '{query}'...")
        results = DDGS().news(query, max_results=5)
    except Exception as e:
        print(f"DEBUG: News search hit a network/API issue: {e}. Falling back to general search...")
        results = [] # Reset to trigger next fallback
        
    # 2. If no news results (or if it failed), try a general text search as the most robust fallback
    if not results:
        try:
            print(f"DEBUG: Using general text search fallback for news query '{query}'...")
            results = DDGS().text(f"latest headlines {query}", max_results=5)
        except Exception as e:
            print(f"DEBUG: General search fallback also failed: {e}")
            return f"I'm sorry, I ran into a network issue while searching for news on '{query}'. It might be a temporary hiccup."
            
    if not results:
        return f"I couldn't find any recent news stories or mentions for '{query}'. Maybe try different keywords?"
            
    formatted_results = []
    for index, r in enumerate(results):
        # Handle both news-style and search-style result keys
        title = r.get("title", "No Title")
        source = r.get("source") or r.get("body", "No Source/Snippet")[:150] + "..."
        date = r.get("date", "Recently")
        url = r.get("url", "") or r.get("href", "")
        
        formatted_results.append(f"Story {index+1}: {title}\n  Context: {source}\n  Date: {date}\n  Link: {url}")
        
    final_text = "\n\n".join(formatted_results)
    return f"Latest results for '{query}':\n\n{final_text}"
