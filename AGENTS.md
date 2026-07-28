# AGENTS.md — news_summary_tg_bot

## Назначение

Telegram-дайджест-бот для небольшой группы доверенных пользователей. Читает посты из
Telegram-каналов от имени пользователя (через Telethon), хранит их в SQLite и по команде
`/digest` генерирует структурированный дайджест с рубриками через Claude API.

**Репозиторий public.** Доступ — только для доверенных пользователей из whitelist (OWNER_ID).

## Стек

- Python 3.11+, asyncio
- [Telethon](https://github.com/LonamiWebs/Telethon) — чтение каналов от имени пользователя
- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) — Bot API
- [Claude API](https://anthropic.com) (anthropic SDK) — генерация дайджестов
- SQLite + aiosqlite — хранение постов
- APScheduler — периодический сбор (каждые 6 часов)
- FastAPI + uvicorn + Jinja2 — веб-панель (`web.py`)
- duckduckgo-search — веб-поиск для дополнения контекста

## Команды

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

python bot.py       # бот + scheduler сбора постов
python web.py       # веб-панель дайджестов
```

## Переменные окружения (`.env`)

- `BOT_TOKEN` — токен бота от @BotFather
- `TG_API_ID` / `TG_API_HASH` — API-ключи Telegram user-аккаунта (для Telethon)
- `ANTHROPIC_API_KEY` — ключ Claude API
- `OWNER_ID` — Telegram ID владельца (whitelist-гейт)

## Архитектура

| Файл | Назначение |
|---|---|
| `bot.py` | python-telegram-bot: команды `/digest`, `/ask`, управление каналами/пользователями, whitelist-гейт |
| `collector.py` | Telethon: чтение каналов, APScheduler (сбор каждые `COLLECT_INTERVAL_HOURS`=6ч), параллельный сбор, streaming, caching, dedup |
| `summarizer.py` | Claude API: генерация рубрикованного дайджеста (AI, Финансы, Политика и др.) за сутки/неделю |
| `database.py` | aiosqlite: хранение постов в `digest.db` |
| `config.py` | Конфиг из `.env` (BOT_TOKEN, TG_API_ID/HASH, ANTHROPIC_API_KEY, OWNER_ID, интервал сбора, лимиты постов) |
| `web.py` | FastAPI веб-панель дайджестов |
| `templates/` | Jinja2-шаблоны веб-панели |

## Возможности

- Автоматический сбор постов из каналов каждые 6 часов
- Генерация дайджеста за сутки или за неделю
- Группировка по тематическим рубрикам (AI, Финансы, Политика и др.)
- Управление каналами и пользователями через команды бота
- Доступ только для доверенных пользователей из whitelist
- `/ask` — вопросы без генерации дайджеста

## Правила кодинга

- Type Hints обязательно. asyncio throughout.
- Конфиг — только через `config.py` из `.env`, не хардкодить токены/ключи.
- Whitelist (OWNER_ID + список доверенных) — не обходить; новые пользователи только через владельца.
- Telethon-сессия (`user_session`) — от имени user-аккаунта, не бота; `.session`-файл не коммитить.
- Новые каналы/рубрики — через команды бота, не через код.
- Conventional Commits (`feat:`, `fix:`, `refactor:`, `perf:`, `docs:`).