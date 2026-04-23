"""
Основной модуль Telegram казино-бота.
Улучшения: безопасность (переменные окружения), обработка ошибок, логирование.
"""
import asyncio
import logging
import sys
import os
import datetime
import time
import random
from typing import Optional
from pathlib import Path
import atexit

# Настройка путей
current_dir = Path(__file__).parent.absolute()
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

# Настройка логирования
file_handler = logging.FileHandler('bot.log', encoding='utf-8')
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.WARNING) # В консоль только важные ошибки
console_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))

# Добавляем отдельный логгер для сетевых ошибок
network_handler = logging.FileHandler('network_errors.log', encoding='utf-8')
network_handler.setLevel(logging.WARNING)
network_handler.setFormatter(logging.Formatter('%(asctime)s - NETWORK ERROR - %(message)s'))

network_logger = logging.getLogger('network')
network_logger.addHandler(network_handler)
network_logger.setLevel(logging.WARNING)

logging.basicConfig(
    level=logging.INFO,
    handlers=[file_handler, console_handler]
)
logger = logging.getLogger(__name__)

# Импорт основных модулей
try:
    from aiogram import Bot, Dispatcher
    from aiogram.types import BotCommand
    
    from database import cursor, conn, db_update_stats, clear_daily_stats, apply_migrations, init_tables
    from Handlers import (
        admin, common, dicedarts, mines, monetka, qtop, 
        sunduk, futandbask, lottery, mining, pvp, crash
    )
    from Handlers.throttling import flood_middleware
    from Handlers.maintenance import MaintenanceMiddleware
    from utils import safe_send_message
    from Handlers.logging_middleware import LoggingMiddleware
    logger.info("[OK] Все модули успешно импортированы")
except ImportError as e:
    logger.error(f"[FAILED] Ошибка импорта: {e}")
    sys.exit(1)

# Инициализируем БД
try:
    init_tables()
    apply_migrations()
    logger.info("[OK] База данных инициализирована и миграции применены")
except Exception as e:
    logger.error(f"[FAILED] Ошибка инициализации БД: {e}")

# ============================================================================
# КОНФИГУРАЦИЯ
# ============================================================================

# Используем переменные окружения или значение по умолчанию
API_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8105418718:AAFRMD0iGArAM2RFdo0u9gHwtH2ecu8GEHg')
if not API_TOKEN or API_TOKEN == '8105418718:AAFRMD0iGArAM2RFdo0u9gHwtH2ecu8GEHg':
    logger.warning("[WARNING] Используется токен по умолчанию. Рекомендуется установить переменную окружения TELEGRAM_BOT_TOKEN")

# Роутеры для регистрации
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

# ============================================================================
# ФОНОВЫЕ ЗАДАЧИ
# ============================================================================

