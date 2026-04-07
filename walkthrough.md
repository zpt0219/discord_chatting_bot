# 🚀 Discord Agent: Technical Walkthrough

This document provides a deep dive into the engineering decisions, architectural patterns, and future roadmap of the Discord Agent.

---

## 🏛️ 1. System Architecture

The bot is designed as a **Tiered Multi-Modal Agent**. It follows a "Sense-Think-Act" loop with a focus on resource optimization and failover reliability.

### The Tiered Router
To balance cost, speed, and intelligence, the bot uses a three-tier routing strategy:
1.  **Tier 1: Local Llama (Edge)**: Handles simple conversational turns and small talk. If a local server is detected in `.env`, it is the first line of defense, ensuring maximum privacy and zero API costs for basic chat.
2.  **Tier 2: OpenAI GPT-4o (Logic/Vision)**: The primary heavyweight for complex reasoning, multi-step tool use, and high-fidelity image analysis.
3.  **Tier 3: Anthropic Claude 4.5 (Resilience)**: Acts as the ultimate failover. If OpenAI's rate limits are hit or the API is down, Claude takes over to ensure the bot never "goes dark."

### Concurrency & Integrity
- **Global Processing Lock**: A `self._processing_lock` ensures that for any given user, messages are processed strictly sequentially. This prevents race conditions where two simultaneous messages might try to update the same memory file.
- **Message Batching**: If a user sends multiple messages in rapid succession (while the bot is still "thinking"), those messages are queued and combined into a single "followed by" query. This reduces API overhead and maintains a natural conversational flow.
- **Process Singleton**: Uses a `psutil`-powered `.bot.lock` to ensure only one instance of the bot runs at a time, protecting the local JSON database from multi-process corruption.

---

## 🧠 2. How Memory Works

Memory is the core of this agent. It doesn't just "remember" text; it **categorizes and abstracts** life facts about the owner.

### Categorized Knowledge Store
Every interaction is followed by a "Reflection" phase where the bot extracts facts into structured categories:
- 👤 **Identity**: Name, profession, core bio.
- 🌟 **Interests**: Hobbies, favorite media, passions.
- ⚙️ **Preferences**: Communication style and bot behavioral requests.
- 📅 **Routine**: Daily habits and schedule.
- 🧠 **Key Memories**: High-level summaries of significant past conversations.

### Persistence Mechanism
- **Atomic Disk Writes**: Uses a "Write-Temp-and-Swap" pattern. Data is written to a `.tmp` file and then renamed. This ensures that even if the server loses power mid-save, the main database remains uncorrupted.
- **Context Injection**: During the "Think" phase, the `agent.py` pulls the most recent facts from each category and injects them into the system prompt. This gives the bot "instant recall" of everything it knows about you without needing to scan thousands of lines of history.

---

## 📡 3. Proactive Outreach

The bot is designed to feel alive, not just reactive. It initiates conversation based on relationship depth and idle time.

### The Proactive Loop
- **Interval Checking**: A background task runs every 60 seconds to evaluate the "Social State."
- **Relationship-Based Delays**: The baseline wait time scales as the bot gets to know you:
    - **Stranger**: Checks in every ~10 minutes.
    - **Acquaintance**: Checks in every ~30 minutes.
    - **Friend**: Checks in every ~2 hours.
- **Exponential Backoff**: To avoid becoming "needy" or spammy, the bot tracks `proactive_messages_ignored`. For every time you ignore a proactive reach-out, the delay is doubled (2^N). If you reply, the counter resets.

### Ethical Guards
- **Interaction Lock**: The bot will *never* proactively reach out if you are currently in a conversation (lock held) or if it was the one who sent the very last message.

---

## 🛠️ 4. Future Improvements (Roadmap)

Given more time, the following high-impact features would be implemented:

1.  **Vector Database Integration (RAG)**: While the JSON store is great for structured facts, a Vector DB (like Chroma or Pinecone) would allow the bot to search through *thousands* of raw past messages for specific details that fall outside the "Key Memories" abstraction.
2.  **Multi-User Relationships**: Currently, the bot is owner-focused. Refactoring the `MemoryManager` to handle a `{user_id: data}` mapping would allow the bot to maintain unique, separate relationships with everyone in a Discord server.
3.  **Voice Interaction (STT/TTS)**: Fully implementing native Discord voice channel support so the owner can talk to the bot in real-time, using Whisper for transcription and ElevenLabs or OpenAI for high-fidelity speech.
4.  **Play Discord Game Together**: Implement a skill that allows the bot to play simple games with the owner.
