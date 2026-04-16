import asyncio
import logging
import re
from collections import defaultdict
from typing import AsyncGenerator

import anthropic
from duckduckgo_search import DDGS

from config import ANTHROPIC_API_KEY, POST_MAX_CHARS, DIGEST_MAX_POSTS

logger = logging.getLogger(__name__)

# Async client — no asyncio.to_thread needed
_client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

MODEL = "claude-haiku-4-5-20251001"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _deduplicate_posts(posts: list[dict]) -> list[dict]:
    """Remove near-duplicate posts (same first 80 chars after normalisation)."""
    seen: set[str] = set()
    unique: list[dict] = []
    for post in posts:
        text = (post["text"] or "").strip()
        fingerprint = re.sub(r"\s+", " ", text.lower())[:80]
        if fingerprint not in seen:
            seen.add(fingerprint)
            unique.append(post)
    return unique


def _build_posts_text(posts: list[dict]) -> str:
    """Sort, deduplicate, truncate and format posts into a prompt block."""
    sorted_posts = sorted(posts, key=lambda p: p["timestamp"], reverse=True)
    selected = _deduplicate_posts(sorted_posts[:DIGEST_MAX_POSTS])

    by_channel: dict[str, list[str]] = defaultdict(list)
    for post in selected:
        text = (post["text"] or "").strip()
        if len(text) > POST_MAX_CHARS:
            text = text[:POST_MAX_CHARS] + "…"
        url = f"https://t.me/{post['channel_username']}/{post['message_id']}"
        by_channel[post["channel_username"]].append(f"[{url}]\n{text}")

    blocks = [
        f"=== @{ch} ===\n" + "\n---\n".join(entries)
        for ch, entries in by_channel.items()
    ]
    return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# Digest — streaming variant (for Telegram bot)
# ---------------------------------------------------------------------------

async def generate_digest_stream(
    posts: list[dict], period_label: str
) -> AsyncGenerator[str, None]:
    """Yield text chunks from Claude as they arrive."""
    if not posts:
        yield "📭 Постов за этот период нет"
        return

    posts_text = _build_posts_text(posts)

    system_prompt = (
        "Ты — ассистент для создания дайджестов Telegram-каналов.\n"
        "Отвечай только на русском языке. Будь кратким и конкретным."
    )
    user_prompt = (
        f"Создай структурированный дайджест постов за {period_label}.\n\n"
        f"1. Начни с блока \"🔥 Главное за {period_label}\": топ-5 важнейших событий,\n"
        "   каждое — одно предложение + ссылка на пост в формате [источник](url)\n\n"
        "2. Затем рубрики по содержанию\n"
        "   (примеры: 🤖 AI, 💰 Финансы, 🌍 Политика, 📱 Технологии, 💼 Бизнес, 🔬 Наука)\n"
        "   По каждой рубрике: 2-4 предложения саммари + ключевые факты списком со ссылками\n\n"
        "Каждый пост в данных снабжён ссылкой в формате [https://t.me/...] перед текстом — "
        "используй эти ссылки при упоминании конкретных фактов и событий.\n\n"
        f"ПОСТЫ:\n{posts_text}"
    )

    try:
        async with _client.messages.stream(
            model=MODEL,
            max_tokens=4000,
            system=[{
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user_prompt}],
        ) as stream:
            async for text in stream.text_stream:
                yield text
    except Exception as e:
        logger.error("Claude API streaming error: %s", e)
        yield f"❌ Ошибка при генерации дайджеста: {e}"


# ---------------------------------------------------------------------------
# Digest — non-streaming variant (for web interface)
# ---------------------------------------------------------------------------

async def generate_digest(posts: list[dict], period_label: str) -> str:
    """Collect full digest text (used by web.py)."""
    if not posts:
        return "📭 Постов за этот период нет"

    chunks: list[str] = []
    async for chunk in generate_digest_stream(posts, period_label):
        chunks.append(chunk)
    return "".join(chunks)


# ---------------------------------------------------------------------------
# Question answering — streaming variant (for Telegram bot)
# ---------------------------------------------------------------------------

async def answer_question_stream(
    posts: list[dict], question: str
) -> AsyncGenerator[str, None]:
    """Yield answer chunks from Claude as they arrive."""
    if not posts:
        yield "📭 Постов за этот период нет."
        return

    posts_text = _build_posts_text(posts)

    system_prompt = (
        "Ты — умный ассистент. Отвечай только на русском языке. "
        "Отвечай развёрнуто и по существу, используя:\n"
        "1. Посты из Telegram-каналов (приведены ниже) — ссылайся на них как [источник](url)\n"
        "2. Свои собственные знания — если вопрос выходит за рамки постов, отвечай из общих знаний\n"
        "3. Результаты веб-поиска (если приведены) — для актуальной информации\n"
        "Чётко разделяй: что из постов, что из своих знаний, что из поиска."
    )

    # Web search runs concurrently while we prepare the prompt
    search_text = ""
    try:
        results = await asyncio.to_thread(
            lambda: list(DDGS().text(question, max_results=5))
        )
        if results:
            snippets = [f"- {r['title']}: {r['body']}" for r in results]
            search_text = "\n\nРЕЗУЛЬТАТЫ ВЕБ-ПОИСКА:\n" + "\n".join(snippets)
    except Exception as e:
        logger.warning("Web search failed: %s", e)

    user_prompt = (
        f"Вопрос: {question}\n\nПОСТЫ ИЗ КАНАЛОВ:\n{posts_text}{search_text}"
    )

    try:
        async with _client.messages.stream(
            model=MODEL,
            max_tokens=1000,
            system=[{
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user_prompt}],
        ) as stream:
            async for text in stream.text_stream:
                yield text
    except Exception as e:
        logger.error("Claude API streaming error: %s", e)
        yield f"❌ Ошибка: {e}"


# ---------------------------------------------------------------------------
# Question answering — non-streaming variant (for web interface)
# ---------------------------------------------------------------------------

async def answer_question(posts: list[dict], question: str) -> str:
    """Collect full answer text (used by web.py)."""
    chunks: list[str] = []
    async for chunk in answer_question_stream(posts, question):
        chunks.append(chunk)
    return "".join(chunks)
