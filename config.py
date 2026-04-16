import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.environ["BOT_TOKEN"]
TG_API_ID: int = int(os.environ["TG_API_ID"]) if os.environ.get("TG_API_ID") else 0
TG_API_HASH: str = os.environ.get("TG_API_HASH", "")
ANTHROPIC_API_KEY: str = os.environ["ANTHROPIC_API_KEY"]
OWNER_ID: int = int(os.environ["OWNER_ID"])

DB_PATH: str = "digest.db"
SESSION_NAME: str = "user_session"
COLLECT_INTERVAL_HOURS: int = 6
MAX_POSTS_PER_CHANNEL: int = 50
POST_MAX_CHARS: int = 800
DIGEST_MAX_POSTS: int = 200
