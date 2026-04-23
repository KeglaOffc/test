import asyncio
import random
from aiogram import Router, types
from aiogram.filters import Command
# Импортируем нужные функции из твоего файла database.py
from database import db_get_user, db_update_stats

router = Router()

# Вспомогательная функция для проверки пользователя (бан и данные)
async def check_user(message: types.Message):
    data = db_get_user(message.from_user.id)
    if not data:
        return None
    if data[2] == 1: # Если забанен
        await message.reply("🚫 Вы заблокированы администрацией.")
        return None
    return data


# --- ДУЭЛИ (DICE, DARTS) ---
@router.message(Command("dice", "darts"))
async def dual_games(message: types.Message):
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

    # Определяем текущую игру для проверки статуса подкрутки
    cmd_name = "dice" if "dice" in message.text.lower() else "darts"
    emoji = "🎲" if cmd_name == "dice" else "🎯"
    status_db = user_data[6] # Поле status (индекс 6)

    # Переменные для принудительных значений (подкрутка)
    forced_user_v = None
    forced_bot_v = None

    # --- ЛОГИКА ПОДКРУТКИ ---
    if status_db == f"{cmd_name}:win":
        forced_user_v = 6
        forced_bot_v = random.randint(1, 5)
    elif status_db == f"{cmd_name}:lose":
        forced_user_v = 1
        forced_bot_v = random.randint(2, 6)
    # ------------------------
    
    await message.answer("🤖 Ход бота...")
    b_msg = await message.answer_dice(emoji=emoji)
    b_v = forced_bot_v if forced_bot_v else b_msg.dice.value
    
    await asyncio.sleep(4) # Даем время анимации проиграться
    
    await message.answer("👤 Твой ход...")
    u_msg = await message.answer_dice(emoji=emoji)
    u_v = forced_user_v if forced_user_v else u_msg.dice.value
    
    await asyncio.sleep(4)

    # Логика расчета результата
    if u_v > b_v:
        win = bet * 2
    elif u_v == b_v:
        win = bet
    else:
        win = 0

    # Обновляем статистику в БД
    db_update_stats(message.from_user.id, bet, win)
    
    # Получаем актуальный баланс
    user_final = db_get_user(message.from_user.id)
    new_bal = user_final[0]

    # --- КРАСИВЫЙ ВЫВОД БЕЗ ЗВЕЗДОЧЕК ---
    if u_v > b_v:
        result_text = f"🏆 ПОБЕДА!\n💰 Получено: +{win - bet:,} 💎"
    elif u_v == b_v:
        result_text = f"🤝 НИЧЬЯ\n💰 Ставка возвращена"
    else:
        result_text = f"💀 ПРОИГРЫШ\n📉 Убыток: -{bet:,} 💎"

    await message.reply(
        f"{result_text}\n\n"
        f"🤖 Бот: {b_v} | 👤 Ты: {u_v}\n"
        f"💵 Баланс: {new_bal:,} 💎"
    )

    # Конец функции