import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR: Path = Path(__file__).resolve().parent

BOT_TOKEN: str = os.environ["BOT_TOKEN"]
TG_API_ID: int = int(os.environ["TG_API_ID"]) if os.environ.get("TG_API_ID") else 0
TG_API_HASH: str = os.environ.get("TG_API_HASH", "")
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

# ---------------------------------------------------------------------------
# LLM backend
# ---------------------------------------------------------------------------
# Основной провайдер генерации: "ollama" (default) или "gemini".
LLM_PROVIDER: str = os.environ.get("LLM_PROVIDER", "ollama").strip().lower()
# Резервные провайдеры через запятую, пробуются после основного: "gemini", "" — выключено.
LLM_FALLBACK_PROVIDERS: str = os.environ.get("LLM_FALLBACK_PROVIDERS", "gemini")
LLM_TIMEOUT_S: float = float(os.environ.get("LLM_TIMEOUT_S", "300"))

# Ollama: локальный демон (http://127.0.0.1:11434) или облако (https://ollama.com + OLLAMA_API_KEY).
OLLAMA_BASE_URL: str = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_API_KEY: str = os.environ.get("OLLAMA_API_KEY", "")
OLLAMA_MODEL: str = os.environ.get("OLLAMA_MODEL", "deepseek-v4.1-flash:cloud")
# OLLAMA_THINK=false — прятать reasoning-цепочку моделей с "thinking" (deepseek-v4.1-flash и др.).
OLLAMA_THINK: bool = os.environ.get("OLLAMA_THINK", "false").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)

# Gemini (резервный провайдер).
# Free tier: 15 req/min, 1500 req/day.
# Options:
#   gemini-3.6-flash      — current default
#   gemini-flash-latest   — always points to newest flash model
#   gemini-2.5-flash      — legacy, may be unavailable to new keys
GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL: str = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
