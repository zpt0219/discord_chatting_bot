import os
import discord
from discord.ext import tasks
from dotenv import load_dotenv
import asyncio
import time

# Import our custom modules for handling memory and AI interactions
from memory_manager import MemoryManager
from agent import generate_response, extract_and_update_memory

import settings
from prompts import PROACTIVE_PROMPT
load_dotenv()

# =======================================================
# SINGLETON INSTANCE LOCK (Anti-Multi-Reply)
# =======================================================
# This ensures that only one instance of the bot is running globally.
# It protects against race conditions where multiple processes might try
# to write to the same persistent JSON memory simultaneously.
LOCK_FILE = ".bot.lock"

def acquire_lock():
    """Tries to create a lock file to ensure singleton status."""
    try:
        # os.O_EXCL ensures the file is created ONLY if it doesn't exist (atomic)
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, 'w') as f:
            f.write(str(os.getpid()))
        return True
    except FileExistsError:
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
        
    async def setup_hook(self):
        """
        A special Pycord/Discord.py lifecycle method called before the bot connects.
        This is the ideal place to start background tasks.
        """
        # Start the proactive outreach loop
        self.proactive_loop.start()

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
        # if message.author.name != owner and message.author.global_name != owner:
            # print(f"Ignored message from {message.author.name} (not '{owner}')")
            # If the user is not the owner, we simply drop the message and do nothing.
            # return
            
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
            
        # Acquire the lock so only one message is processed at a time.
        # This prevents duplicate replies when messages arrive faster than the LLM can respond.
        async with self._processing_lock:
            # 1. If memory is empty (bot restarted), dynamically fetch recent conversation from Discord.
            if len(self.chat_history) == 0:
                print("Memory out of sync! Fetching recent history directly from Discord channel...")
                temp_hist = []
                # Fetch history based on configuration limit
                limit = settings.CHAT_HISTORY_FETCH_LIMIT
                async for old_msg in message.channel.history(limit=limit, before=message):
                    role = "assistant" if old_msg.author.id == self.user.id else "user"
                    old_clean = old_msg.clean_content.replace(f"@{self.user.name}", "").strip()
                    if old_clean:
                        temp_hist.append({"role": role, "content": old_clean})
                # Discord returns history continuously backwards in time, so we must flip it chronological
                temp_hist.reverse()
                self.chat_history = temp_hist

            # 2. Detect and download image attachments from the Discord message.
            image_data_list = []
            audio_data_list = []
            for attachment in message.attachments:
                # Process image file types
                if attachment.content_type and attachment.content_type.startswith("image/"):
                    try:
                        img_bytes = await attachment.read()
                        import base64
                        b64_str = base64.b64encode(img_bytes).decode("utf-8")
                        
                        # Detect the REAL media type from magic bytes.
                        # Discord sometimes lies about content_type (e.g., says webp but it's actually png).
                        real_media_type = attachment.content_type
                        if img_bytes[:8] == b'\x89PNG\r\n\x1a\n':
                            real_media_type = "image/png"
                        elif img_bytes[:2] == b'\xff\xd8':
                            real_media_type = "image/jpeg"
                        elif img_bytes[:4] == b'GIF8':
                            real_media_type = "image/gif"
                        elif img_bytes[:4] == b'RIFF' and img_bytes[8:12] == b'WEBP':
                            real_media_type = "image/webp"
                        
                        image_data_list.append({
                            "base64": b64_str,
                            "media_type": real_media_type
                        })
                        print(f"IMAGE: Downloaded '{attachment.filename}' (detected: {real_media_type}, reported: {attachment.content_type}, {len(img_bytes)} bytes)")
                    except Exception as img_err:
                        print(f"Warning: Failed to download image attachment: {img_err}")
                
                # Process audio file types (mp3, wav, ogg, m4a, flac, webm, etc.)
                elif attachment.content_type and attachment.content_type.startswith("audio/"):
                    try:
                        audio_bytes = await attachment.read()
                        import base64
                        b64_str = base64.b64encode(audio_bytes).decode("utf-8")
                        
                        # Map content type to OpenAI's expected format string
                        format_map = {
                            "audio/mpeg": "mp3", "audio/mp3": "mp3",
                            "audio/wav": "wav", "audio/x-wav": "wav",
                            "audio/ogg": "wav", "audio/flac": "flac",
                            "audio/mp4": "mp3", "audio/m4a": "mp3",
                            "audio/webm": "wav",
                        }
                        audio_format = format_map.get(attachment.content_type, "mp3")
                        
                        audio_data_list.append({
                            "base64": b64_str,
                            "format": audio_format
                        })
                        print(f"AUDIO: Downloaded '{attachment.filename}' ({attachment.content_type}, {len(audio_bytes)} bytes)")
                    except Exception as audio_err:
                        print(f"Warning: Failed to download audio attachment: {audio_err}")

            # 3. Append the user's newest message to our synchronized context.
            # We store only the text in chat_history (media is too large to persist in memory)
            if clean_msg:
                label = clean_msg
            elif audio_data_list:
                label = "[sent a voice message]"
            else:
                label = "[sent an image]"
            self.chat_history.append({"role": "user", "content": label})
            
            # 4. Prune history based on configuration limit
            limit = settings.CHAT_HISTORY_PRUNE_LIMIT
            if len(self.chat_history) > limit:
                self.chat_history = self.chat_history[-limit:]
                    
            # 5. Call the LLM to generate a conversational reply within the typing block.
            async with message.channel.typing():
                res = await generate_response(
                    self.memory, self.chat_history,
                    image_data=image_data_list if image_data_list else None,
                    audio_data=audio_data_list if audio_data_list else None
                )
                reply_text = res["text"]
                attachment_path = res["attachment"]
                
                # 6. Actually send the generated reply back to Discord.
                limit = settings.MAX_DISCORD_MSG_LEN
                safe_reply = reply_text[:limit]
                
                if attachment_path and os.path.exists(attachment_path):
                    file = discord.File(attachment_path)
                    await message.channel.send(safe_reply, file=file)
                else:
                    await message.channel.send(safe_reply)
            
            # --- SEQUENTIAL POST-PROCESSING (REFLECT) --- 
            # We un-indent this from the typing block so the bot stops showing as 'typing'
            # but we keep it INSIDE the processing_lock to ensure memory writes are atomic.
            
            # 7. Update short-term context
            self.chat_history.append({"role": "assistant", "content": reply_text})
            
            # 8. Trigger Semantic Extraction & Memory Hardening
            # The background model (Llama or Claude) abstracts the exchange and updates
            # the Categorized Knowledge Store (Identity, Interests, etc.) and summaries.
            await extract_and_update_memory(self.memory, clean_msg, reply_text)


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
        multiplier = (2 ** ignored_count) if ignored_count > 0 else 1
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
                    
                    # Add to history
                    self.chat_history.append({"role": "assistant", "content": reply_text})
                except Exception as e:
                    print(f"Failed to send proactive message: {e}")

    @proactive_loop.before_loop
    async def before_proactive_loop(self):
        """
        Ensures the bot is fully connected to Discord before starting the loop.
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
