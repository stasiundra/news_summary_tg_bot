import logging
import re
import time

from telethon import TelegramClient
from telethon.errors import FloodWaitError

from config import SESSION_NAME, TG_API_ID, TG_API_HASH, MAX_POSTS_PER_CHANNEL
from database import get_active_channels, save_post, cleanup_old_posts

logger = logging.getLogger(__name__)

client = TelegramClient(SESSION_NAME, TG_API_ID, TG_API_HASH)


def _normalize_username(raw: str) -> str:
    raw = raw.strip()
    # https://t.me/username or t.me/username
    match = re.search(r"(?:t\.me/)([A-Za-z0-9_]+)", raw)
    if match:
        return match.group(1)
    # @username or plain username
    return raw.lstrip("@")


async def validate_channel(raw: str) -> dict | None:
    username = _normalize_username(raw)
    if not username:
        return None
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
