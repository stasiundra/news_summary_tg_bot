import time
import aiosqlite
from config import DB_PATH, OWNER_ID


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id         INTEGER PRIMARY KEY,
                username   TEXT,
                full_name  TEXT,
                added_at   INTEGER NOT NULL,
                is_active  INTEGER NOT NULL DEFAULT 1
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                username   TEXT    NOT NULL UNIQUE,
                title      TEXT,
                added_at   INTEGER NOT NULL,
                is_active  INTEGER NOT NULL DEFAULT 1
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_username TEXT    NOT NULL,
                message_id       INTEGER NOT NULL,
                text             TEXT,
                timestamp        INTEGER NOT NULL,
                UNIQUE(channel_username, message_id)
            )
        """)
        await db.commit()

        cursor = await db.execute("SELECT id FROM users WHERE id = ?", (OWNER_ID,))
        row = await cursor.fetchone()
        if row is None:
            await db.execute(
                "INSERT INTO users (id, username, full_name, added_at, is_active) VALUES (?, NULL, 'Owner', ?, 1)",
                (OWNER_ID, int(time.time())),
            )
            await db.commit()


# --- Пользователи ---

async def add_user(user_id: int, username: str | None, full_name: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT id FROM users WHERE id = ?", (user_id,))
        row = await cursor.fetchone()
        if row is not None:
            return False
        await db.execute(
            "INSERT INTO users (id, username, full_name, added_at, is_active) VALUES (?, ?, ?, ?, 1)",
            (user_id, username, full_name, int(time.time())),
        )
        await db.commit()
        return True


async def remove_user(user_id: int) -> bool:
    if user_id == OWNER_ID:
        return False
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        await db.commit()
        return cursor.rowcount > 0


async def get_active_users() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, username, full_name, added_at FROM users WHERE is_active = 1"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def is_allowed_user(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id FROM users WHERE id = ? AND is_active = 1", (user_id,)
        )
        row = await cursor.fetchone()
        return row is not None


# --- Каналы ---

async def add_channel(username: str, title: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT id FROM channels WHERE username = ?", (username,))
        row = await cursor.fetchone()
        if row is not None:
            return False
        await db.execute(
            "INSERT INTO channels (username, title, added_at, is_active) VALUES (?, ?, ?, 1)",
            (username, title, int(time.time())),
        )
        await db.commit()
        return True


async def remove_channel(username: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("DELETE FROM channels WHERE username = ?", (username,))
        await db.commit()
        return cursor.rowcount > 0


async def get_active_channels() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT username, title, added_at FROM channels WHERE is_active = 1"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def channel_exists(username: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id FROM channels WHERE username = ?", (username,)
        )
        row = await cursor.fetchone()
        return row is not None


# --- Посты ---

async def save_post(channel_username: str, message_id: int, text: str, timestamp: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO posts (channel_username, message_id, text, timestamp)
            VALUES (?, ?, ?, ?)
            """,
            (channel_username, message_id, text, timestamp),
        )
        await db.commit()


async def get_posts_since(since_ts: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT channel_username, message_id, text, timestamp FROM posts WHERE timestamp >= ? ORDER BY timestamp DESC",
            (since_ts,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def delete_posts_by_channel(username: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM posts WHERE channel_username = ?", (username,))
        await db.commit()


async def cleanup_old_posts() -> None:
    cutoff = int(time.time()) - 8 * 24 * 3600
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM posts WHERE timestamp < ?", (cutoff,))
        await db.commit()
