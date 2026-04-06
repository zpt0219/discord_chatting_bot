import os
import discord
from discord.ext import tasks
from dotenv import load_dotenv

# Load environment variables before ANY other local imports
# This ensures LOCAL_LLAMA_BASE_URL in models/local_model_logic.py is correctly populated.
load_dotenv()

import asyncio
import time
import collections
import base64
import psutil

# Import our custom modules for handling memory and AI interactions
from memory_manager import MemoryManager
from agent import generate_response, extract_and_update_memory

import settings
from prompts import PROACTIVE_PROMPT

# =======================================================
# SINGLETON INSTANCE LOCK (Anti-Multi-Reply)
# =======================================================
# This ensures that only one instance of the bot is running globally.
# It protects against race conditions where multiple processes might try
# to write to the same persistent JSON memory simultaneously.
LOCK_FILE = ".bot.lock"

def is_pid_running(pid):
    """Checks if the given PID is currently active on the system using psutil."""
    if pid < 0: return False
    try:
        return psutil.pid_exists(pid)
    except Exception as e:
        print(f"DEBUG: Could not check PID {pid}: {e}")
        return False

def acquire_lock():
    """Tries to create a lock file to ensure singleton status, with stale detection."""
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, 'r') as f:
                old_pid = int(f.read().strip())
            
            if is_pid_running(old_pid):
                return False
            else:
                print(f"NOTICE: Found stale lock file for dead process {old_pid}. Cleaning up.")
                os.remove(LOCK_FILE)
        except (ValueError, Exception) as e:
            print(f"NOTICE: Uncovering corrupted/invalid lock file ({e}). Cleaning up.")
            try: os.remove(LOCK_FILE)
            except Exception as remove_err:
                print(f"WARNING: Could not remove corrupted lock file: {remove_err}")

    try:
        # os.O_EXCL ensures the file is created ONLY if it doesn't exist (atomic)
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, 'w') as f:
            f.write(str(os.getpid()))
        return True
    except FileExistsError:
        return False
    except Exception as e:
        print(f"CRITICAL: Failed to write lock file: {e}")
        return False

def release_lock():
    """Removes the lock file on exit."""
    if os.path.exists(LOCK_FILE):
        os.remove(LOCK_FILE)

