import json
import os
import time
from typing import Dict, Any, List

# Define the local file paths where data will be stored
BOT_FILE = "bot_identity.json"
OWNER_FILE = "owner_relationship.json"

class MemoryManager:
    """
    Handles persistent state for the Discord bot using local JSON files.
    This acts as the 'database', preventing the bot from losing its memory when restarted.
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
                    "facts_about_owner": [], # Array of strings summarizing the owner
                    "relationship_stage": "stranger",  # stranger -> acquaintance -> friend
                    "preferred_language": None,  # e.g. "Chinese", "English", etc.
                    "last_interaction_timestamp": 0, # When they last talked
                    "proactive_messages_ignored": 0  # Counter for backoff logic
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
        - If a trait already exists: move it to the END (most recently used).
        - If it's new: append to the END.
        - If the list exceeds 100: evict from the FRONT (least recently used).
        """
        # Safety: if the LLM returned a single string instead of a list, wrap it
        if isinstance(traits, str):
            traits = [traits]
        
        data = self.get_bot_identity()
        changed = False
        for trait in traits:
            # Skip single characters or very short junk
            if not isinstance(trait, str) or len(trait) < 3:
                continue
            
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

    def add_facts_about_owner(self, facts):
        """Appends newly learned facts about the owner, dodging duplicates."""
        # Safety: if the LLM returned a single string instead of a list, wrap it
        if isinstance(facts, str):
            facts = [facts]
        
        data = self.get_owner_relationship()
        added = False
        for fact in facts:
            # Skip single characters or very short junk
            if not isinstance(fact, str) or len(fact) < 3:
                continue
            if fact not in data["facts_about_owner"]:
                data["facts_about_owner"].append(fact)
                added = True
                
        # Proactive Relationship Logic:
        # As the bot learns more facts, it naturally evolves its relationship stage.
        # This makes the bot reach out less frequently (or differently) over time
        # instead of relying on a rigid timeline.
        if len(data["facts_about_owner"]) >= 5 and data["relationship_stage"] == "stranger":
            data["relationship_stage"] = "acquaintance" # Became acquaintances!
        elif len(data["facts_about_owner"]) >= 15 and data["relationship_stage"] == "acquaintance":
            data["relationship_stage"] = "friend" # Became friends!
            
        if added:
            with open(OWNER_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
                
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
