import asyncio
import html as html_lib
import logging
import re
import time
from datetime import datetime, timezone
from functools import wraps

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

import collector
import database
import summarizer
from config import BOT_TOKEN, COLLECT_INTERVAL_HOURS, OWNER_ID, TG_API_ID

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Access decorators
# ---------------------------------------------------------------------------

def allowed_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not await database.is_allowed_user(user_id):
            await update.effective_message.reply_text("⛔ У вас нет доступа к этому боту")
            return
        return await func(update, context)
    return wrapper


def owner_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id != OWNER_ID:
            await update.effective_message.reply_text("⛔ У вас нет доступа к этому боту")
            return
        return await func(update, context)
    return wrapper


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_date(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d.%m.%Y")


def _md_to_html(text: str) -> str:
    """Convert basic Markdown to Telegram HTML."""
    text = html_lib.escape(text)
    # Links: [text](url) → <a href="url">text</a>
    text = re.sub(r'\[([^\]]+)\]\((https?://[^)]+)\)', r'<a href="\2">\1</a>', text)
    # Bold: **text** → <b>text</b>
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    # Italic: *text* → <i>text</i>
    text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
    # Strip heading markers, keep text
    text = re.sub(r'^#{1,6} ', '', text, flags=re.MULTILINE)
    return text


def _split_text(text: str, chunk_size: int = 4000) -> list[str]:
    """Split text by newlines into chunks of at most chunk_size characters."""
    lines = text.split("\n")
    chunks: list[str] = []
    current = ""
    for line in lines:
        addition = (("\n" + line) if current else line)
        if len(current) + len(addition) > chunk_size:
            if current:
                chunks.append(current)
            # If a single line exceeds chunk_size, hard-split it
            while len(line) > chunk_size:
                chunks.append(line[:chunk_size])
                line = line[chunk_size:]
            current = line
        else:
            current += addition
    if current:
        chunks.append(current)
    return chunks


# ---------------------------------------------------------------------------
# User commands
# ---------------------------------------------------------------------------

@allowed_only
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    first_name = update.effective_user.first_name
    await update.message.reply_text(
        f"👋 Привет, {first_name}!\n\n"
        "Доступные команды:\n"
        "/digest — получить дайджест\n"
        "/channels — список каналов\n"
        "/status — статистика"
    )


@allowed_only
async def cmd_digest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📅 За сутки", callback_data="digest_24h"),
            InlineKeyboardButton("📆 За неделю", callback_data="digest_7d"),
        ]
    ])
    await update.message.reply_text("Выбери период:", reply_markup=keyboard)


@allowed_only
async def cmd_channels(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    channels = await database.get_active_channels()
    if not channels:
        await update.message.reply_text("Каналов пока нет.")
        return
    lines = [f"📡 Каналы ({len(channels)}):\n"]
    for i, ch in enumerate(channels, 1):
        lines.append(f"{i}. {ch['title']} (@{ch['username']}) · {_fmt_date(ch['added_at'])}")
    await update.message.reply_text("\n".join(lines))


@allowed_only
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    channels = await database.get_active_channels()
    now = int(time.time())
    posts_24h = await database.get_posts_since(now - 86400)
    posts_7d = await database.get_posts_since(now - 7 * 86400)

    scheduler: AsyncIOScheduler = context.bot_data["scheduler"]
    job = scheduler.get_job("collect")
    if job and job.next_run_time:
        delta = job.next_run_time.timestamp() - time.time()
        next_collect = f"через {int(delta // 3600)} ч. {int((delta % 3600) // 60)} мин."
    else:
        next_collect = "неизвестно"

    await update.message.reply_text(
        f"📊 Статус:\n\n"
        f"Каналов: {len(channels)}\n"
        f"Постов за 24ч: {len(posts_24h)}\n"
        f"Постов за 7 дней: {len(posts_7d)}\n"
        f"Следующий сбор: {next_collect}"
    )


# ---------------------------------------------------------------------------
# Digest callbacks
# ---------------------------------------------------------------------------

async def _handle_digest_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, hours: int, label: str) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(f"⏳ Генерирую дайджест за {label}...")

    since_ts = int(time.time()) - hours * 3600
    posts = await database.get_posts_since(since_ts)
    result = await summarizer.generate_digest(posts, label)
    html_result = _md_to_html(result)

    if len(html_result) <= 4096:
        await query.edit_message_text(html_result, parse_mode="HTML")
    else:
        await query.edit_message_text("📨 Отправляю частями...")
        chunks = _split_text(html_result)
        total = len(chunks)
        for i, chunk in enumerate(chunks, 1):
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"[{i}/{total}]\n{chunk}",
                parse_mode="HTML",
            )


async def cb_digest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not await database.is_allowed_user(user_id):
        await update.callback_query.answer("⛔ Нет доступа", show_alert=True)
        return

    data = update.callback_query.data
    if data == "digest_24h":
        await _handle_digest_callback(update, context, 24, "сутки")
    elif data == "digest_7d":
        await _handle_digest_callback(update, context, 168, "неделю")


# ---------------------------------------------------------------------------
# Owner commands
# ---------------------------------------------------------------------------

@owner_only
async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("ℹ️ Использование: /add @channel")
        return

    msg = await update.message.reply_text("🔄 Проверяю канал...")
    info = await collector.validate_channel(context.args[0])
    if info is None:
        await msg.edit_text("❌ Канал не найден или недоступен")
        return

    if await database.channel_exists(info["username"]):
        await msg.edit_text("⚠️ Канал уже есть в списке")
        return

    await database.add_channel(info["username"], info["title"])
    await msg.edit_text(
        f"✅ Добавлен: {info['title']} (@{info['username']})\n"
        f"👥 Подписчиков: {info['members_count']:,}\n"
        "📥 Собираю посты..."
    )

    n = await collector.collect_posts(hours_back=25)
    await msg.edit_text(
        f"✅ Добавлен: {info['title']} (@{info['username']})\n"
        f"👥 Подписчиков: {info['members_count']:,}\n"
        f"📥 Собрано новых постов: {n}"
    )


