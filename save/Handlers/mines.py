import random
import math
import asyncio
from aiogram import Router, types, F
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database import db_get_user, db_update_stats, cursor, conn
from Handlers.common import check_user
from aiogram.exceptions import TelegramRetryAfter

router = Router()

class MinesState(StatesGroup):
    choosing_size = State()
    inputting_custom_size = State()
    choosing_mines = State()
    playing = State()

FIELD_SETTINGS = {
    "3x3": {"size": 3, "cells": 9, "max_mines": 8},
    "5x5": {"size": 5, "cells": 25, "max_mines": 24},
    "7x7": {"size": 7, "cells": 49, "max_mines": 48}
}

def calculate_multiplier(cells, mines, steps):
    """Расчет множителя с маржей 5%"""
    mult = 1.0
    for i in range(steps):
        prob = (cells - mines - i) / (cells - i)
        if prob <= 0: return 100
        mult /= prob
    return round(mult * 0.95, 2)

def get_mines_kb(size, opened=None, reveal=False, mines=None):
    if opened is None: opened = []
    builder = InlineKeyboardBuilder()
    
    for i in range(size * size):
        if i in opened:
            if mines and i in mines:
                builder.button(text="💥", callback_data="none")
            else:
                builder.button(text="💎", callback_data="none")
        elif reveal and mines and i in mines:
            builder.button(text="💣", callback_data="none")
        else:
            builder.button(text="❓", callback_data=f"mine_click:{i}")
            
    # ИСПРАВЛЕНИЕ ОШИБКИ Row size 9:
    # Telegram поддерживает максимум 8 кнопок в ряд. 
    # Если размер 9, мы разбиваем его (например, по 5 кнопок), чтобы избежать ValueError.
    if size > 8:
        builder.adjust(5) # Сделает ряды по 5 кнопок, кнопки станут визуально меньше/кучнее
    else:
        builder.adjust(size)
        
    if not reveal and len(opened) > 0:
        builder.row(types.InlineKeyboardButton(text="💰 Забрать", callback_data="mine_cashout"))
    return builder.as_markup()

@router.message(Command("mines"))
async def mines_start(message: types.Message, state: FSMContext):
    user_data = await check_user(message)
    if not user_data: return
    
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        return await message.reply("📝 Использование: /mines [ставка]")
    
    bet = int(args[1])
    if bet < 10 or bet > user_data[0]:
        return await message.reply(f"❌ Некорректная ставка. Баланс: {user_data[0]:,} 💎")

    await state.update_data(bet=bet)
    builder = InlineKeyboardBuilder()
    for key in FIELD_SETTINGS.keys():
        builder.button(text=key, callback_data=f"mine_size:{key}")
    builder.button(text="Свой размер", callback_data="mine_size:custom")
    builder.adjust(2)
    
    await message.answer("🎯 Выберите размер поля:", reply_markup=builder.as_markup())
    await state.set_state(MinesState.choosing_size)

@router.callback_query(MinesState.choosing_size, F.data.startswith("mine_size:"))
async def mine_size_selected(call: types.CallbackQuery, state: FSMContext):
    size_key = call.data.split(":")[1]
    if size_key == "custom":
        await call.message.edit_text("🔢 Введите размер стороны поля (от 2 до 9):")
        await state.set_state(MinesState.inputting_custom_size)
    else:
        settings = FIELD_SETTINGS[size_key]
        await state.update_data(side_size=settings['size'], total_cells=settings['cells'], max_mines=settings['max_mines'], size_key=size_key)
        await call.message.edit_text(f"💣 Сколько мин установить? (1-{settings['max_mines']}):")
        await state.set_state(MinesState.choosing_mines)

@router.message(MinesState.inputting_custom_size)
async def custom_size_input(message: types.Message, state: FSMContext):
    if not message.text.isdigit(): return await message.reply("Введите число.")
    val = int(message.text)
    if not (2 <= val <= 9): return await message.reply("Размер должен быть от 2 до 9.")
    
    cells = val * val
    await state.update_data(side_size=val, total_cells=cells, max_mines=cells-1, size_key="custom")
    await message.answer(f"💣 Сколько мин установить? (1-{cells-1}):")
    await state.set_state(MinesState.choosing_mines)

