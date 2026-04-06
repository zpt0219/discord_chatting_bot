import os
from dotenv import load_dotenv

# Ensure environment variables are loaded if this module is imported standalone
load_dotenv()

# =======================================================
# BOT IDENTITY & OWNER
# =======================================================
# Discord username of the primary owner. The bot only responds to this user.
OWNER_USERNAME = os.getenv("OWNER_USERNAME", "")

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

# Max total characters to keep in long-term key memories (Pruned for context safety).
MAX_KEY_MEMORIES_LEN = 5000

# Max facts to inject per category in the system prompt.
MAX_FACTS_PER_CATEGORY = 10

# Global character ceiling for all facts injected into the prompt.
MAX_FACTS_TOTAL_CHARS = 3000

# Max facts to keep in permanent disk storage per category (to prevent disk-leak).
# When this cap is reached, the oldest facts are pruned.
MAX_STORAGE_FACTS_PER_CATEGORY = 200

# Friendly error messages when ALL model tiers fail.
ERROR_MSG_GENERIC = "*(I'm having a bit of a brain-freeze right now! 😵‍💫 Give me a second to reset and try again.)*"
ERROR_MSG_VISION = "*(I tried to look at that image, but my eyes are a bit blurry right now... 👁️‍🗨️)*"

# Separator used when combining multiple queued messages into one query.
QUEUE_COMBINE_SEPARATOR = "\n[followed by]\n"

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