@owner_only
async def cmd_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("ℹ️ Использование: /remove @channel")
        return

    username = context.args[0].lstrip("@")
    if not await database.channel_exists(username):
        await update.message.reply_text("❌ Канал не найден в списке")
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Да", callback_data=f"rmch_yes_{username}"),
            InlineKeyboardButton("❌ Отмена", callback_data=f"rmch_no_{username}"),
        ]
    ])
    await update.message.reply_text(f"⚠️ Удалить @{username}?", reply_markup=keyboard)


async def cb_remove_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if update.effective_user.id != OWNER_ID:
        await query.answer("⛔ Нет доступа", show_alert=True)
        return

    await query.answer()
    data = query.data

    if data.startswith("rmch_no_"):
        await query.edit_message_text("❌ Отменено")
        return

    if data.startswith("rmch_yes_"):
        username = data[len("rmch_yes_"):]
        await database.remove_channel(username)
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Да, удалить", callback_data=f"rmposts_yes_{username}"),
                InlineKeyboardButton("Нет, оставить", callback_data=f"rmposts_no_{username}"),
            ]
        ])
        await query.edit_message_text(
            f"✅ Канал @{username} удалён.\n🗑 Удалить накопленные посты?",
            reply_markup=keyboard,
        )


async def cb_remove_posts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if update.effective_user.id != OWNER_ID:
        await query.answer("⛔ Нет доступа", show_alert=True)
        return

    await query.answer()
    data = query.data

    if data.startswith("rmposts_yes_"):
        username = data[len("rmposts_yes_"):]
        await database.delete_posts_by_channel(username)
        await query.edit_message_text("✅ Посты удалены")
    elif data.startswith("rmposts_no_"):
        await query.edit_message_text("✅ Посты сохранены")


@owner_only
async def cmd_collect(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = await update.message.reply_text("🔄 Собираю посты...")
    n = await collector.collect_posts(hours_back=25)
    await msg.edit_text(f"✅ Готово. Новых постов: {n}")


@owner_only
async def cmd_adduser(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id: int | None = None
    username: str | None = None
    full_name = "Unknown"

    if context.args:
        try:
            user_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("ℹ️ Перешли сообщение от пользователя или укажи /adduser USER_ID")
            return
    elif update.message.forward_origin:
        origin = update.message.forward_origin
        user = getattr(origin, "sender_user", None)
        if user:
            user_id = user.id
            username = user.username
            full_name = user.full_name

    if user_id is None:
        await update.message.reply_text("ℹ️ Перешли сообщение от пользователя или укажи /adduser USER_ID")
        return

    added = await database.add_user(user_id, username, full_name)
    if not added:
        await update.message.reply_text("⚠️ Пользователь уже в списке")
    else:
        await update.message.reply_text(f"✅ Пользователь добавлен: {full_name} (id: {user_id})")


@owner_only
async def cmd_removeuser(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("ℹ️ Использование: /removeuser USER_ID")
        return

    try:
        user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ℹ️ Использование: /removeuser USER_ID")
        return

    if user_id == OWNER_ID:
        await update.message.reply_text("❌ Нельзя удалить владельца")
        return

    removed = await database.remove_user(user_id)
    if not removed:
        await update.message.reply_text("❌ Пользователь не найден")
    else:
        await update.message.reply_text("✅ Пользователь удалён")


@owner_only
async def cmd_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    users = await database.get_active_users()
    if not users:
        await update.message.reply_text("Пользователей нет.")
        return
    lines = [f"👥 Пользователи ({len(users)}):\n"]
    for i, u in enumerate(users, 1):
        uname = f"@{u['username']}" if u["username"] else "без username"
        lines.append(
            f"{i}. {u['full_name']} ({uname}) · id: {u['id']} · с {_fmt_date(u['added_at'])}"
        )
    await update.message.reply_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

async def post_init(application: Application) -> None:
    await database.init_db()

    if TG_API_ID:
        await collector.client.start()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        collector.collect_posts,
        trigger="interval",
        hours=COLLECT_INTERVAL_HOURS,
        kwargs={"hours_back": 7},
        id="collect",
    )
    scheduler.start()
    application.bot_data["scheduler"] = scheduler

    asyncio.create_task(collector.collect_posts(hours_back=168))


async def post_shutdown(application: Application) -> None:
    scheduler: AsyncIOScheduler = application.bot_data.get("scheduler")
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
    if TG_API_ID:
        await collector.client.disconnect()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # User commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("digest", cmd_digest))
    app.add_handler(CommandHandler("channels", cmd_channels))
    app.add_handler(CommandHandler("status", cmd_status))

    # Owner commands
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("remove", cmd_remove))
    app.add_handler(CommandHandler("collect", cmd_collect))
    app.add_handler(CommandHandler("adduser", cmd_adduser))
    app.add_handler(CommandHandler("removeuser", cmd_removeuser))
    app.add_handler(CommandHandler("users", cmd_users))

    # Callbacks
    app.add_handler(CallbackQueryHandler(cb_digest, pattern=r"^digest_(24h|7d)$"))
    app.add_handler(CallbackQueryHandler(cb_remove_channel, pattern=r"^rmch_(yes|no)_.+$"))
    app.add_handler(CallbackQueryHandler(cb_remove_posts, pattern=r"^rmposts_(yes|no)_.+$"))

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