class AgentBot(discord.Client):
    """
    The main Discord bot class that inherits from discord.Client.
    It manages connections to Discord, handles incoming messages, and runs background loops.
    """
    
    def __init__(self):
        # Intents dictate what events the bot is allowed to receive from Discord.
        # We explicitly enable 'message_content' so the bot can read the text of messages.
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        
        # Initialize our local JSON memory manager
        self.memory = MemoryManager()
        
        # Short-term chat history (sliding window) to maintain immediate context.
        # This is hydrated from Discord history if the bot restarts, ensuring context continuity.
        self.chat_history = []
        
        # PROCESSING LOCK: Critical to ensure one message is fully handled (Read -> Think -> Write)
        # before the next one starts. This maintains strictly sequential memory integrity.
        self._processing_lock = asyncio.Lock()
        
        # NEW: Per-user/channel message queuing to combine multiple rapid messages.
        self._message_queues = collections.defaultdict(list)
        self._active_contexts = set()
        
    async def setup_hook(self):
        """
        A special Pycord/Discord.py lifecycle method called before the bot connects.
        This is the ideal place to start background tasks.
        """
        # Start the background news/reminder and proactive loops
        self.proactive_loop.start()
        self.reminder_loop.start()

    async def on_ready(self):
        """
        Called automatically when the bot successfully logs into Discord.
        """
        print(f"Logged in as {self.user} (ID: {self.user.id})")
        print("Bot is ready and waiting for the owner. Send a DM or mention it in a server!")

    async def on_message(self, message: discord.Message):
        """
        The orchestrator for the 'Sense-Think-Act-Reflect' loop.
        It handles incoming triggers, prepares multi-modal context, 
        generates responses via a tiered AI router, and commits memories sequentially.
        """
        # Security/Sanity Check: Ignore messages sent by the bot itself to prevent infinite loops.
        if message.author.id == self.user.id:
            return
            
        # We enforce the "owner-only" rule.
        owner = settings.OWNER_USERNAME
        if owner and (message.author.name != owner and message.author.global_name != owner):
            print(f"Ignored message from {message.author.name} (not '{owner}')")
            # If the user is not the owner, we simply drop the message and do nothing.
            return
            
        # We save the discord user ID of whoever messages it. 
        # This allows the bot to know WHO to DM when it proactively reaches out later.
        self.memory.set_owner_id_if_null(message.author.id)
        
        # We only want the bot to reply to Direct Messages (DMs) or if explicitly @mentioned in a server.
        is_dm = isinstance(message.channel, discord.DMChannel)
        is_mentioned = self.user.mentioned_in(message)
        
        if not is_dm and not is_mentioned:
            # If it's a random server message that doesn't mention the bot, ignore it.
            return
            
        # Clean the message text to remove the @mention text from the message.
        # Discord's clean_content replaces <@ID> with @DisplayName, so we strip all possible name variants.
        clean_msg = message.clean_content
        clean_msg = clean_msg.replace(f"@{self.user.name}", "")           # @username
        clean_msg = clean_msg.replace(f"@{self.user.display_name}", "")   # @display_name
        clean_msg = clean_msg.strip()

        # NEW: Use per-user context tracking to queue and combine rapid messages.
        # This ensures that if the owner sends 3 messages while the bot is 'thinking',
        # the bot will process them as a single combined query once it's free.
        context_id = message.author.id
        if context_id in self._active_contexts:
            self._message_queues[context_id].append(message)
            print(f"QUEUING: User {message.author.name} is already being processed. Adding message to queue.")
            return

        self._active_contexts.add(context_id)
        
        try:
            # We loop to drain the queue if more messages arrived during the previous LLM processing step.
            msg_to_process = message
            while True:
                # 1. Gather all messages to process in this turn
                pending = self._message_queues[context_id]
                self._message_queues[context_id] = []
                
                current_batch = [msg_to_process] + pending if msg_to_process else pending
                # After the first iteration, 'msg_to_process' (the initial trigger) is handled, 
                # and we only focus on 'pending'.
                msg_to_process = None 

                if not current_batch:
                    break

                # We reply to the LATEST message in the batch to keep the thread natural.
                target_message = current_batch[-1]
                
                # Aggregate text and attachments from all messages in the batch
                combined_clean_msgs = []
                image_data_list = []
                
                for msg in current_batch:
                    c_text = msg.clean_content.replace(f"@{self.user.name}", "").replace(f"@{self.user.display_name}", "").strip()
                    if c_text:
                        combined_clean_msgs.append(c_text)
                    
                    # Detect and download image attachments from each message
                    for attachment in msg.attachments:
                        if attachment.content_type and attachment.content_type.startswith("image/"):
                            try:
                                img_bytes = await attachment.read()
                                b64_str = base64.b64encode(img_bytes).decode("utf-8")
                                
                                # Detect REAL media type from magic bytes
                                real_media_type = attachment.content_type
                                if img_bytes[:8] == b'\x89PNG\r\n\x1a\n': real_media_type = "image/png"
                                elif img_bytes[:2] == b'\xff\xd8': real_media_type = "image/jpeg"
                                elif img_bytes[:4] == b'GIF8': real_media_type = "image/gif"
                                elif img_bytes[:4] == b'RIFF' and img_bytes[8:12] == b'WEBP': real_media_type = "image/webp"
                                
                                image_data_list.append({"base64": b64_str, "media_type": real_media_type})
                            except Exception as e: print(f"Warning: Image download failed: {e}")

                # Combine clean text using the separator from settings
                final_clean_msg = settings.QUEUE_COMBINE_SEPARATOR.join(combined_clean_msgs)

                # Acquire the global processing lock (Sequential memory integrity)
                async with self._processing_lock:
                    # 2. Sync history if needed
                    if len(self.chat_history) == 0:
                        print("Memory out of sync! Fetching recent history...")
                        temp_hist = []
                        async for old_msg in target_message.channel.history(limit=settings.CHAT_HISTORY_FETCH_LIMIT, before=target_message):
                            role = "assistant" if old_msg.author.id == self.user.id else "user"
                            old_clean = old_msg.clean_content.replace(f"@{self.user.name}", "").strip()
                            if old_clean: temp_hist.append({"role": role, "content": old_clean})
                        temp_hist.reverse()
                        self.chat_history = temp_hist

                    # 3. Append combined query to history
                    if final_clean_msg:
                        label = final_clean_msg
                    else:
                        label = f"[sent {len(image_data_list)} image(s)]"
                    self.chat_history.append({"role": "user", "content": label})
                    
                    # 4. Prune history
                    if len(self.chat_history) > settings.CHAT_HISTORY_PRUNE_LIMIT:
                        self.chat_history = self.chat_history[-settings.CHAT_HISTORY_PRUNE_LIMIT:]
                            
                    # 5. Call LLM (with Final Safety Net)
                    try:
                        async with target_message.channel.typing():
                            # Thread-safe attachment capturing per-request
                            current_attachments = []
                            res = await generate_response(
                                self.memory, self.chat_history,
                                image_data=image_data_list if image_data_list else None,
                                attachments_list=current_attachments
                            )
                            reply_text = res["text"]
                            attachment_path = res["attachment"]
                            
                            # 6. Send reply (to target_message)
                            safe_reply = reply_text[:settings.MAX_DISCORD_MSG_LEN]
                            if attachment_path and os.path.exists(attachment_path):
                                file = discord.File(attachment_path)
                                await target_message.channel.send(safe_reply, file=file)
                            else:
                                await target_message.channel.send(safe_reply)
                    except Exception as e:
                        # Final catch-all for any unhandled generation/network errors
                        print(f"CRITICAL: Uncaught generation or network error: {e}")
                        reply_text = settings.ERROR_MSG_GENERIC
                        await target_message.channel.send(reply_text)
                    
                    # 7. Update context & memory (only if generate_response didn't completely crash)
                    # If it did crash, we still want to keep history but maybe warn the AI later.
                    self.chat_history.append({"role": "assistant", "content": reply_text})
                    await extract_and_update_memory(self.memory, final_clean_msg, reply_text)
                    
                    # NEW: Save the in-memory cache to disk after a full turn while still holding the lock.
                    await self.memory.save()

        finally:
            self._active_contexts.remove(context_id)


    @tasks.loop(seconds=settings.PROACTIVE_LOOP_INTERVAL)
    async def proactive_loop(self):
        """
        A background loop that runs every 60 seconds.
        It evaluates if the bot should proactively message the owner based on relationship stage and idle time.
        """
        # 1. Check for Active Conversation:
        # If the bot is currently processing a message from the owner, skip proactive check.
        if self._processing_lock.locked():
            return

        # 2. Extract context from MemoryManager
        owner_info = self.memory.get_owner_relationship()
        
        # If the bot has never been messaged, it doesn't know who the owner is yet (No ID). Can't reach out.
        if owner_info["owner_id"] is None:
            return
            
        last_interaction = owner_info["last_interaction_timestamp"]
        ignored_count = owner_info["proactive_messages_ignored"]
        stage = owner_info["relationship_stage"]
        
        # No history of interactions at all
        if last_interaction == 0:
            return
            
        now = time.time()
        time_since_last = now - last_interaction # Time passed in seconds
        
        # Determine the baseline "target idle time" before reaching out.
        # For testing purposes, these are short (2, 5, 15 minutes).
        # In a real bot, these would be hours (e.g., 3600 seconds, 14400 seconds).
        if stage == "stranger":
            target_delay = settings.PROACTIVE_DELAY_STRANGER
        elif stage == "acquaintance":
            target_delay = settings.PROACTIVE_DELAY_ACQUAINTANCE
        else:
            target_delay = settings.PROACTIVE_DELAY_FRIEND
            
        # Exponential Backoff logic:
        # If the bot reaches out and the owner ignores it, `ignored_count` goes up.
        # We multiply the target_delay by 2^ignored_count.
        # Example: if 2 mins target, and they ignore it once, it becomes 4 mins. Ignore again, 8 mins.
        # This prevents the bot from becoming a needy spammer.
        multiplier = (2 ** min(10, ignored_count)) if ignored_count > 0 else 1
        target_delay *= multiplier
        
        # If enough time has passed...
        if time_since_last > target_delay:
            # Try to fetch the Discord User object using the saved ID.
            # We use fetch_user (API call) instead of get_user (cache-only)
            # so the bot can reach the owner even after a cold restart.
            try:
                user = await self.fetch_user(owner_info["owner_id"])
            except Exception:
                user = None
            if user:
                # We prompt the LLM to generate a natural opening message
                prompt_text = PROACTIVE_PROMPT
                
                # Append this temporary prompt to our history and send it to the LLM.
                temp_hist = self.chat_history + [{"role": "user", "content": prompt_text}]
                
                try:
                    res = await generate_response(self.memory, temp_hist)
                    reply_text = res["text"]
                    attachment_path = res["attachment"]
                    
                    # Send the AI's proactive text as a Direct Message
                    if attachment_path and os.path.exists(attachment_path):
                        file = discord.File(attachment_path)
                        await user.send(reply_text, file=file)
                    else:
                        await user.send(reply_text)
                    
                    # Log that we sent a proactive message (increases the ignored_count counter by 1)
                    self.memory.record_proactive_message_sent()
                    await self.memory.save()
                    
                    # Add to history
                    self.chat_history.append({"role": "assistant", "content": reply_text})
                except Exception as e:
                    print(f"Failed to send proactive message: {e}")

    @tasks.loop(seconds=settings.PROACTIVE_LOOP_INTERVAL)
    async def reminder_loop(self):
        """
        A background loop that checks for due reminders in the MemoryManager.
        If a reminder is due, it sends a DM to the owner and marks it as triggered.
        """
        # 1. Fetch due reminders
        due_reminders = self.memory.get_due_reminders()
        if not due_reminders:
            return
            
        # 2. Get owner info
        owner_info = self.memory.get_owner_relationship()
        if not owner_info["owner_id"]:
            return
            
        try:
            user = await self.fetch_user(owner_info["owner_id"])
            if not user: return
            
            for reminder in due_reminders:
                try:
                    # Send the reminder DM
                    alert_msg = f"🔔 **REMINDER**: {reminder['message']}"
                    await user.send(alert_msg)
                    
                    # Mark as triggered in the in-memory cache
                    reminder["triggered"] = True
                    print(f"REMINDER: Triggered alert for {user.name}: {reminder['message']}")
                except Exception as e:
                    print(f"Error sending individual reminder: {e}")
            
            # 3. Periodically clean old reminders BEFORE saving
            self.memory.clean_old_reminders()
            
            # 4. Save the cache to disk (atomic write)
            await self.memory.save()
            
        except Exception as e:
            print(f"Critical error in reminder_loop: {e}")

    @proactive_loop.before_loop
    @reminder_loop.before_loop
    async def before_loops(self):
        """
        Ensures the bot is fully connected to Discord before starting the loops.
        """
        await self.wait_until_ready()

if __name__ == "__main__":
    # Check if another bot instance is already running
    if not acquire_lock():
        print("\n" + "="*60)
        print("CRITICAL ERROR: ANOTHER BOT INSTANCE IS ALREADY RUNNING!")
        print(f"Please close the other terminal or kill the existing process.")
        print("To force-start, manually delete the '.bot.lock' file.")
        print("="*60 + "\n")
        os._exit(1)

    try:
        token = os.environ.get("DISCORD_TOKEN")
        if not token:
            print("ERROR: DISCORD_TOKEN is missing in the environment.")
        else:
            # Instantiate and run our bot blockingly.
            bot = AgentBot()
            bot.run(token)
    finally:
        # Ensure the lock file is removed even if the bot crashes
        release_lock()
