"""Точка входа Telegram казино-бота."""
import asyncio
import atexit
import datetime
import logging
import os
import random
import sys
import time
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
    conn,
    cursor,
    db_update_stats,
    init_tables,
)
from Handlers import (  # noqa: E402
    admin,
    common,
    crash,
    dicedarts,
    futandbask,
    lottery,
    mines,
    mining,
    monetka,
    pvp,
    qtop,
    sunduk,
)
from Handlers.logging_middleware import LoggingMiddleware  # noqa: E402
from Handlers.maintenance import MaintenanceMiddleware  # noqa: E402
from Handlers.throttling import flood_middleware  # noqa: E402
from utils import safe_send_message  # noqa: E402

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
]


async def hourly_draw_task(bot: Bot) -> None:
    """Фоновая задача часовой лотереи.

    Последовательность:
        1. За 5 минут до часа — уведомление участникам.
        2. За 1 минуту — финальный отсчёт.
        3. Ровно на начало часа — розыгрыш.
    """
    logger.info("Часовая лотерея запущена")

    while True:
        try:
            now = datetime.datetime.now()
            next_hour = (now + datetime.timedelta(hours=1)).replace(
                minute=0, second=0, microsecond=0
            )

            warning_time = next_hour - datetime.timedelta(minutes=5)
            wait_for_warning = (warning_time - datetime.datetime.now()).total_seconds()
            if wait_for_warning > 0:
                await asyncio.sleep(wait_for_warning)
                await notify_lottery_participants(
                    bot,
                    "⏰ **До розыгрыша Часовой лотереи осталось 5 минут!**\n"
                    "Успей купить ещё билеты, чтобы повысить шансы.",
                )

            final_call_time = next_hour - datetime.timedelta(minutes=1)
            wait_for_final = (final_call_time - datetime.datetime.now()).total_seconds()
            if wait_for_final > 0:
                await asyncio.sleep(wait_for_final)
                try:
                    await notify_lottery_participants(
                        bot,
                        "🔔 **ВНИМАНИЕ!** Розыгрыш начнётся через 60 секунд! 🤞",
                    )
                except Exception as e:
                    logger.warning("Не удалось отправить уведомление: %s", e)

            wait_for_draw = (next_hour - datetime.datetime.now()).total_seconds()
            if wait_for_draw > 0:
                await asyncio.sleep(wait_for_draw)

            await process_hourly_draw(bot)

        except Exception as e:
            logger.error("Ошибка в часовой лотерее: %s", e, exc_info=True)
            await asyncio.sleep(60)


async def notify_lottery_participants(bot: Bot, message_text: str) -> None:
    """Рассылает сообщение всем участникам текущего тиража часовой лотереи."""
    try:
        cursor.execute(
            "SELECT DISTINCT user_id FROM lottery_tickets "
            "WHERE lottery_type = 'hourly' AND buy_time > ?",
            (int(time.time()) - 3600,),
        )
        participants = [r[0] for r in cursor.fetchall()]
        for uid in participants:
            ok = await safe_send_message(
                bot, uid, message_text, parse_mode="Markdown", max_retries=2
            )
            if not ok:
                logger.warning("Не удалось уведомить пользователя %s", uid)
    except Exception as e:
        logger.error("Ошибка при рассылке уведомлений: %s", e)


async def process_hourly_draw(bot: Bot) -> None:
    """Проводит розыгрыш часовой лотереи."""
    try:
        cursor.execute(
            "SELECT draw_id, prize_pool FROM hourly_state ORDER BY draw_id DESC LIMIT 1"
        )
        res = cursor.fetchone()
        if not res:
            logger.warning("Информация о тираже не найдена")
            return

        draw_id, prize = res

        cursor.execute(
            "SELECT user_id, COUNT(*) AS tix FROM lottery_tickets "
            "WHERE lottery_type = 'hourly' AND buy_time > ? "
            "GROUP BY user_id ORDER BY tix DESC",
            (int(time.time()) - 3600,),
        )
        rows = cursor.fetchall()

        if not rows:
            cursor.execute("INSERT INTO hourly_state (prize_pool) VALUES (?)", (prize,))
            conn.commit()
            logger.info("Тираж #%s пуст. Приз %s перенесён", draw_id, prize)
            return

        pool_for_random = []
        for uid, tix in rows:
            pool_for_random.extend([uid] * tix)
        winner_id = random.choice(pool_for_random)

        db_update_stats(winner_id, bet=0, win=prize)

        lines = [f"🎰 **ИТОГИ РОЗЫГРЫША #{draw_id}**", "", "👤 **Участники и билеты:**"]
        for i, (uid, tix) in enumerate(rows, 1):
            mark = "🏆" if uid == winner_id else "🔹"
            lines.append(f"{i}. {mark} ID: `{uid}` — {tix} шт.")
        lines.append("")
        lines.append(f"💰 **Общий приз:** `{prize:,}` 💎")
        lines.append(f"👑 **Победитель:** `{winner_id}`")
        result_text = "\n".join(lines)

        for uid, _ in rows:
            ok = await safe_send_message(
                bot, uid, result_text, parse_mode="Markdown", max_retries=2
            )
            if not ok:
                logger.warning("Не удалось отправить результат пользователю %s", uid)

        cursor.execute("INSERT INTO hourly_state (prize_pool) VALUES (100000)")
        conn.commit()
        logger.info("Розыгрыш #%s завершён. Победитель: %s", draw_id, winner_id)

    except Exception as e:
        logger.error("Ошибка при проведении розыгрыша: %s", e, exc_info=True)


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

    asyncio.create_task(hourly_draw_task(bot))
    logger.info("Фоновая задача часовой лотереи запущена")

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
