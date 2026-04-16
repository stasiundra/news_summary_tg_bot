# Telegram Digest Bot

Бот для небольшой группы доверенных пользователей. Читает посты из Telegram-каналов от имени пользователя (через Telethon), хранит их в SQLite и по команде `/digest` генерирует структурированный дайджест с рубриками через Claude API.

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
- [Claude API](https://anthropic.com) (claude-opus-4-5) — генерация дайджестов
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
ANTHROPIC_API_KEY= # с console.anthropic.com
OWNER_ID=         # твой Telegram user_id
```

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
├── summarizer.py    # Claude API: генерация дайджеста
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
