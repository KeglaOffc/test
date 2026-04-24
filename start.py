"""Точка входа Telegram казино-бота."""
import asyncio
import atexit
import logging
import os
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

current_dir = Path(__file__).parent.absolute()
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

file_handler = logging.FileHandler("bot.log", encoding="utf-8")
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(
    logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.WARNING)
console_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))

network_handler = logging.FileHandler("network_errors.log", encoding="utf-8")
network_handler.setLevel(logging.WARNING)
network_handler.setFormatter(
    logging.Formatter("%(asctime)s - NETWORK ERROR - %(message)s")
)

network_logger = logging.getLogger("network")
network_logger.addHandler(network_handler)
network_logger.setLevel(logging.WARNING)

logging.basicConfig(level=logging.INFO, handlers=[file_handler, console_handler])
logger = logging.getLogger(__name__)

from database import (  # noqa: E402
    apply_migrations,
    clear_daily_stats,
    init_tables,
)
from Handlers import (  # noqa: E402
    admin,
    clans,
    common,
    crash,
    dicedarts,
    events,
    futandbask,
    lottery,
    mines,
    mining,
    monetka,
    pvp,
    qtop,
    referrals,
    roulette,
    sunduk,
    wheel,
)
from Handlers.logging_middleware import LoggingMiddleware  # noqa: E402
from Handlers.maintenance import MaintenanceMiddleware  # noqa: E402
from Handlers.throttling import flood_middleware  # noqa: E402

try:
    init_tables()
    apply_migrations()
    logger.info("База данных инициализирована")
except Exception as e:  # pragma: no cover - defensive
    logger.error("Ошибка инициализации БД: %s", e)

API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not API_TOKEN:
    logger.critical(
        "Переменная окружения TELEGRAM_BOT_TOKEN не задана. "
        "Скопируйте .env.example в .env и укажите токен."
    )
    sys.exit(1)

ROUTERS = [
    mines.router,
    admin.router,
    common.router,
    qtop.router,
    monetka.router,
    sunduk.router,
    dicedarts.router,
    futandbask.router,
    lottery.router,
    mining.router,
    pvp.router,
    crash.router,
    roulette.router,
    wheel.router,
    events.router,
    clans.router,
    referrals.router,
]


from Handlers.lottery import hourly_loop, weekly_loop  # noqa: E402


async def main() -> None:
    """Основная функция: инициализирует бота и запускает polling."""
    logger.info("Запуск казино-бота")

    proxy_url = os.getenv("PROXY_URL")
    if proxy_url:
        logger.info("Используется прокси: %s", proxy_url)

    bot = Bot(token=API_TOKEN)
    dp = Dispatcher()

    dp.message.outer_middleware(LoggingMiddleware())
    dp.callback_query.outer_middleware(LoggingMiddleware())
    dp.message.outer_middleware(MaintenanceMiddleware())
    dp.callback_query.outer_middleware(MaintenanceMiddleware())
    dp.message.outer_middleware(flood_middleware())
    dp.callback_query.outer_middleware(flood_middleware())

    for router in ROUTERS:
        dp.include_router(router)
        logger.debug("Роутер %s зарегистрирован", router.name)

    @dp.error()
    async def error_handler(error):
        logger.error("Глобальная ошибка: %s", error)
        if "Cannot connect to host" in str(error) or "timeout" in str(error).lower():
            logger.warning("Сетевая ошибка, aiogram повторит автоматически")
        return True

    try:
        clear_daily_stats()
    except Exception as e:
        logger.warning("Не удалось очистить дневную статистику: %s", e)

    await bot.set_my_commands(
        [
            BotCommand(command="start", description="📱 Мой профиль"),
            BotCommand(command="games", description="🎮 Список игр"),
            BotCommand(command="top", description="🏆 Рейтинг"),
            BotCommand(command="help", description="❓ Помощь и команды"),
        ]
    )

    logger.info("Бот готов к работе")

    asyncio.create_task(hourly_loop(bot))
    asyncio.create_task(weekly_loop(bot))
    logger.info("Фоновые задачи лотерей запущены")

    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.critical("Критическая ошибка polling: %s", e, exc_info=True)
        raise
    finally:
        logger.info("Бот остановлен")


def cleanup_pid_file() -> None:
    """Удаляет файл PID при завершении работы."""
    try:
        if os.path.exists("bot.pid"):
            os.remove("bot.pid")
    except Exception as e:
        logger.warning("Не удалось удалить файл PID: %s", e)


if __name__ == "__main__":
    try:
        pid = os.getpid()
        with open("bot.pid", "w") as f:
            f.write(str(pid))
        logger.info("Процесс бота запущен с PID: %s", pid)

        atexit.register(cleanup_pid_file)

        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот прерван пользователем (Ctrl+C)")
    except Exception as e:
        logger.critical("Критическая ошибка при запуске: %s", e, exc_info=True)
        sys.exit(1)
