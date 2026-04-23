import random
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database import db_get_user, db_update_stats

router = Router()

async def check_user(message: types.Message):
    data = db_get_user(message.from_user.id)
    if data and data[2] == 1:
        await message.reply("🚫 Вы заблокированы.")
        return None
    return data

@router.message(Command("flip"))
async def flip_start(message: types.Message):
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
    await message.answer(f"💰 Ставка: {bet:,} 💎\nВыбирай сторону:", reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("flip_choice:"))
async def flip_result(call: types.CallbackQuery):
    await call.answer() # Мгновенный ответ
    data = call.data.split(":")
    bet, choice = int(data[1]), data[2]
    
    u_d = db_get_user(call.from_user.id)
    if u_d[0] < bet:
        return await call.message.edit_text("❌ Недостаточно средств.")

    # --- ЛОГИКА ИНДИВИДУАЛЬНОЙ ПОДКРУТКИ ---
    status_db = u_d[6] # Поле status в таблице users
    
    if status_db == "flip:win":
        res = choice
    elif status_db == "flip:lose":
        res = "tails" if choice == "heads" else "heads"
    else:
        res = random.choice(["heads", "tails"])
    # ----------------------------------------------

    res_text = "Орел 🦅" if res == "heads" else "Решка 🪙"
    
    if choice == res:
        win = int(bet * 1.9)
        profit = win - bet
        db_update_stats(call.from_user.id, bet, win)
        new_balance = db_get_user(call.from_user.id)[0]
        
        await call.message.edit_text(
            f"🎉 ВЫИГРЫШ!\n\n"
            f"Выпало: {res_text}\n"
            f"💰 Профит: +{profit:,} 💎\n"
            f"💵 Баланс: {new_balance:,} 💎"
        )
    else:
        db_update_stats(call.from_user.id, bet, 0)
        new_balance = db_get_user(call.from_user.id)[0]
        
        await call.message.edit_text(
            f"💀 ПРОИГРЫШ\n\n"
            f"Выпало: {res_text}\n"
            f"📉 Убыток: -{bet:,} 💎\n"
            f"💵 Баланс: {new_balance:,} 💎"
        )