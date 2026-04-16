import html as html_lib
import logging
import re
import time
from datetime import datetime

import httpx
from telethon import TelegramClient
from telethon.errors import FloodWaitError

from config import SESSION_NAME, TG_API_ID, TG_API_HASH, MAX_POSTS_PER_CHANNEL
from database import get_active_channels, save_post, cleanup_old_posts

logger = logging.getLogger(__name__)

client = TelegramClient(SESSION_NAME, TG_API_ID, TG_API_HASH)

# True when Telethon credentials are not configured — use web scraping instead
_USE_WEB = TG_API_ID == 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_username(raw: str) -> str:
    raw = raw.strip()
    match = re.search(r"(?:t\.me/)([A-Za-z0-9_]+)", raw)
    if match:
        return match.group(1)
    return raw.lstrip("@")


def _parse_tme_html(html_content: str, since_ts: int) -> list[dict]:
    """Extract posts from a t.me/s/channel HTML page."""
    posts = []
    # Split page into per-message blocks by the data-post attribute
    blocks = re.split(r'(?=<div[^>]+data-post=")', html_content)

    for block in blocks:
        # Message ID
        id_m = re.search(r'data-post="[^/]+/(\d+)"', block)
        if not id_m:
            continue
        msg_id = int(id_m.group(1))

        # Timestamp
        time_m = re.search(r'datetime="(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[^"]*)"', block)
        if not time_m:
            continue
        try:
            dt_str = time_m.group(1)
            if dt_str.endswith("Z"):
                dt_str = dt_str[:-1] + "+00:00"
            ts = int(datetime.fromisoformat(dt_str).timestamp())
        except Exception:
            continue

        if ts < since_ts:
            continue

        # Text — grab content of the message_text div
        text_m = re.search(
            r'class="tgme_widget_message_text[^"]*"[^>]*>([\s\S]*?)</div>',
            block,
        )
        if not text_m:
            continue

        raw = re.sub(r'<br\s*/?>', "\n", text_m.group(1), flags=re.IGNORECASE)
        text = html_lib.unescape(re.sub(r"<[^>]+>", "", raw)).strip()
        text = re.sub(r"\n{3,}", "\n\n", text)

        if len(text) < 20:
            continue

        posts.append({"msg_id": msg_id, "ts": ts, "text": text})

    return posts


# ---------------------------------------------------------------------------
# Web-scraping mode
# ---------------------------------------------------------------------------

async def _validate_channel_web(username: str) -> dict | None:
    url = f"https://t.me/s/{username}"
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as http:
            r = await http.get(url)
            if r.status_code != 200:
                return None

            title_m = re.search(
                r'<div class="tgme_page_title">\s*<span[^>]*>([^<]+)</span>', r.text
            )
            title = html_lib.unescape(title_m.group(1)) if title_m else username

            members_m = re.search(r'<div class="tgme_page_extra">([^<]+)</div>', r.text)
            members_str = members_m.group(1) if members_m else ""
            members_count = (
                int(re.sub(r"\D", "", members_str))
                if re.search(r"\d", members_str)
                else 0
            )

            return {"username": username, "title": title, "members_count": members_count}
    except Exception as e:
        logger.error("Error validating channel %s via web: %s", username, e)
        return None


async def _collect_channel_web(username: str, since_ts: int) -> int:
    url = f"https://t.me/s/{username}"
    saved = 0
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as http:
            r = await http.get(url)
            if r.status_code != 200:
                logger.error("Channel %s returned HTTP %s", username, r.status_code)
                return 0

        for post in _parse_tme_html(r.text, since_ts):
            await save_post(username, post["msg_id"], post["text"], post["ts"])
            saved += 1
    except Exception as e:
        logger.error("Error collecting %s via web: %s", username, e)
    return saved


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def validate_channel(raw: str) -> dict | None:
    username = _normalize_username(raw)
    if not username:
        return None

    if _USE_WEB:
        return await _validate_channel_web(username)

    try:
        entity = await client.get_entity(username)
        title = getattr(entity, "title", username)
        members_count = getattr(entity, "participants_count", None) or 0
        return {"username": username, "title": title, "members_count": members_count}
    except FloodWaitError as e:
        logger.error("FloodWaitError validating channel %s: wait %s sec", username, e.seconds)
        return None
    except Exception as e:
        logger.error("Error validating channel %s: %s", username, e)
        return None


async def collect_posts(hours_back: int = 25) -> int:
    channels = await get_active_channels()
    since_ts = int(time.time()) - hours_back * 3600
    saved_total = 0

    for channel in channels:
        username = channel["username"]

        if _USE_WEB:
            saved_total += await _collect_channel_web(username, since_ts)
            continue

        try:
            saved_count = 0
            async for message in client.iter_messages(username, limit=MAX_POSTS_PER_CHANNEL):
                if message.date.timestamp() < since_ts:
                    break
                text = message.text or message.caption or ""
                if len(text) < 20:
                    continue
                await save_post(
                    channel_username=username,
                    message_id=message.id,
                    text=text,
                    timestamp=int(message.date.timestamp()),
                )
                saved_count += 1
            saved_total += saved_count
        except FloodWaitError as e:
            logger.error("FloodWaitError collecting %s: wait %s sec", username, e.seconds)
        except Exception as e:
            logger.error("Error collecting posts from %s: %s", username, e)

    await cleanup_old_posts()
    return saved_total
