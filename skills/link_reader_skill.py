import aiohttp
import asyncio
from bs4 import BeautifulSoup

def get_openai_schema():
    return {
        "type": "function",
        "function": {
            "name": "read_url_content",
            "description": "Call this to 'open' a link and read its text content. Use this when the user provides a specific URL and asks for a summary, details, or a translation of that page.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The full web URL to read (e.g., https://en.wikipedia.org/wiki/Artificial_intelligence)."
                    }
                },
                "required": ["url"]
            }
        }
    }

def get_anthropic_schema():
    return {
        "name": "read_url_content",
        "description": "Call this to 'open' a link and read its text content. Use this when the user provides a specific URL and asks for a summary, details, or a translation of that page.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The full web URL to read (e.g., https://en.wikipedia.org/wiki/Artificial_intelligence)."
                }
            },
            "required": ["url"]
        }
    }

async def execute(arguments):
    """
    Fetches the HTML from the URL, cleans it using BeautifulSoup, 
    and returns a clean text snapshot.
    """
    print("DEBUG: Link Reader tool called with arguments:", arguments)
    url = arguments.get("url")
    if not url:
        return "Error: No URL provided."
        
    print(f"DEBUG: Link Reader tool fetching content from -> {url}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=10) as response:
                if response.status != 200:
                    return f"Error: Could not access the page (HTTP {response.status})."
                
                html = await response.text()
                
        # Use BeautifulSoup to clean up the HTML
        soup = BeautifulSoup(html, "html.parser")
        
        # Remove script and style elements
        for script_or_style in soup(["script", "style", "meta", "noscript", "header", "footer", "nav"]):
            script_or_style.decompose()
            
        # Get text and clean up whitespace
        text = soup.get_text()
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        clean_text = "\n".join(chunk for chunk in chunks if chunk)
        
        # Limit the output to avoid context window explosion (5,000 chars is usually enough for a summary)
        MAX_CHARS = 5000
        if len(clean_text) > MAX_CHARS:
            return clean_text[:MAX_CHARS] + "\n\n...(Content truncated for length)..."
            
        return clean_text if clean_text else "Error: The page appeared even though I parsed it, but no readable text was found."
        
    except asyncio.TimeoutError:
        return "Error: The connection timed out while trying to reach the website."
    except Exception as e:
        return f"Error: An unexpected error occurred while reading the link: {e}"
