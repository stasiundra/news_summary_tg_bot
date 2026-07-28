import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR: Path = Path(__file__).resolve().parent

BOT_TOKEN: str = os.environ["BOT_TOKEN"]
TG_API_ID: int = int(os.environ["TG_API_ID"]) if os.environ.get("TG_API_ID") else 0
TG_API_HASH: str = os.environ.get("TG_API_HASH", "")
ANTHROPIC_API_KEY: str = os.environ["ANTHROPIC_API_KEY"]
OWNER_ID: int = int(os.environ["OWNER_ID"])

DB_PATH: str = str(BASE_DIR / "digest.db")
SESSION_NAME: str = "user_session"
COLLECT_INTERVAL_HOURS: int = 6
MAX_POSTS_PER_CHANNEL: int = 50
POST_MAX_CHARS: int = 400
DIGEST_MAX_POSTS: int = 200

WEB_AUTH_TOKEN: str = os.environ.get("WEB_AUTH_TOKEN", "")
WEB_BIND_HOST: str = os.environ.get("WEB_BIND_HOST", "127.0.0.1")
WEB_PORT: int = int(os.environ.get("WEB_PORT", "8080"))

# Claude model for digest generation and Q&A.
# Options (pricing per million tokens, input/output):
#   claude-haiku-4-5       $1/$5   — fastest, cheapest, near-frontier (default)
#   claude-sonnet-5        $2/$10  — best speed/intelligence balance (intro until 2026-08-31)
#   claude-opus-5          $5/$25  — highest quality, slower
CLAUDE_MODEL: str = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5")
