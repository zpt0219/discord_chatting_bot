import json
import os
import time
from typing import Dict, Any, List
import settings

# Define the local file paths where data will be stored
BOT_FILE = "bot_identity.json"
OWNER_FILE = "owner_relationship.json"

class MemoryManager:
    """
    The 'Persistent Brain' of the Agent.
    
    Manages long-term state using localized JSON files. It implements a 
    Categorized Knowledge Store (Identity, Interests, Preferences, Routine)
    to ensure the bot maintains a sophisticated and structured understanding 
    of its owner across restarts.
    """
    
    def __init__(self):
        # Automatically ensure files exist on startup
        self._init_files()

    def _init_files(self):
        """
        Creates the JSON files with default, empty templates if they don't already exist.
        """
        # 1. Initialize Bot Identity File
        if not os.path.exists(BOT_FILE):
            with open(BOT_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "name": None,         # The bot's chosen name
                    "personality_traits": [], # E.g., ["Sarcastic", "Curious"]
                    "creation_timestamp": time.time()
                }, f, indent=4)
        
        # 2. Initialize Owner Relationship File
        if not os.path.exists(OWNER_FILE):
            with open(OWNER_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "owner_id": None,     # Discord User ID of the owner
                    "facts": {
                        "identity": [],      # Name, age, role, etc.
                        "interests": [],     # Hobbies, likes, dislikes
                        "preferences": [],   # How the owner likes the bot to behave
                        "routine": [],       # Daily schedule, work life
                        "other": []          # Catch-all
                    },
                    "relationship_stage": "stranger",  # stranger -> acquaintance -> friend
                    "preferred_language": None,  # e.g. "Chinese", "English", etc.
                    "last_interaction_timestamp": 0, # When they last talked
                    "proactive_messages_ignored": 0,  # Counter for backoff logic
                    "summarized_memories": [] # Long-term abstracted conversation snapshots
                }, f, indent=4)
                
    # ==========================================
    # BOT IDENTITY METHODS
    # ==========================================
    
    def get_bot_identity(self) -> Dict[str, Any]:
        """Reads the bot_identity.json file and returns a dictionary."""
        with open(BOT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
            
    def update_bot_identity(self, updates: Dict[str, Any]):
        """Updates specific fields in the bot's identity (like saving the name)."""
        data = self.get_bot_identity()
        data.update(updates)
        with open(BOT_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
            
    def add_personality_traits(self, traits):
        """
        Appends new personality traits using LRU cache logic (max 100).
        - Splits compound traits (e.g., "playful and humorous") into simple ones.
        - Normalizes each trait (strips whitespace, lowercase comparison, remove trailing periods).
        - Deduplicates using case-insensitive exact matching.
        """
        # Safety: if the LLM returned a single string instead of a list, wrap it
        if isinstance(traits, str):
            traits = [traits]
        
        data = self.get_bot_identity()
        changed = False
        
        # 1. Expand compound traits and normalize
        expanded_traits = []
        for raw_trait in traits:
            if not isinstance(raw_trait, str):
                continue
            
            # Split by common connectors: " and ", ",", "/", "&"
            # We use a simple regex-like approach by replacing connectors with a common delimiter
            normalized = raw_trait.replace(" and ", "|").replace(",", "|").replace("/", "|").replace("&", "|")
            parts = [p.strip() for p in normalized.split("|")]
            
            for p in parts:
                # Clean up: remove trailing punctuation, lowercase for comparison
                clean = p.strip().strip(".,!?;:\"'").lower()
                if len(clean) >= 3 and clean not in ["none", "identified", "yet"]:
                    # We store the original case but use lowercase for comparison
                    expanded_traits.append(p.strip().strip(".,!?;:\"'"))
        
        for trait in expanded_traits:
            # Check for existing match (case-insensitive)
            existing_index = None
            for i, existing in enumerate(data["personality_traits"]):
                if existing.lower() == trait.lower():
                    existing_index = i
                    break
            
            if existing_index is not None:
                # LRU: Move existing trait to the end (mark as recently used)
                data["personality_traits"].append(data["personality_traits"].pop(existing_index))
                changed = True
            else:
                # New trait: append to end
                data["personality_traits"].append(trait)
                changed = True
        
        # LRU eviction: if over 100 traits, trim from the front (least recently used)
        MAX_TRAITS = 100
        if len(data["personality_traits"]) > MAX_TRAITS:
            evicted = data["personality_traits"][:-MAX_TRAITS]
            data["personality_traits"] = data["personality_traits"][-MAX_TRAITS:]
            print(f"MEMORY: Evicted {len(evicted)} least-used personality traits (LRU cap: {MAX_TRAITS})")
        
        if changed:
            with open(BOT_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)

    # ==========================================
    # OWNER RELATIONSHIP METHODS
    # ==========================================

    def get_owner_relationship(self) -> Dict[str, Any]:
        """Reads the owner_relationship.json file and returns a dictionary."""
        with open(OWNER_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
            
    def update_owner_relationship(self, updates: Dict[str, Any]):
        """Updates specific fields in the owner's relationship file."""
        data = self.get_owner_relationship()
        data.update(updates)
        with open(OWNER_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
            
    def set_owner_id_if_null(self, owner_id: int):
        """Saves the user's Discord ID if we haven't locked onto an owner yet."""
        data = self.get_owner_relationship()
        if data["owner_id"] is None:
            data["owner_id"] = owner_id
            with open(OWNER_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)

    def record_owner_reply(self, owner_reply: str, bot_response: str, summarized_memory: str = None):
        """
        Commits a conversation turn to persistent storage.
        
        1. Updates the last interaction timestamp (Clock Reset).
        2. Appends new abstracted memories (if provided by the background model).
        3. Enforces a 10,000 character limit on memories to optimize context windows.
        """
        data = self.get_owner_relationship()
        if "facts" not in data:
            data["facts"] = {"identity": [], "interests": [], "preferences": [], "routine": [], "other": []}
            
        data["last_interaction_timestamp"] = time.time()
        data["proactive_messages_ignored"] = 0
        
        if summarized_memory:
            self.add_summarized_memory(summarized_memory)
        else:
            with open(OWNER_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)

    def add_categorized_facts(self, categorized_facts: List[Dict[str, str]]):
        """
        Adds or merges facts into specific categories (Identity, Interests, Preferences, Routine, Other).
        categorized_facts: list of {"category": str, "text": str}
        """
        data = self.get_owner_relationship()
        if "facts" not in data:
            data["facts"] = {"identity": [], "interests": [], "preferences": [], "routine": [], "other": []}
            
        added = False
        for entry in categorized_facts:
            cat = entry.get("category", "other").lower()
            text = entry.get("text")
            
            if not text or len(text) < 3:
                continue
                
            if cat not in data["facts"]:
                cat = "other"
                
            # Deduplication: is this exactly the same string?
            if text not in data["facts"][cat]:
                data["facts"][cat].append(text)
                added = True
                
        # Relationship logic (count total facts across all categories)
        total_facts = sum(len(facts) for facts in data["facts"].values())
        if total_facts >= 5 and data["relationship_stage"] == "stranger":
            data["relationship_stage"] = "acquaintance"
        elif total_facts >= 15 and data["relationship_stage"] == "acquaintance":
            data["relationship_stage"] = "friend"
            
        if added:
            with open(OWNER_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
            print(f"MEMORY: Added {len(categorized_facts)} categorized facts.")

    def add_facts_about_owner(self, facts):
        """[LEGACY] Redirects to add_categorized_facts as 'other' for compatibility."""
        if isinstance(facts, str):
            facts = [facts]
        self.add_categorized_facts([{"category": "other", "text": f} for f in facts])
                
    def add_summarized_memory(self, memory_text: str):
        """
        Appends a new abstracted summary of a conversation to our long-term memory.
        We cap this at 20 snippets to prevent the JSON file from becoming massive.
        """
        if not memory_text or not isinstance(memory_text, str) or len(memory_text) < 5:
            return
            
        data = self.get_owner_relationship()
        
        # We use a list to store these snapshots chronologically
        if "summarized_memories" not in data:
            data["summarized_memories"] = []
            
        # Avoid duplicate summaries if they are identical
        if memory_text not in data["summarized_memories"]:
            data["summarized_memories"].append(memory_text)
            
            # 1. LRU-like count eviction: Keep only the 20 most recent high-level memories
            MAX_MEMORIES = 20
            if len(data["summarized_memories"]) > MAX_MEMORIES:
                data["summarized_memories"] = data["summarized_memories"][-MAX_MEMORIES:]
            
            # 2. Total Character length eviction: Ensure the entire list is not too large for LLM context
            # We prune from the beginning (oldest) until the total character count is under the limit
            max_chars = settings.MAX_SUMMARIZED_MEMORIES_LEN
            while data["summarized_memories"] and sum(len(m) for m in data["summarized_memories"]) > max_chars:
                evicted = data["summarized_memories"].pop(0)
                print(f"MEMORY: Evicted oldest summary memory to stay under {max_chars} character limit.")
                
            with open(OWNER_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
            print(f"MEMORY: Archived a new abstracted conversation memory.")
                
    # ==========================================
    # LANGUAGE PREFERENCE
    # ==========================================
    
    def update_preferred_language(self, language: str):
        """Updates the owner's preferred language in the relationship file."""
        data = self.get_owner_relationship()
        data["preferred_language"] = language
        with open(OWNER_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        print(f"MEMORY: Updated preferred language to '{language}'")

    # ==========================================
    # PROACTIVE MESSAGING TRACKERS
    # ==========================================
                
    def record_owner_reply(self):
        """
        Called whenever the owner replies. 
        Updates the timestamp so the bot knows the owner is actively chatting.
        Resets the ignored counter back to 0, resetting the backoff delay.
        """
        data = self.get_owner_relationship()
        data["last_interaction_timestamp"] = time.time()
        data["proactive_messages_ignored"] = 0
        with open(OWNER_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
            
    def record_proactive_message_sent(self):
        """
        Called when the bot sends an unprompted message. We increment the 'ignored' 
        counter. If the user replies, 'record_owner_reply' resets it. If they don't, 
        the counter goes up, triggering exponential backoff in bot.py.
        """
        data = self.get_owner_relationship()
        data["last_interaction_timestamp"] = time.time()
        data["proactive_messages_ignored"] += 1
        with open(OWNER_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
