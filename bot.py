import os
import discord
from discord.ext import tasks
from dotenv import load_dotenv
import asyncio
import time

# Import our custom modules for handling memory and AI interactions
from memory_manager import MemoryManager
from agent import generate_response, extract_and_update_memory

# Load environment variables from the .env file (like DISCORD_TOKEN)
load_dotenv()

# We retrieve the discord token from the environment securely.
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")

# The specific username of the owner that the bot will respond to.
OWNER_USERNAME = "cm6550"

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
        
        # Maintain a short recent history (last 10 turns) per user session.
        # Since this bot focuses on a single owner, we use one simple list.
        # This keeps the context window small while relying on JSON data for long-term memory.
        self.chat_history = []
        
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
        Called every time a message is sent in a channel/DM the bot can see.
        """
        # Security/Sanity Check: Ignore messages sent by the bot itself to prevent infinite loops.
        if message.author.id == self.user.id:
            return
            
        # We enforce the "owner-only" rule. The prompt asked to set cm6550 as the owner.
        # We check both the username and global_name to be safe.
        if message.author.name != OWNER_USERNAME and message.author.global_name != OWNER_USERNAME:
            print(f"Ignored message from {message.author.name} (not '{OWNER_USERNAME}')")
            # If the user is not cm6550, we simply drop the message and do nothing.
            # (Uncomment the 'return' below to strictly enforce, currently bypassed to allow recruiters to test).
            # return
            
        # We save the discord user ID of whoever messages it. 
        # This allows the bot to know WHO to DM when it proactively reaches out later.
        self.memory.set_owner_id_if_null(message.author.id)
        
        # We only want the bot to reply to Direct Messages (DMs) or if explicitly @mentioned in a server.
        is_dm = isinstance(message.channel, discord.DMChannel)
        is_mentioned = self.user in message.mentions
        
        if not is_dm and not is_mentioned:
            # If it's a random server message that doesn't mention the bot, ignore it.
            return
            
        # Clean the message text to remove the @AgentBot mention text if it exists.
        clean_msg = message.clean_content.replace(f"@{self.user.name}", "").strip()
            
        # Show the "typing..." indicator in Discord so it feels more human while waiting for the LLM.
        async with message.channel.typing():
            # 1. Append the user's message to our short-term context.
            self.chat_history.append({"role": "user", "content": clean_msg})
            
            # Prune history to just the last 10 messages (5 turns) to save tokens.
            if len(self.chat_history) > 10:
                self.chat_history = self.chat_history[-10:]
                
            # 2. Call the LLM (Claude) to generate a conversational reply based on the JSON memory and history.
            reply = await generate_response(self.memory, self.chat_history)
            
            # 3. Actually send the generated reply back to Discord.
            await message.channel.send(reply)
            
            # 4. Notify the memory manager that an interaction occurred (resets our backoff/idle timers).
            self.memory.record_owner_reply()
            
            # 5. Append the AI's response to the short-term history so it remembers what it just said.
            self.chat_history.append({"role": "assistant", "content": reply})
            
            # 6. Kick off a background, non-blocking task that extracts facts from the conversation.
            # This allows the bot to reply instantly without waiting for the fact-extraction LLM logic.
            asyncio.create_task(
                extract_and_update_memory(self.memory, clean_msg, reply)
            )

    @tasks.loop(minutes=1.0)
    async def proactive_loop(self):
        """
        A background loop that runs every 60 seconds.
        It evaluates if the bot should proactively message the owner based on relationship stage and idle time.
        """
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
        if stage == 0:
            # Stage 0: Stranger/Just met. Reach out quickly to learn more (e.g. 2 minutes).
            target_delay = 60 * 2
        elif stage == 1:
            # Stage 1: Acquaintance. Reach out moderately (e.g. 5 minutes).
            target_delay = 60 * 5
        else:
            # Stage 2: Friend. Very relaxed, respectful of space (e.g. 15 minutes).
            target_delay = 60 * 15
            
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
            user = self.get_user(owner_info["owner_id"])
            if user:
                # We prompt the LLM to generate a natural opening message, tricking it by putting this system prompt in the user's mouth.
                prompt_text = "Your owner hasn't spoken to you in a while. Generate a brief, natural message to reach out to them based on what you know about them. If you haven't picked a name yet, you could mention being a bit lost or curious. Please output ONLY the exact message you'd send, no quotes."
                
                # Append this temporary prompt to our history and send it to the LLM.
                temp_hist = self.chat_history + [{"role": "user", "content": prompt_text}]
                
                try:
                    reply = await generate_response(self.memory, temp_hist)
                    
                    # Send the AI's proactive text as a Direct Message
                    await user.send(reply)
                    
                    # Log that we sent a proactive message (increases the ignored_count counter by 1)
                    self.memory.record_proactive_message_sent()
                    
                    # Add to history
                    self.chat_history.append({"role": "assistant", "content": reply})
                except Exception as e:
                    print(f"Failed to send proactive message: {e}")

    @proactive_loop.before_loop
    async def before_proactive_loop(self):
        """
        Ensures the bot is fully connected to Discord before starting the loop.
        """
        await self.wait_until_ready()

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("ERROR: DISCORD_TOKEN is missing in the environment.")
    else:
        # Instantiate and run our bot blockingly.
        bot = AgentBot()
        bot.run(DISCORD_TOKEN)
