import asyncio
import logging
import sys
import os
import datetime
import time
import random

# ПРИНУДИТЕЛЬНАЯ НАСТРОЙКА ПУТЕЙ
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

# Пробуем импортировать базу и папки
try:
    from database import cursor, conn, db_update_stats
    from Handlers import admin, common, dicedarts, mines, monetka, qtop, sunduk, futandbask, lottery ,mining
    from Handlers.throttling import flood_middleware
except ImportError as e:
    print(f"❌ Ошибка импорта: {e}")
    sys.exit(1)

API_TOKEN = '8105418718:AAFRMD0iGArAM2RFdo0u9gHwtH2ecu8GEHg'

# --- ФОНОВАЯ ЗАДАЧА РОЗЫГРЫША ---
async def hourly_draw_task(bot: Bot):
    while True:
        now = datetime.datetime.now()
        # Считаем время до начала следующего часа
        next_hour = (now + datetime.timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        
        # 1. Ждем до момента "за 5 минут до конца"
        warning_time = next_hour - datetime.timedelta(minutes=5)
        wait_for_warning = (warning_time - datetime.datetime.now()).total_seconds()
        
        if wait_for_warning > 0:
            await asyncio.sleep(wait_for_warning)
            
            # Рассылаем уведомление тем, кто участвует
            cursor.execute("SELECT DISTINCT user_id FROM lottery_tickets WHERE lottery_type = 'hourly' AND buy_time > ?", 
                           (int(time.time()) - 3600,))
            participants = [r[0] for r in cursor.fetchall()]
            for uid in participants:
                try:
                    await bot.send_message(uid, "⚠️ **До розыгрыша Часовой Лотереи осталось 5 минут!**\nУспей купить еще билеты, чтобы повысить шансы.")
                except: continue

        # 2. ОПОВЕЩЕНИЕ ЗА 1 МИНУТУ (Финальный отсчет)
        final_call_time = next_hour - datetime.timedelta(minutes=1)
        wait_for_final = (final_call_time - datetime.datetime.now()).total_seconds()
        
        if wait_for_final > 0:
            await asyncio.sleep(wait_for_final)
            cursor.execute("SELECT DISTINCT user_id FROM lottery_tickets WHERE lottery_type = 'hourly' AND buy_time > ?", 
                           (int(time.time()) - 3600,))
            participants = [r[0] for r in cursor.fetchall()]
            for uid in participants:
                try:
                    await bot.send_message(uid, "🔔 **ВНИМАНИЕ!** Розыгрыш начнется через 60 секунд! Скрестите пальцы! 🤞")
                except: continue

        # 3. Ждем самого розыгрыша (оставшаяся 1 минута)
        wait_for_draw = (next_hour - datetime.datetime.now()).total_seconds()
        if wait_for_draw > 0:
            await asyncio.sleep(wait_for_draw)

        try:
            # Получаем данные текущего тиража
            cursor.execute("SELECT draw_id, prize_pool FROM hourly_state ORDER BY draw_id DESC LIMIT 1")
            res = cursor.fetchone()
            if not res: continue
            draw_id, prize = res

            # Собираем всех участников и их количество билетов
            cursor.execute("""
                SELECT user_id, COUNT(*) as tix 
                FROM lottery_tickets 
                WHERE lottery_type = 'hourly' AND buy_time > ? 
                GROUP BY user_id ORDER BY tix DESC
            """, (int(time.time()) - 3600,))
            rows = cursor.fetchall()

            if not rows:
                # ЕСЛИ НИКТО НЕ УЧАСТВОВАЛ: переносим деньги в следующий тираж
                cursor.execute("INSERT INTO hourly_state (prize_pool) VALUES (?)", (prize,))
                conn.commit()
                logging.info(f"Тираж #{draw_id} пуст. Приз {prize} перенесен.")
                continue

            # Определяем победителя (рандом с учетом веса/количества билетов)
            pool_for_random = []
            for uid, tix in rows:
                pool_for_random.extend([uid] * tix)
            
            winner_id = random.choice(pool_for_random)
            
            # Начисляем выигрыш
            db_update_stats(winner_id, bet=0, win=prize)

            # Формируем таблицу результатов
            table_text = f"🎰 **ИТОГИ РОЗЫГРЫША #{draw_id}**\n\n"
            table_text += "👤 **Участники и билеты:**\n"
            
            for i, (uid, tix) in enumerate(rows, 1):
                mark = "🏆" if uid == winner_id else "🔹"
                table_text += f"{i}. {mark} ID: `{uid}` — {tix} шт.\n"
            
            table_text += f"\n💰 **Общий приз:** `{prize:,}` 💎\n"
            table_text += f"👑 **Победитель:** `{winner_id}`"

            # Рассылаем всем участникам итоги в ЛС
            for uid, _ in rows:
                try:
                    await bot.send_message(uid, table_text, parse_mode="Markdown")
                except: continue

            # Создаем новый тираж (базовый фонд 100к)
            cursor.execute("INSERT INTO hourly_state (prize_pool) VALUES (100000)")
            conn.commit()
            logging.info(f"Розыгрыш #{draw_id} завершен. Победитель: {winner_id}")

        except Exception as e:
            logging.error(f"Ошибка розыгрыша: {e}")
            await asyncio.sleep(10)

async def main():
    logging.basicConfig(level=logging.WARNING)
    bot = Bot(token=API_TOKEN)
    dp = Dispatcher()
    
    dp.message.middleware(flood_middleware())
    dp.callback_query.middleware(flood_middleware())

    # Регистрация роутеров
    dp.include_router(mines.router)
    dp.include_router(admin.router)
    dp.include_router(common.router)
    dp.include_router(qtop.router)
    dp.include_router(monetka.router)
    dp.include_router(sunduk.router)
    dp.include_router(dicedarts.router)
    dp.include_router(futandbask.router)
    dp.include_router(lottery.router)
    dp.include_router(mining.router)
    
    await bot.delete_webhook(drop_pending_updates=True)

    try:
        cursor.execute("DELETE FROM daily_stats")
        conn.commit()
    except:
        pass

    await bot.set_my_commands([
        BotCommand(command="start", description="📱 Мой профиль"),
        BotCommand(command="games", description="🎮 Список игр"),
        BotCommand(command="top", description="🏆 Рейтинг"),
        BotCommand(command="help", description="❓ Помощь и команды"),
    ])

    print("🚀 Бот запущен!")
    
    # Запуск фоновой задачи
    asyncio.create_task(hourly_draw_task(bot))
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())