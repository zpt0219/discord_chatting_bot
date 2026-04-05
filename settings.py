import os

# =======================================================
# BOT IDENTITY & OWNER
# =======================================================
OWNER_USERNAME = "cm6550"

# =======================================================
# ROUTER CONFIGURATIONS (agent.py)
# =======================================================
# Length threshold for determining if a query is complex.
# Any message longer than this will bypass the local model and go to cloud (Claude).
# Default: 500 characters (Higher value allows long proactive prompts to stay local).
ROUTER_COMPLEXITY_LEN_THRESHOLD = 500

# Keywords that trigger the "Complex" router to skip the local model.
ROUTER_COMPLEX_KEYWORDS = ["explain", "why", "how", "compare", "write", "code", "analyze"]

# =======================================================
# DISCORD LIMITS & HISTORY
# =======================================================
# Hard limit of characters per message to avoid Discord API crashes.
MAX_DISCORD_MSG_LEN = 1999

# Number of messages to fetch from history if memory is out of sync.
CHAT_HISTORY_FETCH_LIMIT = 20

# Max messages to keep in local chat history (sliding window).
CHAT_HISTORY_PRUNE_LIMIT = 20

# Max total characters to keep in long-term summarized memories.
MAX_SUMMARIZED_MEMORIES_LEN = 10000

# =======================================================
# PROACTIVE OUTREACH TIMERS (in seconds)
# =======================================================
# Interval for the proactive outreach loop check.
PROACTIVE_LOOP_INTERVAL = 60.0

# Delays before the bot reaches out, based on relationship stage.
PROACTIVE_DELAY_STRANGER = 60 * 10        # 10 minutes
PROACTIVE_DELAY_ACQUAINTANCE = 60 * 30    # 30 minutes
PROACTIVE_DELAY_FRIEND = 60 * 120        # 2 hours

# =======================================================
# ASSET PATHS
# =======================================================
BOT_PORTRAIT_PATH = "assets/bot_portrait.png"
