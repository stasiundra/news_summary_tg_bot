# AGENTS.md — news_summary_tg_bot

## Назначение

Telegram-дайджест-бот для небольшой группы доверенных пользователей. Читает посты из
Telegram-каналов от имени пользователя (через Telethon), хранит их в SQLite и по команде
`/digest` генерирует структурированный дайджест с рубриками через LLM: основной провайдер —
Ollama (`deepseek-v4.1-flash:cloud`), резервный — Gemini API.

**Репозиторий public.** Доступ — только для доверенных пользователей из whitelist (OWNER_ID).

## Стек

- Python 3.11+, asyncio
- [Telethon](https://github.com/LonamiWebs/Telethon) — чтение каналов от имени пользователя
- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) — Bot API
- [Ollama](https://ollama.com) (облачная модель `deepseek-v4.1-flash:cloud`, локальный демон или ollama.com) — генерация дайджестов, основной провайдер
- [Gemini API](https://ai.google.dev) (google-genai SDK) — резервный провайдер
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
- `LLM_PROVIDER` — основной провайдер: `ollama` (по умолчанию) или `gemini`
- `LLM_FALLBACK_PROVIDERS` — резервные провайдеры через запятую (по умолчанию `gemini`, пусто — без резерва)
- `LLM_TIMEOUT_S` — таймаут одного запроса к LLM (по умолчанию 300)
- `OLLAMA_BASE_URL` — адрес Ollama: локальный демон `http://127.0.0.1:11434` или облако `https://ollama.com`
- `OLLAMA_API_KEY` — ключ ollama.com (нужен только для облачного endpoint'а)
- `OLLAMA_MODEL` — модель Ollama (по умолчанию `deepseek-v4.1-flash:cloud`)
- `OLLAMA_THINK` — `false` прячет reasoning-цепочку thinking-моделей
- `GEMINI_API_KEY` — ключ Google Gemini API (free tier), нужен только для резервного провайдера
- `GEMINI_MODEL` — модель Gemini (по умолчанию `gemini-3.6-flash`)
- `OWNER_ID` — Telegram ID владельца (whitelist-гейт)

## Архитектура

| Файл | Назначение |
|---|---|
| `bot.py` | python-telegram-bot: команды `/digest`, `/ask`, управление каналами/пользователями, whitelist-гейт |
| `collector.py` | Telethon: чтение каналов, APScheduler (сбор каждые `COLLECT_INTERVAL_HOURS`=6ч), параллельный сбор, streaming, caching, dedup |
| `summarizer.py` | LLM: генерация рубрикованного дайджеста (AI, Финансы, Политика и др.) за сутки/неделю; провайдеры — `_PROVIDERS` (ollama, gemini), переключение при сбое в `_stream_llm` |
| `database.py` | aiosqlite: хранение постов в `digest.db` |
| `config.py` | Конфиг из `.env` (BOT_TOKEN, TG_API_ID/HASH, OWNER_ID, провайдер и модель LLM, интервал сбора, лимиты постов) |
| `web.py` | FastAPI веб-панель дайджестов |
| `templates/` | Jinja2-шаблоны веб-панели |

## Возможности

- Автоматический сбор постов из каналов каждые 6 часов
- Генерация дайджеста за сутки или за неделю
- Группировка по тематическим рубрикам (AI, Финансы, Политика и др.)
- Управление каналами и пользователями через команды бота
- Доступ только для доверенных пользователей из whitelist
- `/ask` — вопросы без генерации дайджеста

## Провайдеры LLM

- Провайдеры живут в `summarizer._PROVIDERS` и имеют одинаковую сигнатуру
  `(system_prompt, user_prompt, max_tokens, warn_truncation) -> AsyncGenerator[str, None]`.
  Новый провайдер = функция в этом словаре + значение в `_stream_llm`; `bot.py`/`web.py` не меняются.
- Порядок попыток: `LLM_PROVIDER`, затем `LLM_FALLBACK_PROVIDERS`. Переключение на резерв
  возможно только пока не пришёл ни один кусок текста — иначе ответ склеится из двух моделей.
- Предупреждение «⚠️ Дайджест обрезан…» показывается только для дайджеста (`warn_truncation=True`),
  для `/ask` обрезание только логируется.
- Логи Ollama: `journalctl -u digest_bot -f`. Проверка модели без бота:
  `curl -s http://127.0.0.1:11434/api/chat -d '{"model":"…","messages":[…],"stream":false}'`.

## Правила кодинга

- Type Hints обязательно. asyncio throughout.
- Конфиг — только через `config.py` из `.env`, не хардкодить токены/ключи.
- Whitelist (OWNER_ID + список доверенных) — не обходить; новые пользователи только через владельца.
- Telethon-сессия (`user_session`) — от имени user-аккаунта, не бота; `.session`-файл не коммитить.
- Новые каналы/рубрики — через команды бота, не через код.
- Conventional Commits (`feat:`, `fix:`, `refactor:`, `perf:`, `docs:`).