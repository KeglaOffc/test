import asyncio
import random
import logging
import re
import time
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database import db_get_user, db_update_stats, cursor, conn
from Handlers.common import check_user

# Защита от spam-реролла
REROLL_COOLDOWN = {}

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("dice", "darts"))
async def dual_games(message: types.Message):
    try:
        user_data = await check_user(message)
        if not user_data: 
            return
            
        args = message.text.split()
        if len(args) < 2: 
            return await message.reply("📝 Использование: /команда [ставка]")
            
        try:
            bet = int(args[1])
        except ValueError:
            return await message.reply("❌ Ставка должна быть числом.")
            
        if bet <= 0:
            return await message.reply("❌ Ставка должна быть больше 0.")
            
        if bet > user_data[0]: 
            return await message.reply(f"❌ Недостаточно средств. Баланс: {user_data[0]:,} 💎")

        # Определяем текущую игру
        cmd_name = "dice" if "dice" in message.text.lower() else "darts"
        
        await play_dice_logic(message, bet, cmd_name)

    except Exception as e:
        logger.error(f"Error in dual_games: {e}")
        await message.reply("❌ Ошибка при выполнении игры.")

async def play_dice_logic(message: types.Message, bet: int, game_type: str, is_reroll=False):
    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            "UPDATE users SET balance = balance - ? WHERE id = ? AND balance >= ?",
            (bet, message.from_user.id, bet),
        )
        if cursor.rowcount == 0:
            cursor.execute("ROLLBACK")
            return await message.reply("❌ Недостаточно средств.")
        conn.commit()
    except Exception:
        cursor.execute("ROLLBACK")
        logger.exception("dice/darts: deduction failed")
        return await message.reply("❌ Ошибка при списании ставки.")

    emoji = "🎲" if game_type == "dice" else "🎯"
    user_id = message.from_user.id

    if is_reroll:
        await message.answer(f"🔄 **ПЕРЕБРОС!** Ставка {bet:,} 💎 возвращена. Новая попытка...", parse_mode="Markdown")
    else:
        await message.answer("🤖 Ход бота...")
    
    b_msg = await message.answer_dice(emoji=emoji)
    b_v = b_msg.dice.value
    
    await asyncio.sleep(4) # Даем время анимации проиграться
    
    if not is_reroll:
        await message.answer("👤 Твой ход...")
    
    u_msg = await message.answer_dice(emoji=emoji)
    u_v = u_msg.dice.value
    
    await asyncio.sleep(4)

    # Логика расчета результата
    if u_v > b_v:
        win = bet * 2
    elif u_v == b_v:
        win = bet
    else:
        win = 0

    # Обновляем статистику в БД
    db_update_stats(user_id, bet, win, deducted=True)
    
    # Получаем актуальный баланс
    user_final = db_get_user(user_id)
    new_bal = user_final[0]

    builder = InlineKeyboardBuilder()
    
    if u_v > b_v:
        result_text = f"🏆 ПОБЕДА!\n💰 Получено: +{win - bet:,} 💎"
    elif u_v == b_v:
        result_text = f"🤝 НИЧЬЯ\n💰 Ставка возвращена"
    else:
        result_text = f"💀 ПРОИГРЫШ\n📉 Убыток: -{bet:,} 💎"
        
        # Проверяем наличие рероллов только при проигрыше
        cursor.execute("SELECT rerolls FROM users WHERE id = ?", (user_id,))
        res = cursor.fetchone()
        rerolls = res[0] if res else 0
        
        if rerolls > 0:
            builder.button(text=f"🔄 Переброс ({rerolls} шт)", callback_data=f"reroll:{bet}:{game_type}")

    await message.reply(
        f"{result_text}\n\n"
        f"🤖 Бот: {b_v} | 👤 Ты: {u_v}\n"
        f"💵 Баланс: {new_bal:,} 💎",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("reroll:"))
async def reroll_callback(call: types.CallbackQuery):
    try:
        user_id = call.from_user.id
        
        # ЗАЩИТА ОТ SPAM: Проверяем cooldown
        current_time = time.time()
        if user_id in REROLL_COOLDOWN:
            if current_time - REROLL_COOLDOWN[user_id] < 2:  # 2 сек защиты от spam
                return await call.answer("⏱️ Слишком быстро! Подождите...", show_alert=True)
        REROLL_COOLDOWN[user_id] = current_time
        
        data = call.data.split(":")
        bet = int(data[1])
        
        if bet <= 0:
            return await call.answer("❌ Некорректная ставка!", show_alert=True)

        # Безопасность: Проверяем ставку по тексту сообщения
        msg_text = call.message.text or call.message.caption or ""
        match = re.search(r"Убыток:\s*-([\d\s\.,]+)", msg_text)
        if match:
            # Очищаем строку от пробелов и запятых
            real_bet_str = match.group(1).replace(" ", "").replace("\xa0", "").replace(",", "").replace(".", "")
            real_bet_str = "".join(filter(str.isdigit, real_bet_str))
            if real_bet_str:
                real_bet = int(real_bet_str)
                if real_bet != bet:
                    logger.warning(f"SECURITY: User {user_id} forged reroll bet {bet} -> {real_bet}")
                    bet = real_bet

        game_type = data[2]
        
        # Проверяем рероллы (используем транзакцию)
        try:
            cursor.execute("BEGIN IMMEDIATE")  # Блокируем запись
            cursor.execute("SELECT rerolls, balance FROM users WHERE id = ?", (user_id,))
            res = cursor.fetchone()
            
            if not res or res[0] < 1:
                cursor.execute("ROLLBACK")
                return await call.answer("❌ У вас нет рероллов!", show_alert=True)
                
            # Списываем реролл и возвращаем ставку (АТОМАРНО)
            cursor.execute("UPDATE users SET rerolls = rerolls - 1, balance = balance + ? WHERE id = ?", (bet, user_id))
            conn.commit()
            
        except Exception as e:
            cursor.execute("ROLLBACK")
            logger.error(f"Error in reroll transaction: {e}")
            return await call.answer("❌ Ошибка при реролле", show_alert=True)
        
        # Удаляем кнопку у старого сообщения
        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest as e:
            logger.warning(f"Timeout при удалении кнопки: {e}")
            
        await call.answer("🔄 Реролл использован!")
        
        # Запускаем новую игру
        await play_dice_logic(call.message, bet, game_type, is_reroll=True)
        
    except Exception as e:
        logger.error(f"Error in reroll_callback: {e}")
        await call.answer("❌ Ошибка при реролле", show_alert=True)
