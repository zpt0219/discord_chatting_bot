import os
import json
from typing import Dict, Any
from memory_manager import MemoryManager

def get_openai_schema():
    return {
        "type": "function",
        "function": {
            "name": "get_my_profile",
            "description": "Call this whenever the user asks 'what do you know about me?', 'show me my profile', 'what's in your memory?', or similar questions. It will trigger a summary of their categorized facts and relationship status.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    }

def get_anthropic_schema():
    return {
        "name": "get_my_profile",
        "description": "Call this whenever the user asks 'what do you know about me?', 'show me my profile', 'what's in your memory?', or similar questions. It will trigger a summary of their categorized facts and relationship status.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }

def execute_with_memory(memory: MemoryManager):
    """
    Returns a formatted summary of the owner's categorized facts and relationship status
    using the provided live MemoryManager instance.
    """
    owner_info = memory.get_owner_relationship()
    bot_info = memory.get_bot_identity()
    
    facts_dict = owner_info.get("facts", {})
    relationship_stage = owner_info.get("relationship_stage", "stranger")
    bot_name = bot_info.get("name") or "Your Bot"
    
    output = [
        f"### 🧠 {bot_name}'s Memory of You",
        f"**Relationship Stage**: {relationship_stage.capitalize()}",
        ""
    ]
    
    category_labels = {
        "identity": "👤 **Identity**",
        "interests": "🌟 **Interests & Hobbies**",
        "preferences": "⚙️ **Your Preferences**",
        "routine": "📅 **Daily Routine**",
        "other": "📝 **Other Notes**",
        "key_memories": "🧠 **Key Memories**"
    }
    
    found_any = False
    for cat, label in category_labels.items():
        cat_facts = facts_dict.get(cat, [])
        if cat_facts:
            found_any = True
            output.append(label)
            output.extend([f"• {f}" for f in cat_facts])
            output.append("")
            
    if not found_any:
        output.append("_I'm still getting to know you! I don't have many specific facts saved yet._")
        
    return "\n".join(output)

def execute(arguments=None):
    """
    Fallback execute that creates its own MemoryManager. 
    NOTE: This might read stale data from disk if a turn is mid-process.
    """
    print("WARNING: Brain tool called without live memory context. Reading from disk.")
    memory = MemoryManager()
    return execute_with_memory(memory)
