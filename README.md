# 🤖 Discord Agent Bot: Multi-Modal & Long-Term Memory

A sophisticated, persistent Discord agent designed for deep, context-aware interaction. This bot goes beyond simple chat by combining **categorized long-term memory**, **multi-modal capabilities** (Vision & Voice), and a **dynamic routing system** that intelligently switches between local and cloud LLMs.

---

## 🚀 Key Features

### 🧠 Advanced Persistent Memory
- **Categorized Knowledge Store**: Automatically extracts and organizes facts about the owner into structured categories:
    - 👤 **Identity**: Name, roles, and background.
    - 🌟 **Interests**: Hobbies, media, and passions.
    - ⚙️ **Preferences**: How you want the bot to behave.
    - 📅 **Routine**: Your daily schedule and habits.
- **Conversation Abstraction**: Periodically summarizes long conversations into high-level "memories" to maintain context without hitting token limits.
- **Sequential Integrity**: Uses an atomic write-back system with a singleton lock to ensure memory is never corrupted during high-concurrency message bursts.

### 🖼️ Multi-Modal Intelligence
- **Vision Integration**: Send images to the bot for analysis, feedback, or just to share a moment. Powered by Claude 3.5 Sonnet and GPT-4o.
- **Voice Message Support**: Native support for Discord voice messages. The bot "listens" to your audio and responds appropriately.

### 🚦 Intelligent Model Routing
The bot optimizes for speed, cost, and complexity by dynamically selecting the best model for the task:
1.  **Local Llama 3**: Handles simple conversational turns and small-talk locally for maximum privacy and speed.
2.  **Claude 3.5 Sonnet**: The primary "brain" for complex analysis, creative writing, and image vision.
3.  **OpenAI GPT-4o**: The final fallback and primary engine for native audio processing.

### 🛠️ Integrated Skills & Tools
- **Web Search**: Real-time browsing to answer factual questions.
- **Link Reader**: Deep-content extraction from any provided URL (strips HTML noise for clean reading).
- **Weather integration**: Real-time hyper-local weather reports.
- **Identity Portraits**: The bot can share official head-portraits of itself with varying facial expressions.
- **Brain Transparency**: Ask *"What do you know about me?"* to see a formatted summary of your stored profile.

### 🔔 Proactive Engagement
- The bot isn't just reactive. It will occasionally reach out to check in on you if you've been away, using a **smart backoff system** that scales based on your relationship stage (Stranger -> Acquaintance -> Friend).

---

## 🛠️ Setup & Installation

### 1. Prerequisites
- Python 3.10+
- A Discord Bot Token (via [Discord Developer Portal](https://discord.com/developers/applications))
- API Keys for Anthropic and OpenAI.
- (Optional) Local LLM server running an OpenAI-compatible API.

### 2. Environment Variables
Create a `.env` file in the root directory:
```env
DISCORD_TOKEN=your_discord_bot_token
ANTHROPIC_API_KEY=your_anthropic_api_key
OPENAI_API_KEY=your_openai_api_key
LOCAL_LLM_URL=http://localhost:1234/v1  # Optional: for local fallback
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Run the Bot
```bash
python bot.py
```

---

## 🏗️ System Architecture
[View the high-level architecture diagram and data flow here.](architecture.md)

---

## 📁 Project Structure (Key Components)

- `bot.py`: The entry point, Discord handles, and background loops for reminders and proactive messages.
- `agent.py`: **Context & Prompting**: Gathers memories and formats the system prompt for the AI.
- `models/router.py`: **The Switchboard**: Dynamically selects the best LLM (Llama, Claude, GPT-4o) and handles failover strategy.
- `memory_manager.py`: Handles all in-memory caching, JSON persistence, and categorization logic.
- `prompts.py`: Centralized system and extraction prompts.
- `settings.py`: Global configuration for timers, thresholds, and limits.
- `skills/`: Individual tool implementations (Search, Weather, Link Reader, etc.).
- `models/`: Provider-specific logic for OpenAI, Claude, and Local models.

---

## 🛡️ Safety & Stability
- **Locked Execution**: Uses a `.bot.lock` file to prevent multiple instances from running simultaneously.
- **Constraint Management**: Hard character limits on summarized memories (10k) and Discord messages (2k) to ensure reliability.
- **Graceful Fallbacks**: If one LLM provider is down, the bot automatically tries the next one in the priority chain.
