import asyncio
import json
import logging
import re
from collections import defaultdict
from typing import AsyncGenerator, Callable

import httpx
from duckduckgo_search import DDGS

from config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    LLM_FALLBACK_PROVIDERS,
    LLM_PROVIDER,
    LLM_TIMEOUT_S,
    OLLAMA_API_KEY,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OLLAMA_THINK,
    POST_MAX_CHARS,
    DIGEST_MAX_POSTS,
)

logger = logging.getLogger(__name__)

_gemini_client = None


def _get_gemini_client():
    """Lazy-init Gemini client — allows bot to start without API key."""
    global _gemini_client
    if _gemini_client is None:
        if not GEMINI_API_KEY:
            raise RuntimeError(
                "GEMINI_API_KEY not set — get one at https://aistudio.google.com/apikey"
            )
        from google import genai

        _gemini_client = genai.Client(api_key=GEMINI_API_KEY)
    return _gemini_client


# Активная модель — для логов/статуса. Основной провайдер = LLM_PROVIDER.
MODEL = OLLAMA_MODEL if LLM_PROVIDER == "ollama" else GEMINI_MODEL
DIGEST_MAX_OUTPUT_TOKENS = 8192
ANSWER_MAX_OUTPUT_TOKENS = 1024


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
# Providers — каждый отдаёт AsyncGenerator[str, None] с кусками текста
# ---------------------------------------------------------------------------

async def _stream_ollama(
    system_prompt: str, user_prompt: str, max_tokens: int, warn_truncation: bool = False
) -> AsyncGenerator[str, None]:
    """Stream from an Ollama endpoint (/api/chat): local daemon or ollama.com cloud."""
    url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat"
    headers = {"Content-Type": "application/json"}
    if OLLAMA_API_KEY:
        headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"

    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": True,
        "think": OLLAMA_THINK,
        "options": {"num_predict": max_tokens},
    }

    timeout = httpx.Timeout(LLM_TIMEOUT_S, connect=15.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as response:
            if response.status_code >= 400:
                body = (await response.aread()).decode("utf-8", "replace")
                raise RuntimeError(f"ollama HTTP {response.status_code}: {body[:300]}")

            done_reason: str | None = None
            async for line in response.aiter_lines():
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("ollama: нераспознанная строка потока: %.120s", line)
                    continue

                if event.get("error"):
                    raise RuntimeError(f"ollama: {event['error']}")

                chunk = (event.get("message") or {}).get("content") or ""
                if chunk:
                    yield chunk

                if event.get("done"):
                    done_reason = event.get("done_reason")
                    break

            if warn_truncation and done_reason and done_reason not in ("stop", ""):
                logger.warning("digest truncated: ollama done_reason=%s", done_reason)
                yield "\n\n⚠️ Дайджест обрезан по лимиту длины ответа."


async def _stream_gemini(
    system_prompt: str, user_prompt: str, max_tokens: int, warn_truncation: bool = False
) -> AsyncGenerator[str, None]:
    """Stream from Google Gemini (google-genai SDK)."""
    from google.genai import types

    response = await _get_gemini_client().aio.models.generate_content_stream(
        model=GEMINI_MODEL,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=max_tokens,
        ),
    )
    finish_reason = None
    async for chunk in response:
        if chunk.text:
            yield chunk.text
        if chunk.candidates:
            finish_reason = chunk.candidates[0].finish_reason
    if finish_reason and getattr(finish_reason, "value", str(finish_reason)) not in (
        "STOP",
        "FINISH_REASON_UNSPECIFIED",
    ):
        logger.warning("digest truncated: finish_reason=%s", finish_reason)
        if warn_truncation:
            yield "\n\n⚠️ Дайджест обрезан по лимиту длины ответа."


_PROVIDERS: dict[str, Callable[..., AsyncGenerator[str, None]]] = {
    "ollama": _stream_ollama,
    "gemini": _stream_gemini,
}


def _provider_chain() -> list[str]:
    """Основной провайдер + резервные из LLM_FALLBACK_PROVIDERS (без дублей)."""
    chain = [LLM_PROVIDER]
    for name in LLM_FALLBACK_PROVIDERS.split(","):
        name = name.strip().lower()
        if name and name not in chain:
            chain.append(name)
    return chain


async def _stream_llm(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    error_prefix: str,
    warn_truncation: bool = False,
) -> AsyncGenerator[str, None]:
    """Отдаёт текст от первого работоспособного провайдера, переключаясь при сбое.

    Переключение на резерв возможно только пока не пришло ни одного куска текста —
    иначе пользователь получил бы склейку двух ответов.
    """
    errors: list[str] = []

    for provider in _provider_chain():
        stream_fn = _PROVIDERS.get(provider)
        if stream_fn is None:
            errors.append(f"{provider}: неизвестный провайдер")
            continue

        produced = False
        try:
            async for chunk in stream_fn(
                system_prompt, user_prompt, max_tokens, warn_truncation
            ):
                produced = True
                yield chunk
        except Exception as exc:
            logger.error("%s streaming error: %s", provider, exc)
            errors.append(f"{provider}: {exc}")
            if produced:
                yield f"\n\n⚠️ Провайдер {provider} прервал ответ: {exc}"
                return
            continue

        if produced:
            return
        logger.error("%s вернул пустой ответ", provider)
        errors.append(f"{provider}: пустой ответ")

    yield f"{error_prefix}: " + "; ".join(errors)


# ---------------------------------------------------------------------------
# Digest — streaming variant (for Telegram bot)
# ---------------------------------------------------------------------------

async def generate_digest_stream(
    posts: list[dict], period_label: str
) -> AsyncGenerator[str, None]:
    """Yield digest text chunks from the configured LLM as they arrive."""
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

    async for chunk in _stream_llm(
        system_prompt,
        user_prompt,
        DIGEST_MAX_OUTPUT_TOKENS,
        error_prefix="❌ Ошибка при генерации дайджеста",
        warn_truncation=True,
    ):
        yield chunk


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
    """Yield answer chunks from the configured LLM as they arrive."""
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

    async for chunk in _stream_llm(
        system_prompt,
        user_prompt,
        ANSWER_MAX_OUTPUT_TOKENS,
        error_prefix="❌ Ошибка",
    ):
        yield chunk


# ---------------------------------------------------------------------------
# Question answering — non-streaming variant (for web interface)
# ---------------------------------------------------------------------------

async def answer_question(posts: list[dict], question: str) -> str:
    """Collect full answer text (used by web.py)."""
    chunks: list[str] = []
    async for chunk in answer_question_stream(posts, question):
        chunks.append(chunk)
    return "".join(chunks)
