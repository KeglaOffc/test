# 🎰 Telegram Casino Bot

Telegram-бот казино на Python (aiogram 3) с несколькими играми, лотереями и рейтингом.

## 🎮 Игры

| Команда | Описание |
| --- | --- |
| `/mines` | Сапёр: открывай клетки, избегай бомб |
| `/flip` | Монетка (орёл/решка), режимы x1.9 и x5 |
| `/slot` | Слоты |
| `/dice`, `/darts` | Кости и дартс против бота |
| `/football`, `/basket` | Спортивные мини-игры |
| `/chests` | Сундуки удачи |
| `/crash` | Крэш (полёт множителя) |
| `/lottery` | Часовая, недельная, МЕГА и пользовательские лотереи |
| `/mining` | Симулятор криптомайнинга |
| `/pvp` | Дуэли между игроками |
| `/top` | Рейтинг богачей и лидеров дня |
| `/shop` | Магазин бустов и предметов |
| `/bonus` | Ежедневный бонус |

## 📋 Требования

- Python 3.9+
- Telegram Bot Token от [@BotFather](https://t.me/BotFather)

## 🚀 Запуск

```bash
git clone https://github.com/KeglaOffc/test.git
cd test

python -m venv venv
source venv/bin/activate   # Linux/Mac
# venv\Scripts\activate    # Windows

pip install -r requirements.txt

cp .env.example .env
# Отредактируйте .env: укажите TELEGRAM_BOT_TOKEN и ADMIN_ID
python start.py
```

## ⚙️ Переменные окружения

Все настройки читаются из `.env` или переменных окружения:

| Переменная | Описание |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Токен бота (обязательно) |
| `ADMIN_ID` | Telegram ID администратора |
| `PROXY_URL` | Прокси (опционально) |

## 🗄️ Структура проекта

```
.
├── start.py              # Точка входа, aiogram Dispatcher и фоновые задачи
├── database.py           # Слой SQLite: таблицы, миграции, запросы
├── utils.py              # Безопасная отправка сообщений
├── Handlers/
│   ├── admin.py          # Админ-панель и команды
│   ├── common.py         # Профиль, магазин, бонусы
│   ├── mines.py, monetka.py, ...
│   ├── lottery.py        # Системные и пользовательские лотереи
│   ├── mining.py, pvp.py, crash.py
│   ├── throttling.py     # Антифлуд
│   ├── maintenance.py    # Режим тех. работ
│   └── logging_middleware.py
├── requirements.txt
├── .env.example
└── README.md
```

## 🛡️ Админ-панель

Команда `/admin` в личке с ботом открывает интерактивную панель с разделами:

- 💰 Управление балансом (`/setbal`, `/addbal`, `/subbal`, `/reset_money`)
- 🚫 Блокировки (`/ban`, `/getbans`, `/deluser`)
- 🔍 Информация (`/info`, `/show_mines`, `/allplayers`)
- ⭐ Выдача предметов (`/additem`)
- ⛏️ Управление майнингом (`/mine_add`, `/mine_set`, `/mine_watt`, `/mine_reset`, `/mine_boost`)
- 📢 Рассылка (`/broadcast`, `/bcgroup`)
- 🔧 Тех. работы (`/maintenance on|off`)

Админом считается пользователь с Telegram ID из `ADMIN_ID`.

## 🪵 Логи

- `bot.log` — основной лог (INFO)
- `network_errors.log` — только сетевые ошибки

## 🤝 Вклад

1. Создайте issue с описанием бага или фичи.
2. Форкните репозиторий и создайте ветку `feature/<название>`.
3. Откройте Pull Request с понятным описанием.
