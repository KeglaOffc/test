import random
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Импортируем функции БД и общую проверку
from database import db_get_user, db_update_stats
from Handlers.common import check_user

router = Router()

# --- СУНДУКИ ---
@router.message(Command("chests"))
async def chests_start(message: types.Message):
    user_data = await check_user(message)
    if not user_data: 
        return
        
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit(): 
        return await message.reply("📝 Использование: /chests [ставка]")
    
    bet = int(args[1])
    
    if bet < 10:
        return await message.reply("❌ Минимальная ставка — 10 💎")
        
    if bet > user_data[0]: 
        return await message.reply(f"❌ Недостаточно средств. Ваш баланс: {user_data[0]:,} 💎")

    builder = InlineKeyboardBuilder()
    # В callback_data передаем: ставку, индекс сундука и ID игрока для безопасности
    for i in range(3): 
        builder.button(text="🎁", callback_data=f"chest_op:{bet}:{i}:{message.from_user.id}")
    
    await message.answer(
        f"📦 СУНДУКИ\n\n"
        f"Ставка: {bet:,} 💎\n"
        f"Выбери один из трех сундуков:", 
        reply_markup=builder.as_markup()
    )

@router.callback_query(F.data.startswith("chest_op:"))
async def chest_open(call: types.CallbackQuery):
    data = call.data.split(":")
    bet = int(data[1])
    choice_idx = int(data[2])
    player_id = int(data[3])

    # Проверка, что на кнопку нажал именно тот, кто запустил игру
    if call.from_user.id != player_id:
        return await call.answer("🚫 Это не ваша игра!", show_alert=True)

    # Получаем актуальные данные пользователя
    u_d = db_get_user(call.from_user.id)
    if u_d[0] < bet:
        return await call.message.edit_text("❌ Ошибка: недостаточно средств.")

    # Полный набор множителей
    base_pool = [3.0, 0.0, 0.5, 1.5, 0.2]
    
    # --- ЛОГИКА ПОДКРУТКИ ---
    status = u_d[6] # Поле status
    
    if status == 'win':
        outcomes = [3.0, 3.0, 3.0]
    elif status == 'lose':
        outcomes = [0.0, 0.0, 0.0]
    else:
        outcomes = random.sample(base_pool, 3)
    
    # Перемешиваем выбранные сундуки
    random.shuffle(outcomes)
    
    # Результат по выбранному индексу
    mult = outcomes[choice_idx]
    win = int(bet * mult)
    
    # Обновляем статистику в БД
    db_update_stats(call.from_user.id, bet, win)
    
    # Получаем актуальный баланс
    new_balance = db_get_user(call.from_user.id)[0]
    
    # Расчет профита
    profit = win - bet
    profit_text = f"+{profit:,}" if profit >= 0 else f"{profit:,}"

    # Формируем сообщение с результатом
    result_msg = (
        f"🎁 РЕЗУЛЬТАТ ОТКРЫТИЯ\n\n"
        f"Сундук №{choice_idx + 1} | Множитель: x{mult}\n"
        f"📈 Итог: {profit_text} 💎\n"
        f"💵 Баланс: {new_balance:,} 💎"
    )

    # Визуализация содержимого (раскрываем карты)
    reveal_text = "\n\n🔍 Содержимое сундуков:\n"
    for i, m in enumerate(outcomes):
        if i == choice_idx:
            reveal_text += f"📦 {i+1} сундук: {m}x ← (Твой выбор)\n"
        else:
            reveal_text += f"📦 {i+1} сундук: {m}x\n"

    await call.message.edit_text(result_msg + reveal_text)