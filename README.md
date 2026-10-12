# Telegram Digest Bot

Бот для небольшой группы доверенных пользователей. Читает посты из Telegram-каналов от имени пользователя (через Telethon), хранит их в SQLite и по команде `/digest` генерирует структурированный дайджест с рубриками через LLM (основной — Ollama `deepseek-v4.1-flash:cloud`, резервный — Gemini API).

## Возможности

- Автоматический сбор постов из каналов каждые 6 часов
- Генерация дайджеста за сутки или за неделю
- Группировка по тематическим рубрикам (AI, Финансы, Политика и др.)
- Управление каналами и пользователями через команды бота
- Доступ только для доверенных пользователей из белого списка

## Стек

- Python 3.11+, asyncio
- [Telethon](https://github.com/LonamiWebs/Telethon) — чтение каналов от имени пользователя
- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) — Bot API
- [Ollama](https://ollama.com) (`deepseek-v4.1-flash:cloud`, configurable via `OLLAMA_MODEL`) — генерация дайджестов, основной провайдер
- [Gemini API](https://ai.google.dev) (google-genai SDK, configurable via `GEMINI_MODEL`, free tier) — резервный провайдер
- SQLite + aiosqlite — хранение постов
- APScheduler — периодический сбор

## Установка

```bash
git clone https://github.com/stasiundra/news_summary_tg_bot.git
cd news_summary_tg_bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Настройка

Создай файл `.env`:

```env
BOT_TOKEN=        # токен бота от @BotFather
TG_API_ID=        # с my.telegram.org
TG_API_HASH=      # с my.telegram.org
OWNER_ID=         # твой Telegram user_id

LLM_PROVIDER=ollama             # основной провайдер: ollama | gemini
LLM_FALLBACK_PROVIDERS=gemini   # резерв (через запятую), пусто — без резерва
OLLAMA_BASE_URL=http://127.0.0.1:11434   # или https://ollama.com для облака
OLLAMA_API_KEY=                 # только для https://ollama.com
OLLAMA_MODEL=deepseek-v4.1-flash:cloud
OLLAMA_THINK=false              # не показывать reasoning thinking-моделей

GEMINI_API_KEY=     # с aistudio.google.com/apikey (для резервного провайдера)
```

Модель Ollama должна быть доступна аккаунту заранее: `ollama pull deepseek-v4.1-flash:cloud`
(облачные модели запускаются на ollama.com, локально качается только манифест).

### Выбор модели (LLM backend)

- `LLM_PROVIDER` — основной провайдер, `LLM_FALLBACK_PROVIDERS` — список резервных через запятую.
- Если основной провайдер отвечает ошибкой (например, Gemini 503 «high demand») до первого куска
  текста, бот автоматически переключается на резервный; если ошибка пришла в середине ответа —
  дописывает пометку о прерывании, не склеивая два ответа.
- Оба провайдера стримят ответ одинаково, поэтому команды и веб-панель менять не нужно.

## Запуск

```bash
python bot.py
```

При первом запуске Telethon запросит номер телефона и код из Telegram. После этого создаётся файл `user_session.session` — повторная авторизация не нужна.

## Команды

### Для всех пользователей

| Команда | Описание |
|---------|----------|
| `/start` | Приветствие и список команд |
| `/digest` | Получить дайджест (за сутки или неделю) |
| `/channels` | Список отслеживаемых каналов |
| `/status` | Статистика: каналы, посты, время следующего сбора |

### Только для владельца

| Команда | Описание |
|---------|----------|
| `/add @channel` | Добавить канал |
| `/remove @channel` | Удалить канал |
| `/collect` | Запустить сбор постов вручную |
| `/adduser USER_ID` | Добавить пользователя (или переслать его сообщение) |
| `/removeuser USER_ID` | Удалить пользователя |
| `/users` | Список пользователей |

## Структура проекта

```
├── bot.py           # точка входа, команды и callback-хендлеры
├── collector.py     # Telethon: валидация каналов, сбор постов
├── summarizer.py    # LLM: генерация дайджеста (провайдеры ollama/gemini)
├── database.py      # работа с SQLite
├── config.py        # загрузка .env и константы
└── requirements.txt
```

## Деплой на сервер (systemd)

```bash
# Скопировать .env на сервер
scp .env user@server:/opt/digest_bot/.env

# Создать сервис
cat > /etc/systemd/system/digest_bot.service << EOF
[Unit]
Description=Telegram Digest Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/digest_bot
ExecStart=/opt/digest_bot/venv/bin/python bot.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now digest_bot
```
