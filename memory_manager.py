import json
import os
import time
from typing import Dict, Any, List

BOT_FILE = "bot_identity.json"
OWNER_FILE = "owner_relationship.json"

class MemoryManager:
    """Handles persistent state for the Discord bot using local JSON files."""
    
    def __init__(self):
        self._init_files()

    def _init_files(self):
        if not os.path.exists(BOT_FILE):
            with open(BOT_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "name": None,
                    "personality_traits": [],
                    "creation_timestamp": time.time()
                }, f, indent=4)
        
        if not os.path.exists(OWNER_FILE):
            with open(OWNER_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "owner_id": None,
                    "facts_about_owner": [],
                    "relationship_stage": 0,  # 0: just met, 1: acquaintance, 2: friend
                    "last_interaction_timestamp": 0,
                    "proactive_messages_ignored": 0
                }, f, indent=4)
                
    def get_bot_identity(self) -> Dict[str, Any]:
        with open(BOT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
            
    def update_bot_identity(self, updates: Dict[str, Any]):
        data = self.get_bot_identity()
        data.update(updates)
        with open(BOT_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
            
    def add_personality_traits(self, traits: List[str]):
        data = self.get_bot_identity()
        added = False
        for trait in traits:
            if trait not in data["personality_traits"]:
                data["personality_traits"].append(trait)
                added = True
        if added:
            with open(BOT_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)

    def get_owner_relationship(self) -> Dict[str, Any]:
        with open(OWNER_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
            
    def update_owner_relationship(self, updates: Dict[str, Any]):
        data = self.get_owner_relationship()
        data.update(updates)
        with open(OWNER_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
            
    def set_owner_id_if_null(self, owner_id: int):
        data = self.get_owner_relationship()
        if data["owner_id"] is None:
            data["owner_id"] = owner_id
            with open(OWNER_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)

    def add_facts_about_owner(self, facts: List[str]):
        data = self.get_owner_relationship()
        added = False
        for fact in facts:
            if fact not in data["facts_about_owner"]:
                data["facts_about_owner"].append(fact)
                added = True
                
        # Naturally evolve the relationship stage based on the number of facts known
        if len(data["facts_about_owner"]) >= 5 and data["relationship_stage"] == 0:
            data["relationship_stage"] = 1
        elif len(data["facts_about_owner"]) >= 15 and data["relationship_stage"] == 1:
            data["relationship_stage"] = 2
            
        if added:
            with open(OWNER_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
                
    def record_owner_reply(self):
        """Called when the owner sends a message."""
        data = self.get_owner_relationship()
        data["last_interaction_timestamp"] = time.time()
        data["proactive_messages_ignored"] = 0
        with open(OWNER_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
            
    def record_proactive_message_sent(self):
        """Called when the bot reaches out proactively."""
        data = self.get_owner_relationship()
        data["last_interaction_timestamp"] = time.time()
        data["proactive_messages_ignored"] += 1
        with open(OWNER_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
