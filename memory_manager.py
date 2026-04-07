import json
import os
import time
import asyncio
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
        # Initialize the bot identity files if they are missing or return defaults on corruption
        self._bot_data = self._load_file(BOT_FILE)
        self._owner_data = self._load_file(OWNER_FILE)
        
        # We re-run init logic to fill in missing keys if the file was just reset by _load_file
        self._init_files()

    def _load_file(self, filename: str) -> Dict[str, Any]:
        """Helper to safely load a JSON file from disk with corruption recovery."""
        try:
            if not os.path.exists(filename):
                return {}
            with open(filename, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, PermissionError) as e:
            # If the file exists but we can't load it (corrupted or empty), back it up and reset
            backup_name = f"{filename}.corrupted_{int(time.time())}"
            try:
                os.rename(filename, backup_name)
                print(f"CRITICAL: {filename} was corrupted! Backed up to {backup_name}.")
            except Exception as rename_err:
                print(f"CRITICAL: {filename} is unreadable and cannot be renamed: {rename_err}")
            
            # Return an empty dictionary to trigger re-initialization in callers
            return {}

    def _init_files(self):
        """
        Creates the JSON files with default, empty templates if they don't already exist
        or if the in-memory cache is empty.
        """
        # 1. Initialize Bot Identity
        bot_defaults = {
            "name": None,
            "personality_traits": [],
            "creation_timestamp": time.time()
        }
        if not self._bot_data:
            self._bot_data = bot_defaults
            if not os.path.exists(BOT_FILE):
                with open(BOT_FILE, "w", encoding="utf-8") as f:
                    json.dump(bot_defaults, f, indent=4)
        
        # 2. Initialize Owner Relationship
        owner_defaults = {
            "owner_id": None,
            "facts": {
                "identity": [],
                "interests": [],
                "preferences": [],
                "routine": [],
                "key_memories": [],
                "other": []
            },
            "relationship_stage": "stranger",
            "preferred_language": None,
            "last_interaction_timestamp": 0,
            "proactive_messages_ignored": 0,
            "reminders": []
        }
        if not self._owner_data:
            self._owner_data = owner_defaults
            if not os.path.exists(OWNER_FILE):
                with open(OWNER_FILE, "w", encoding="utf-8") as f:
                    json.dump(owner_defaults, f, indent=4)

    async def save(self):
        """
        Explicitly commits the in-memory cache to the JSON files on disk.
        This uses asyncio.to_thread to prevent blocking the event loop 
        and ensure the write-to-disk is atomic.
        """
        # We save both files in parallel in the background thread pool
        await asyncio.gather(
            asyncio.to_thread(self._save_atomic, BOT_FILE, self._bot_data),
            asyncio.to_thread(self._save_atomic, OWNER_FILE, self._owner_data)
        )
        print("MEMORY: Synchronized caches to disk atomically.")

    def _save_atomic(self, filename: str, data: Dict[str, Any]):
        """
        Internal helper that writes to a temporary file and then performs 
        an atomic OS-level replace. This protects against corrupted JSON 
        files if the process crashes mid-write.
        """
        temp_filename = f"{filename}.tmp"
        try:
            with open(temp_filename, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
            
            # os.replace is atomic on POSIX and Windows (Python 3.3+)
            os.replace(temp_filename, filename)
        except Exception as e:
            print(f"CRITICAL ERROR: Failed to save {filename} atomically: {e}")
            # If we failed, try to cleanup the temp file so it doesn't clutter
            if os.path.exists(temp_filename):
                try: os.remove(temp_filename)
                except Exception as cleanup_err:
                    print(f"WARNING: Could not remove temp file {temp_filename}: {cleanup_err}")
            raise e
                
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
            
    def set_owner_id(self, owner_id: int):
        """Saves the user's Discord ID."""
        self._owner_data["owner_id"] = owner_id

    def add_categorized_facts(self, categorized_facts: List[Dict[str, str]]):
        """
        Adds or merges facts into specific categories (Identity, Interests, Preferences, Routine, Other).
        """
        if "facts" not in self._owner_data:
            self._owner_data["facts"] = {"identity": [], "interests": [], "preferences": [], "routine": [], "key_memories": [], "other": []}
            
        for entry in categorized_facts:
            cat = entry.get("category", "other").lower()
            text = entry.get("text")
            if not text or len(text) < 3: continue
            if cat not in self._owner_data["facts"]: cat = "other"
            if text not in self._owner_data["facts"][cat]:
                self._owner_data["facts"][cat].append(text)
                
        # NEW: Prune to prevent "Disk-Leak" (physical growth of JSON files)
        for cat in self._owner_data["facts"]:
            if len(self._owner_data["facts"][cat]) > settings.MAX_STORAGE_FACTS_PER_CATEGORY:
                # Keep only the N most recent facts
                self._owner_data["facts"][cat] = self._owner_data["facts"][cat][-settings.MAX_STORAGE_FACTS_PER_CATEGORY:]

        # Update relationship stage based on total facts
        total_facts = sum(len(facts) for facts in self._owner_data["facts"].values())
        if total_facts >= 5 and self._owner_data["relationship_stage"] == "stranger":
            self._owner_data["relationship_stage"] = "acquaintance"
        elif total_facts >= 15 and self._owner_data["relationship_stage"] == "acquaintance":
            self._owner_data["relationship_stage"] = "friend"

    def add_key_memory(self, memory_text: str):
        """
        Appends a new Key Memory snapshot into the categorized facts section.
        """
        if not memory_text or not isinstance(memory_text, str) or len(memory_text) < 5: return
        
        if "facts" not in self._owner_data:
            self._owner_data["facts"] = {}
        if "key_memories" not in self._owner_data["facts"]:
            self._owner_data["facts"]["key_memories"] = []
            
        if memory_text not in self._owner_data["facts"]["key_memories"]:
            self._owner_data["facts"]["key_memories"].append(memory_text)
            
            # Evict old memories if they grow too large to preserve prompt space
            # Prune by count
            max_count = 30
            if len(self._owner_data["facts"]["key_memories"]) > max_count: 
                self._owner_data["facts"]["key_memories"] = self._owner_data["facts"]["key_memories"][-max_count:]
                
            # Prune by character limit
            max_chars = settings.MAX_KEY_MEMORIES_LEN
            while self._owner_data["facts"]["key_memories"] and sum(len(m) for m in self._owner_data["facts"]["key_memories"]) > max_chars:
                self._owner_data["facts"]["key_memories"].pop(0)

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
