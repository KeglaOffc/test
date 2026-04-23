import random
import logging
import time
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database import db_get_user, db_update_stats, cursor, conn
from Handlers.common import check_user

logger = logging.getLogger(__name__)
router = Router()

# Защита от spam
FLIP_COOLDOWN = {}
FLIP_COOLDOWN_SEC = 2

@router.message(Command("flip"))
async def flip_start(message: types.Message):
    try:
        user_data = await check_user(message)
        if not user_data: return
            
        args = message.text.split()
        if len(args) < 2 or not args[1].isdigit(): 
            return await message.reply("📝 Использование: /flip [ставка]")
        
        bet = int(args[1])
        if bet < 10 or bet > user_data[0]:
            return await message.reply(f"❌ Некорректная ставка (Мин: 10, Ваш баланс: {user_data[0]:,})")

        builder = InlineKeyboardBuilder()
        builder.button(text="🦅 ОРЕЛ", callback_data=f"flip_choice:{bet}:heads")
        builder.button(text="🪙 РЕШКА", callback_data=f"flip_choice:{bet}:tails")
        builder.button(text="🎯 МНОЖИТЕЛЬ x5", callback_data=f"flip_choice:{bet}:heads:risky")
        builder.adjust(2, 1)
        
        await message.answer(
            f"💰 Ставка: {bet:,} 💎\n\n"
            f"🔹 Обычное - Выигрыш x1.9\n"
            f"🔸 Рискованное (Множитель) - Выигрыш x5 (50% шанс)\n\n"
            f"Выбирай сторону:", 
            reply_markup=builder.as_markup()
        )
    except Exception as e:
        logger.error(f"Error in flip_start: {e}")
        await message.reply("❌ Ошибка при запуске игры.")

@router.callback_query(F.data.startswith("flip_choice:"))
async def flip_result(call: types.CallbackQuery):
    try:
        user_id = call.from_user.id
        
        # ЗАЩИТА ОТ SPAM (debounce)
        current_time = time.time()
        if user_id in FLIP_COOLDOWN:
            if current_time - FLIP_COOLDOWN[user_id] < FLIP_COOLDOWN_SEC:
                return await call.answer("⏱️ Слишком быстро! Подождите...", show_alert=True)
        FLIP_COOLDOWN[user_id] = current_time
        
        await call.answer()
        data = call.data.split(":")
        bet = int(data[1])
        if bet <= 0:
            return await call.answer("❌ Некорректная ставка!", show_alert=True)
        choice = data[2]
        risky_mode = len(data) > 3 and data[3] == "risky"
        
        u_d = db_get_user(user_id)
        if not u_d:
            try:
                await call.message.edit_text("❌ Ошибка при загрузке профиля.")
            except TelegramBadRequest:
                pass
            return
        
        if u_d[0] < bet:
            try:
                await call.message.edit_text("❌ Недостаточно средств.")
            except TelegramBadRequest:
                pass
            return

        # ИСПОЛЬЗУЕМ ТРАНЗАКЦИЮ ДЛЯ ЗАЩИТЫ ОТ ДЮПОВ
        try:
            cursor.execute("BEGIN IMMEDIATE")
            
            # Проверяем баланс ЕЩЕ РАЗ внутри транзакции
            cursor.execute("SELECT balance FROM users WHERE id = ?", (user_id,))
            res = cursor.fetchone()
            if not res or res[0] < bet:
                cursor.execute("ROLLBACK")
                try:
                    await call.message.edit_text("❌ Недостаточно средств!")
                except TelegramBadRequest:
                    logger.warning("Timeout при проверке баланса")
                return
            
            # Списываем ставку АТОМАРНО
            cursor.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (bet, user_id))
            
            # --- ЛОГИКА РЕЗУЛЬТАТА ---
            status_db = u_d[6]
            
            if status_db == "win":
                res = choice
            elif status_db == "lose":
                res = "tails" if choice == "heads" else "heads"
            else:
                res = random.choice(["heads", "tails"])

            res_text = "Орел 🦅" if res == "heads" else "Решка 🪙"
            
            if choice == res:
                if risky_mode:
                    win = int(bet * 5)
                    profit = win - bet
                    emoji = "🔥"
                else:
                    win = int(bet * 1.9)
                    profit = win - bet
                    emoji = "🎉"
                    
                # Добавляем выигрыш (ставка уже вычтена)
                cursor.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (win, user_id))
                cursor.execute("UPDATE users SET total_wins = total_wins + ? WHERE id = ?", (win, user_id))
                
                cursor.execute("SELECT balance FROM users WHERE id = ?", (user_id,))
                new_balance = cursor.fetchone()[0]
                
                result_msg = (
                    f"{emoji} ВЫИГРЫШ!\n\n"
                    f"Выпало: {res_text}\n"
                    f"💰 Профит: +{profit:,} 💎\n"
                    f"💵 Баланс: {new_balance:,} 💎"
                )
            else:
                cursor.execute("UPDATE users SET total_bets = total_bets + ? WHERE id = ?", (bet, user_id))
                
                cursor.execute("SELECT balance FROM users WHERE id = ?", (user_id,))
                new_balance = cursor.fetchone()[0]
                
                result_msg = (
                    f"💀 ПРОИГРЫШ\n\n"
                    f"Выпало: {res_text}\n"
                    f"📉 Убыток: -{bet:,} 💎\n"
                    f"💵 Баланс: {new_balance:,} 💎"
                )
            
            conn.commit()
            
        except Exception as e:
            cursor.execute("ROLLBACK")
            logger.error(f"Error in flip_result transaction: {e}")
            return await call.message.edit_text("❌ Ошибка при обработке результата.")
        
        await call.message.edit_text(result_msg)
    except Exception as e:
        logger.error(f"Error in flip_result: {e}")
        await call.message.edit_text("❌ Ошибка при обработке результата.")