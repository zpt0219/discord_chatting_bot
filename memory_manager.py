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
        # Load raw data from disk into memory cache
        self._init_files()
        self._bot_data = self._load_file(BOT_FILE)
        self._owner_data = self._load_file(OWNER_FILE)

    def _load_file(self, filename: str) -> Dict[str, Any]:
        """Helper to safely load a JSON file from disk."""
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)

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
                    "summarized_memories": [], # Long-term abstracted conversation snapshots
                    "reminders": [] # Upcoming alerts: [{"time": timestamp, "message": str, "triggered": bool}]
                }, f, indent=4)

    def save(self):
        """
        Explicitly commits the in-memory cache to the JSON files on disk.
        This should be called at the end of a conversation turn to minimize I/O.
        """
        with open(BOT_FILE, "w", encoding="utf-8") as f:
            json.dump(self._bot_data, f, indent=4)
        with open(OWNER_FILE, "w", encoding="utf-8") as f:
            json.dump(self._owner_data, f, indent=4)
        print("MEMORY: Synchronized caches to disk.")
                
    # ==========================================
    # BOT IDENTITY METHODS
    # ==========================================
    
    def get_bot_identity(self) -> Dict[str, Any]:
        """Returns the current cached bot identity."""
        return self._bot_data
            
    def update_bot_identity(self, updates: Dict[str, Any]):
        """Updates specific fields in the cached bot identity."""
        self._bot_data.update(updates)
            
    def add_personality_traits(self, traits):
        """
        Appends new personality traits using LRU cache logic (max 100).
        """
        if isinstance(traits, str):
            traits = [traits]
        
        # 1. Expand compound traits and normalize
        expanded_traits = []
        for raw_trait in traits:
            if not isinstance(raw_trait, str): continue
            normalized = raw_trait.replace(" and ", "|").replace(",", "|").replace("/", "|").replace("&", "|")
            parts = [p.strip() for p in normalized.split("|")]
            for p in parts:
                clean = p.strip().strip(".,!?;:\"'").lower()
                if len(clean) >= 3 and clean not in ["none", "identified", "yet"]:
                    expanded_traits.append(p.strip().strip(".,!?;:\"'"))
        
        for trait in expanded_traits:
            existing_index = next((i for i, ext in enumerate(self._bot_data["personality_traits"]) if ext.lower() == trait.lower()), None)
            if existing_index is not None:
                self._bot_data["personality_traits"].append(self._bot_data["personality_traits"].pop(existing_index))
            else:
                self._bot_data["personality_traits"].append(trait)
        
        # Trim to LRU limit
        MAX_TRAITS = 100
        if len(self._bot_data["personality_traits"]) > MAX_TRAITS:
            self._bot_data["personality_traits"] = self._bot_data["personality_traits"][-MAX_TRAITS:]

    # ==========================================
    # OWNER RELATIONSHIP METHODS
    # ==========================================

    def get_owner_relationship(self) -> Dict[str, Any]:
        """Returns the current cached owner relationship data."""
        return self._owner_data
            
    def update_owner_relationship(self, updates: Dict[str, Any]):
        """Updates specific fields in the cached relationship file."""
        self._owner_data.update(updates)
            
    def set_owner_id_if_null(self, owner_id: int):
        """Saves the user's Discord ID if not set."""
        if self._owner_data["owner_id"] is None:
            self._owner_data["owner_id"] = owner_id

    def add_categorized_facts(self, categorized_facts: List[Dict[str, str]]):
        """
        Adds or merges facts into specific categories (Identity, Interests, Preferences, Routine, Other).
        """
        if "facts" not in self._owner_data:
            self._owner_data["facts"] = {"identity": [], "interests": [], "preferences": [], "routine": [], "other": []}
            
        for entry in categorized_facts:
            cat = entry.get("category", "other").lower()
            text = entry.get("text")
            if not text or len(text) < 3: continue
            if cat not in self._owner_data["facts"]: cat = "other"
            if text not in self._owner_data["facts"][cat]:
                self._owner_data["facts"][cat].append(text)
                
        # Update relationship stage based on total facts
        total_facts = sum(len(facts) for facts in self._owner_data["facts"].values())
        if total_facts >= 5 and self._owner_data["relationship_stage"] == "stranger":
            self._owner_data["relationship_stage"] = "acquaintance"
        elif total_facts >= 15 and self._owner_data["relationship_stage"] == "acquaintance":
            self._owner_data["relationship_stage"] = "friend"

    def add_summarized_memory(self, memory_text: str):
        """
        Appends a new summary snapshot to the cached memory.
        """
        if not memory_text or not isinstance(memory_text, str) or len(memory_text) < 5: return
        if "summarized_memories" not in self._owner_data:
            self._owner_data["summarized_memories"] = []
            
        if memory_text not in self._owner_data["summarized_memories"]:
            self._owner_data["summarized_memories"].append(memory_text)
            # Evict old summaries (count limit)
            if len(self._owner_data["summarized_memories"]) > 20: 
                self._owner_data["summarized_memories"] = self._owner_data["summarized_memories"][-20:]
            # Evict old summaries (char total limit)
            max_chars = settings.MAX_SUMMARIZED_MEMORIES_LEN
            while self._owner_data["summarized_memories"] and sum(len(m) for m in self._owner_data["summarized_memories"]) > max_chars:
                self._owner_data["summarized_memories"].pop(0)

    def update_preferred_language(self, language: str):
        """Updates cached preferred language."""
        self._owner_data["preferred_language"] = language

    def record_owner_reply(self):
        """Resets interaction tracking in memory cache."""
        self._owner_data["last_interaction_timestamp"] = time.time()
        self._owner_data["proactive_messages_ignored"] = 0
            
    def record_proactive_message_sent(self):
        """Increments ignored counter in memory cache."""
        self._owner_data["last_interaction_timestamp"] = time.time()
        self._owner_data["proactive_messages_ignored"] += 1
        
    # ==========================================
    # REMINDER METHODS
    # ==========================================

    def add_reminder(self, minutes: int, message: str):
        """Calculates target time and adds a reminder to the owner's cached data."""
        if "reminders" not in self._owner_data:
            self._owner_data["reminders"] = []
            
        target_time = time.time() + (minutes * 60)
        self._owner_data["reminders"].append({
            "time": target_time,
            "message": message,
            "triggered": False
        })
        return target_time

    def get_due_reminders(self) -> List[Dict[str, Any]]:
        """Returns all reminders that are due and haven't been triggered yet."""
        if "reminders" not in self._owner_data:
            return []
            
        now = time.time()
        due = []
        for r in self._owner_data["reminders"]:
            if not r["triggered"] and r["time"] <= now:
                due.append(r)
        return due

    def clean_old_reminders(self):
        """Removes triggered reminders more than 24 hours old to keep the file lean."""
        if "reminders" not in self._owner_data: return
        now = time.time()
        # Keep if not triggered OR if triggered less than 24h ago
        self._owner_data["reminders"] = [
            r for r in self._owner_data["reminders"]
            if not r["triggered"] or (now - r["time"] < 86400)
        ]
