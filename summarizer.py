import asyncio
import logging
from collections import defaultdict

import anthropic
from duckduckgo_search import DDGS

from config import ANTHROPIC_API_KEY, POST_MAX_CHARS, DIGEST_MAX_POSTS

logger = logging.getLogger(__name__)

_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


async def generate_digest(posts: list[dict], period_label: str) -> str:
    if not posts:
        return "📭 Постов за этот период нет"

    # Предпочитаем свежие посты — сортируем по убыванию и берём первые DIGEST_MAX_POSTS
    sorted_posts = sorted(posts, key=lambda p: p["timestamp"], reverse=True)
    selected = sorted_posts[:DIGEST_MAX_POSTS]

    # Группируем по каналу, сохраняем URL каждого поста
    by_channel: dict[str, list[str]] = defaultdict(list)
    for post in selected:
        text = (post["text"] or "").strip()
        if len(text) > POST_MAX_CHARS:
            text = text[:POST_MAX_CHARS] + "…"
        url = f"https://t.me/{post['channel_username']}/{post['message_id']}"
        by_channel[post["channel_username"]].append(f"[{url}]\n{text}")

    # Собираем текст для промпта
    blocks: list[str] = []
    for channel, entries in by_channel.items():
        block = f"=== @{channel} ===\n" + "\n---\n".join(entries)
        blocks.append(block)
    posts_text = "\n\n".join(blocks)

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
        message = await asyncio.to_thread(
            _client.messages.create,
            model="claude-haiku-4-5-20251001",
            max_tokens=4000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return message.content[0].text
    except Exception as e:
        logger.error("Claude API error: %s", e)
        return f"❌ Ошибка при генерации дайджеста: {e}"


async def answer_question(posts: list[dict], question: str) -> str:
    if not posts:
        return "📭 Постов за этот период нет."

    sorted_posts = sorted(posts, key=lambda p: p["timestamp"], reverse=True)
    selected = sorted_posts[:DIGEST_MAX_POSTS]

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
    posts_text = "\n\n".join(blocks)

    system_prompt = (
        "Ты — умный ассистент. Отвечай только на русском языке. "
        "Отвечай развёрнуто и по существу, используя:\n"
        "1. Посты из Telegram-каналов (приведены ниже) — ссылайся на них как [источник](url)\n"
        "2. Свои собственные знания — если вопрос выходит за рамки постов, отвечай из общих знаний\n"
        "3. Результаты веб-поиска (если приведены) — для актуальной информации\n"
        "Чётко разделяй: что из постов, что из своих знаний, что из поиска."
    )

    # Веб-поиск для свежей информации
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

    user_prompt = f"Вопрос: {question}\n\nПОСТЫ ИЗ КАНАЛОВ:\n{posts_text}{search_text}"

    try:
        message = await asyncio.to_thread(
            _client.messages.create,
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return message.content[0].text
    except Exception as e:
        logger.error("Claude API error: %s", e)
        return f"❌ Ошибка: {e}"