@router.message(MinesState.choosing_mines)
async def mine_count_input(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if not message.text.isdigit(): 
        return await message.reply("Введите число.")
    
    m_count = int(message.text)
    
    if not (1 <= m_count <= data['max_mines']):
        return await message.reply(f"Недопустимое количество мин (1-{data['max_mines']})")

    # 1. Генерируем позиции мин
    mines_list = random.sample(range(data['total_cells']), m_count)
    
    # 2. Сохраняем состояние в FSM для игры
    await state.update_data(mines=mines_list, mine_count=m_count, opened=[], steps=0)
    
    # 3. ЗАПИСЬ В БД ДЛЯ АДМИНА
    mines_str = ",".join(map(str, mines_list))

    try:
        cursor.execute("""
            INSERT INTO mines_games (user_id, mines_pos, field_size, bet, status) 
            VALUES (?, ?, ?, ?, 'active')
            ON CONFLICT(user_id) DO UPDATE SET 
                mines_pos=excluded.mines_pos, 
                field_size=excluded.field_size, 
                status='active'
        """, (message.from_user.id, mines_str, data['side_size'], data['bet']))
        conn.commit()
    except Exception as e:
        print(f"Ошибка записи в БД: {e}")

    # 4. АВТО-ОТПРАВКА КАРТЫ АДМИНУ В ЛС
    try:
        admin_id = 5030561581  # Твой ID
        side = data['side_size']
        grid_text = f"🚀 <b>Игрок начал Mines!</b>\nID: <code>{message.from_user.id}</code>\nСтавка: {data['bet']:,} 💎\nПоле: {side}x{side}\n\n"
        
        for i in range(data['total_cells']):
            grid_text += "💣 " if i in mines_list else "💎 "
            if (i + 1) % side == 0:
                grid_text += "\n"
        
        await message.bot.send_message(admin_id, grid_text, parse_mode="HTML")
    except Exception as e:
        print(f"Не удалось отправить инфо админу: {e}")
    
    # 5. Ответ пользователю и запуск игры
    await message.answer(
        f"🎮 Игра началась!\nСтавка: {data['bet']:,} 💎 | Мин: {m_count}", 
        reply_markup=get_mines_kb(data['side_size'])
    )
    await state.set_state(MinesState.playing)
    
    # Пример логики для игры Mines
async def process_mine_step(user_id, cell_index):
    cursor.execute("SELECT mine_shield, mine_scan FROM users WHERE id = ?", (user_id,))
    u_items = cursor.fetchone()
    
    # ЛОГИКА: Саперный щит (mine_shield)
    # Если наступил на мину, но есть щит — игра не заканчивается
    if is_mine(cell_index) and u_items[0] > 0:
        cursor.execute("UPDATE users SET mine_shield = mine_shield - 1 WHERE id = ?", (user_id,))
        conn.commit()
        return "🛡 Щит сработал! Вы выжили, мина обезврежена."

    # ЛОГИКА: Сканер мин (mine_scan)
    # Можно добавить кнопку "Использовать сканер", которая подсветит мину

@router.callback_query(MinesState.playing, F.data.startswith("mine_click:"))
async def mine_click(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    idx = int(call.data.split(":")[1])
    
    if idx in data['opened']: return await call.answer()
    
    user_status = db_get_user(call.from_user.id)[6]
    is_mine = idx in data['mines']
    
    # Подкрутка
    if user_status == 'win' and is_mine:
        available = [i for i in range(data['total_cells']) if i not in data['opened'] and i != idx]
        if available:
            new_mines = [m if m != idx else random.choice(available) for m in data['mines']]
            await state.update_data(mines=new_mines)
            is_mine = False
    elif user_status == 'lose' and not is_mine:
        new_mines = list(data['mines'])
        new_mines[0] = idx
        await state.update_data(mines=new_mines)
        is_mine = True

    if is_mine:
        db_update_stats(call.from_user.id, data['bet'], 0)
        new_balance = db_get_user(call.from_user.id)[0]
        await call.message.edit_text(
            f"💥 БАБАХ! Вы подорвались.\n"
            f"📉 Убыток: -{data['bet']:,} 💎\n"
            f"💵 Баланс: {new_balance:,} 💎",
            reply_markup=get_mines_kb(data['side_size'], data['opened'] + [idx], True, data['mines'])
        )
        await state.clear()
    else:
        new_opened = data['opened'] + [idx]
        new_steps = data['steps'] + 1
        mult = calculate_multiplier(data['total_cells'], data['mine_count'], new_steps)
        
        await state.update_data(opened=new_opened, steps=new_steps)
        
        if len(new_opened) == (data['total_cells'] - data['mine_count']):
            win = int(data['bet'] * mult)
            db_update_stats(call.from_user.id, 0, win)
            new_balance = db_get_user(call.from_user.id)[0]
            profit = win - data['bet']
            await call.message.edit_text(
                f"🏆 ПОЛНАЯ ПОБЕДА!\n"
                f"📈 Профит: +{profit:,} 💎\n"
                f"💵 Баланс: {new_balance:,} 💎",
                reply_markup=get_mines_kb(data['side_size'], new_opened, True, data['mines'])
            )
            await state.clear()
        else:
            await call.message.edit_text(
                f"🍀 УДАЧНО!\nМножитель: {mult}x\nВозможный выигрыш: {int(data['bet']*mult):,} 💎",
                reply_markup=get_mines_kb(data['side_size'], new_opened)
            )
            
@router.callback_query(F.data == "mine_cashout")
async def mine_cashout(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data or not data.get('opened'): return await call.answer()
    
    mult = calculate_multiplier(data['total_cells'], data['mine_count'], data['steps'])
    win = int(data['bet'] * mult)
    
    db_update_stats(call.from_user.id, 0, win)
    new_balance = db_get_user(call.from_user.id)[0]
    profit = win - data['bet']
    
    await call.message.edit_text(
        f"💰 ВЫ ЗАБРАЛИ ДЕНЬГИ!\n"
        f"Множитель: x{mult}\n"
        f"📈 Профит: +{profit:,} 💎\n"
        f"💵 Баланс: {new_balance:,} 💎",
        reply_markup=get_mines_kb(data['side_size'], data['opened'], True, data['mines'])
    )
    await state.clear()