async def hourly_draw_task(bot: Bot):
    """
    Фоновая задача часовой лотереи.
    Структура:
    1. За 5 минут до часа - предупреждение
    2. За 1 минуту - финальный отсчет
    3. В начало часа - розыгрыш
    """
    logger.info("[CASINO] Часовая лотерея запущена")
    
    while True:
        try:
            now = datetime.datetime.now()
            next_hour = (now + datetime.timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
            
            # --- ШАГ 1: Уведомление за 5 минут ---
            warning_time = next_hour - datetime.timedelta(minutes=5)
            wait_for_warning = (warning_time - datetime.datetime.now()).total_seconds()
            
            if wait_for_warning > 0:
                await asyncio.sleep(wait_for_warning)
                await notify_lottery_participants(
                    bot, 
                    "[WARNING] **До розыгрыша Часовой Лотереи осталось 5 минут!**\n"
                    "Успей купить еще билеты, чтобы повысить шансы."
                )
            
            # --- ШАГ 2: Финальное предупреждение за 1 минуту ---
            final_call_time = next_hour - datetime.timedelta(minutes=1)
            wait_for_final = (final_call_time - datetime.datetime.now()).total_seconds()
            
            if wait_for_final > 0:
                await asyncio.sleep(wait_for_final)
                try:
                    await notify_lottery_participants(
                        bot,
                        "🔔 **ВНИМАНИЕ!** Розыгрыш начнется через 60 секунд! Скрестите пальцы! 🤞"
                    )
                except Exception as e:
                    logger.warning(f"Failed to send lottery notification: {e}")
                    # Continue even if notification fails
            
            # --- ШАГ 3: Ожидание до розыгрыша ---
            wait_for_draw = (next_hour - datetime.datetime.now()).total_seconds()
            if wait_for_draw > 0:
                await asyncio.sleep(wait_for_draw)
            
            # --- ШАГ 4: Проведение розыгрыша ---
            await process_hourly_draw(bot)
            
        except Exception as e:
            logger.error(f"[FAILED] Ошибка в часовой лотерее: {e}", exc_info=True)
            await asyncio.sleep(60)  # Ждем минуту перед повтором при ошибке


async def notify_lottery_participants(bot: Bot, message_text: str):
    """Отправляет уведомление всем участникам текущего тиража"""
    try:
        cursor.execute(
            "SELECT DISTINCT user_id FROM lottery_tickets "
            "WHERE lottery_type = 'hourly' AND buy_time > ?", 
            (int(time.time()) - 3600,)
        )
        participants = [r[0] for r in cursor.fetchall()]
        
        for uid in participants:
            success = await safe_send_message(bot, uid, message_text, parse_mode="Markdown", max_retries=2)
            if not success:
                logger.warning(f"Failed to send notification to user {uid}")
    except Exception as e:
        logger.error(f"[FAILED] Ошибка при рассылке уведомлений: {e}")


async def process_hourly_draw(bot: Bot):
    """Проводит розыгрыш часовой лотереи"""
    try:
        # Получаем текущий тираж
        cursor.execute("SELECT draw_id, prize_pool FROM hourly_state ORDER BY draw_id DESC LIMIT 1")
        res = cursor.fetchone()
        if not res:
            logger.warning("[WARNING] Информация о тираже не найдена")
            return
        
        draw_id, prize = res
        
        # Собираем участников
        cursor.execute(
            "SELECT user_id, COUNT(*) as tix FROM lottery_tickets "
            "WHERE lottery_type = 'hourly' AND buy_time > ? "
            "GROUP BY user_id ORDER BY tix DESC",
            (int(time.time()) - 3600,)
        )
        rows = cursor.fetchall()
        
        if not rows:
            # Тираж пуст - переносим приз
            cursor.execute("INSERT INTO hourly_state (prize_pool) VALUES (?)", (prize,))
            conn.commit()
            logger.info(f"[STATS] Тираж #{draw_id} пуст. Приз {prize} перенесен на следующий тираж")
            return
        
        # Выбираем победителя (с учетом веса)
        pool_for_random = []
        for uid, tix in rows:
            pool_for_random.extend([uid] * tix)
        
        winner_id = random.choice(pool_for_random)
        
        # Начисляем приз
        db_update_stats(winner_id, bet=0, win=prize)
        
        # Формируем результаты
        result_text = f"[CASINO] **ИТОГИ РОЗЫГРЫША #{draw_id}**\n\n"
        result_text += "👤 **Участники и билеты:**\n"
        
        for i, (uid, tix) in enumerate(rows, 1):
            mark = "🏆" if uid == winner_id else "🔹"
            result_text += f"{i}. {mark} ID: `{uid}` — {tix} шт.\n"
        
        result_text += f"\n[MONEY] **Общий приз:** `{prize:,}` 💎\n"
        result_text += f"👑 **Победитель:** `{winner_id}`"
        
        # Отправляем результаты всем участникам
        for uid, _ in rows:
            success = await safe_send_message(bot, uid, result_text, parse_mode="Markdown", max_retries=2)
            if not success:
                logger.warning(f"Failed to send result to user {uid}")
        
        # Создаем новый тираж
        cursor.execute("INSERT INTO hourly_state (prize_pool) VALUES (100000)")
        conn.commit()
        logger.info(f"[PARTY] Розыгрыш #{draw_id} завершен. Победитель: {winner_id}, Приз: {prize}")
        
    except Exception as e:
        logger.error(f"[FAILED] Ошибка при проведении розыгрыша: {e}", exc_info=True)


# ============================================================================
# ОСНОВНАЯ ФУНКЦИЯ
# ============================================================================

async def main():
    """Основная функция бота"""
    logger.info("=" * 60)
    logger.info("[START] ЗАПУСК КАЗИНО-БОТА")
    logger.info("=" * 60)
    
    try:
        # Инициализируем бота и диспетчер
        # session_timeout = 60 # Используем int для таймаута, чтобы избежать конфликтов с aiogram
        # session_timeout = ClientTimeout(total=None, connect=60, sock_connect=60, sock_read=60)
        
        # Поддержка прокси
        proxy_url = os.getenv('PROXY_URL')
        if proxy_url:
            logger.info(f"[NETWORK] Используется прокси: {proxy_url}")
            # session = AiohttpSession(timeout=ClientTimeout(total=None, connect=60), proxy=proxy_url)
            # Временно отключаем кастомную сессию с прокси, если она вызывает ошибки
            session = None 
            logger.warning("[WARNING] Прокси найден в .env, но временно отключен в коде из-за конфликтов типов!")
        else:
            # session = AiohttpSession(timeout=ClientTimeout(total=None, connect=60))
            session = None
        
        # Убрана кастомная сессия, так как она вызывала конфликт типов (TypeError)
        # Если нужно вернуть таймауты, нужно использовать правильную версию aiogram или не смешивать типы
        if session:
            bot = Bot(token=API_TOKEN, session=session)
        else:
            bot = Bot(token=API_TOKEN) # Используем стандартную сессию по умолчанию
        dp = Dispatcher()
        
        # Регистрируем middleware
        # 1. Логирование (самое первое)
        dp.message.outer_middleware(LoggingMiddleware())
        dp.callback_query.outer_middleware(LoggingMiddleware())

        # 2. Тех. работы
        dp.message.outer_middleware(MaintenanceMiddleware())
        dp.callback_query.outer_middleware(MaintenanceMiddleware())
        
        # 3. Антифлуд
        dp.message.outer_middleware(flood_middleware())
        dp.callback_query.outer_middleware(flood_middleware())
        
        # Регистрируем все роутеры
        for router in ROUTERS:
            dp.include_router(router)
            logger.debug(f"✓ Роутер {router.name} зарегистрирован")
        
        # Добавляем глобальный обработчик ошибок
        @dp.error()
        async def error_handler(error):
            logger.error(f"Global error handler caught: {error}")
            if "Cannot connect to host" in str(error) or "timeout" in str(error).lower():
                logger.warning("Network connectivity issue detected, will retry automatically")
            return True
        
        # Удаляем ожидающие обновления с обработкой ошибок
        try:
            # Убираем drop_pending_updates, так как это требует запроса к API при запуске
            # await bot.delete_webhook(drop_pending_updates=True)
            pass
        except Exception as e:
            logger.warning(f"Failed to delete webhook: {e}")
            # Продолжаем работу даже при ошибке webhook
        
        # Очищаем дневную статистику
        try:
            clear_daily_stats()
        except Exception as e:
            logger.warning(f"[WARNING] Не удалось очистить дневную статистику: {e}")
        
        # Устанавливаем команды бота
        await bot.set_my_commands([
            BotCommand(command="start", description="📱 Мой профиль"),
            BotCommand(command="games", description="🎮 Список игр"),
            BotCommand(command="top", description="🏆 Рейтинг"),
            BotCommand(command="help", description="❓ Помощь и команды"),
        ])
        
        logger.info("[OK] Бот полностью инициализирован и готов к работе")
        
        # Запускаем фоновую задачу розыгрыша
        asyncio.create_task(hourly_draw_task(bot))
        logger.info("[TIME] Фоновая задача часовой лотереи запущена")
        
        # Запускаем polling с обработкой сетевых ошибок
        try:
            await dp.start_polling(bot)
        except Exception as e:
            if 'TelegramNetworkError' in str(type(e)):
                logger.critical(f"[NETWORK] Ошибка сети при polling: {e}")
                logger.info("[INFO] Попробуйте перезапустить бота через несколько минут")
                raise
            else:
                raise
        except Exception as e:
            logger.critical(f"[FAILED] КРИТИЧЕСКАЯ ОШИБКА: {e}", exc_info=True)
            raise
    finally:
        logger.info("🛑 Бот остановлен")


def cleanup_pid_file():
    """Удаляет файл PID при завершении работы"""
    try:
        if os.path.exists('bot.pid'):
            os.remove('bot.pid')
            logger.info("[CLEANUP] Файл PID удален")
    except Exception as e:
        logger.warning(f"[WARNING] Не удалось удалить файл PID: {e}")

if __name__ == "__main__":
    try:
        # Записываем PID в файл для возможности жесткой остановки
        pid = os.getpid()
        with open('bot.pid', 'w') as f:
            f.write(str(pid))
        logger.info(f"[PID] Процесс бота запущен с PID: {pid}")
        
        # Регистрируем функцию очистки при выходе
        atexit.register(cleanup_pid_file)
        
        # Запускаем основную функцию с обработкой сетевых ошибок
        try:
            asyncio.run(main())
        except Exception as e:
            if 'TelegramNetworkError' in str(type(e)):
                 logger.critical(f"[NETWORK] Сетевая ошибка при запуске бота: {e}")
                 logger.info("[INFO] Проверьте подключение к интернету и доступность Telegram API")
                 sys.exit(1)
            else:
                 logger.critical(f"[FAILED] Критическая ошибка при запуске бота: {e}", exc_info=True)
                 sys.exit(1)
            
    except KeyboardInterrupt:
        logger.info("⚙️ Бот прерван пользователем (Ctrl+C)")
    except Exception as e:
        logger.critical(f"[FAILED] Непредвиденная ошибка: {e}", exc_info=True)
        sys.exit(1)
        cleanup_pid_file()
    except Exception as e:
        logger.critical(f"[FAILED] Непредвиденная ошибка: {e}", exc_info=True)
        cleanup_pid_file()
        sys.exit(1)

