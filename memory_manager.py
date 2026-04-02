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
                    "relationship_stage": 0,  # 0: just met, 1: acquaintance, 2: friend
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
            
    def add_personality_traits(self, traits: List[str]):
        """Appends new personality traits to the list, verifying they aren't duplicates."""
        data = self.get_bot_identity()
        added = False
        for trait in traits:
            if trait not in data["personality_traits"]:
                data["personality_traits"].append(trait)
                added = True
        # Only rewrite the file if we actually added something new
        if added:
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

    def add_facts_about_owner(self, facts: List[str]):
        """Appends newly learned facts about the owner, dodging duplicates."""
        data = self.get_owner_relationship()
        added = False
        for fact in facts:
            if fact not in data["facts_about_owner"]:
                data["facts_about_owner"].append(fact)
                added = True
                
        # Proactive Relationship Logic:
        # As the bot learns more facts, it naturally evolves its relationship stage.
        # This makes the bot reach out less frequently (or differently) over time
        # instead of relying on a rigid timeline.
        if len(data["facts_about_owner"]) >= 5 and data["relationship_stage"] == 0:
            data["relationship_stage"] = 1 # Became acquaintances!
        elif len(data["facts_about_owner"]) >= 15 and data["relationship_stage"] == 1:
            data["relationship_stage"] = 2 # Became friends!
            
        if added:
            with open(OWNER_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
                
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
