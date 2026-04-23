import logging
import os
import random

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import conn, cursor, db_get_user, db_update_stats
from Handlers.common import check_user

logger = logging.getLogger(__name__)
router = Router()

class MinesState(StatesGroup):
    choosing_size = State()
    inputting_custom_size = State()
    choosing_mines = State()
    playing = State()
    scanning = State()

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

def get_mines_kb(size, opened=None, reveal=False, mines=None, scanning=False, user_id=None, flagged=None):
    if opened is None: opened = []
    if flagged is None: flagged = []
    builder = InlineKeyboardBuilder()
    
    for i in range(size * size):
        if i in opened:
            if mines and i in mines:
                builder.button(text="💥", callback_data="none")
            else:
                builder.button(text="💎", callback_data="none")
        elif i in flagged:
            builder.button(text="🚩", callback_data="none")
        elif reveal and mines and i in mines:
            builder.button(text="💣", callback_data="none")
        else:
            if scanning:
                builder.button(text="🔍", callback_data=f"mine_scan:{i}")
            else:
                builder.button(text="❓", callback_data=f"mine_click:{i}")
            
    # ИСПРАВЛЕНИЕ ОШИБКИ Row size 9:
    # Telegram поддерживает максимум 8 кнопок в ряд. 
    # Если размер 9, мы разбиваем его (например, по 5 кнопок), чтобы избежать ValueError.
    if size > 8:
        builder.adjust(5) # Сделает ряды по 5 кнопок, кнопки станут визуально меньше/кучнее
    else:
        builder.adjust(size)
        
    if not reveal and len(opened) > 0 and not scanning:
        builder.row(types.InlineKeyboardButton(text="💰 Забрать", callback_data="mine_cashout"))
    
    # Кнопка сканера если игрок имеет mine_scan
    if not reveal and not scanning and user_id and len(opened) == 0:
        cursor.execute("SELECT mine_scan FROM users WHERE id = ?", (user_id,))
        result = cursor.fetchone()
        if result and result[0] > 0:
            builder.row(types.InlineKeyboardButton(text="🔍 Использовать сканер", callback_data="mine_activate_scan"))
    
    return builder.as_markup()

@router.message(Command("mines"))
async def mines_start(message: types.Message, state: FSMContext):
    user_data = await check_user(message)
    if not user_data: return
    
    args = message.text.split()
    if len(args) < 2:
        return await message.reply("📝 Использование: /mines [ставка]")
        
    if not args[1].isdigit(): # isdigit не пускает минус, но проверим дальше
         try:
            val = int(args[1])
            if val <= 0: return await message.reply("❌ Ставка должна быть больше нуля!")
         except ValueError:
            return await message.reply("❌ Некорректное число!")
    
    bet = int(args[1])
    if bet <= 0: return await message.reply("❌ Ставка должна быть больше нуля!")
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
    if not message.text.isdigit():
        return await message.reply("Введите число.")
    
    val = int(message.text)
    if val <= 0: # Защита от отрицательных чисел (хотя isdigit не пустит минус, но для надежности)
        return await message.reply("Число должно быть положительным.")
        
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
    if m_count <= 0:
        return await message.reply("Число должно быть положительным.")
    
    if not (1 <= m_count <= data['max_mines']):
        return await message.reply(f"Недопустимое количество мин (1-{data['max_mines']})")

    user = db_get_user(message.from_user.id)
    if user[0] < data['bet']:
        return await message.reply("❌ Недостаточно средств! Пополните баланс.")
    
    mines_list = random.sample(range(data['total_cells']), m_count)
    
    try:
        cursor.execute("BEGIN IMMEDIATE")
        
        # Еще раз проверяем баланс внутри транзакции
        cursor.execute("SELECT balance FROM users WHERE id = ?", (message.from_user.id,))
        res = cursor.fetchone()
        if not res or res[0] < data['bet']:
            cursor.execute("ROLLBACK")
            return await message.reply("❌ Недостаточно средств!")
        
        # Списываем деньги АТОМАРНО
        cursor.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (data['bet'], message.from_user.id))
        
        mines_str = ",".join(map(str, mines_list))
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
        cursor.execute("ROLLBACK")
        logger.error(f"Error in mines transaction: {e}")
        return await message.reply("❌ Ошибка при запуске игры. Попробуйте еще раз.")
    
    await state.update_data(mines=mines_list, mine_count=m_count, opened=[], flagged=[], steps=0)

    try:
        admin_id = int(os.getenv("ADMIN_ID", 5030561581))
        side = data['side_size']
        grid_text = f"🚀 <b>Игрок начал Mines!</b>\nID: <code>{message.from_user.id}</code>\nСтавка: {data['bet']:,} 💎\nПоле: {side}x{side}\n\n"
        
        for i in range(data['total_cells']):
            grid_text += "💣 " if i in mines_list else "💎 "
            if (i + 1) % side == 0:
                grid_text += "\n"
        
        await message.bot.send_message(admin_id, grid_text, parse_mode="HTML")
    except Exception as e:
        print(f"Не удалось отправить инфо админу: {e}")
    
    await message.answer(
        f"🎮 Игра началась!\nСтавка: {data['bet']:,} 💎 | Мин: {m_count}", 
        reply_markup=get_mines_kb(data['side_size'], user_id=message.from_user.id)
    )
    await state.set_state(MinesState.playing)
    
    # Пример логики для игры Mines
    # (Функция process_mine_step удалена, логика перенесена в mine_click)

@router.callback_query(MinesState.playing, F.data == "mine_activate_scan")
async def mine_activate_scan(call: types.CallbackQuery, state: FSMContext):
    """Активирует режим сканирования - игрок выбирает клетку для сканирования"""
    data = await state.get_data()
    
    # Проверяем, есть ли у игрока сканер
    cursor.execute("SELECT mine_scan FROM users WHERE id = ?", (call.from_user.id,))
    result = cursor.fetchone()
    if not result or result[0] < 1:
        return await call.answer("❌ У вас нет сканера!", show_alert=True)
    
    await call.answer()
    await state.set_state(MinesState.scanning)
    await call.message.edit_text(
        "🔍 Выберите клетку для сканирования\n(будут открыты 3 соседние)",
        reply_markup=get_mines_kb(data['side_size'], data['opened'], scanning=True)
    )

def get_neighbors(cell_idx, grid_size):
    """Получить соседние клетки (максимум 3) для сканирования"""
    side = int(grid_size ** 0.5)
    row = cell_idx // side
    col = cell_idx % side
    
    neighbors = []
    # Соседи: право, вниз, диагональ вниз-право
    directions = [(0, 1), (1, 0), (1, 1)]  # право, вниз, диагональ
    
    for dr, dc in directions:
        new_row = row + dr
        new_col = col + dc
        if 0 <= new_row < side and 0 <= new_col < side:
            neighbors.append(new_row * side + new_col)
    
    return neighbors

@router.callback_query(MinesState.scanning, F.data.startswith("mine_scan:"))
async def mine_scan_process(call: types.CallbackQuery, state: FSMContext):
    """Сканирует выбранную клетку и 3 соседей"""
    data = await state.get_data()
    scan_idx = int(call.data.split(":")[1])
    
    # Проверяем, не открыта ли уже эта клетка
    if scan_idx in data['opened']:
        return await call.answer("❌ Эта клетка уже открыта!", show_alert=True)
    
    # Получаем соседей + саму клетку
    neighbors = get_neighbors(scan_idx, data['total_cells'])
    targets = [scan_idx] + neighbors
    
    scanned_opened = []
    scanned_flagged = []
    scan_result = ""
    
    for target in targets:
        if target in data['opened'] or target in data.get('flagged', []):
            continue
        
        if target in data['mines']:
            # Это бомба - помечаем флагом
            if target not in scanned_flagged:
                scanned_flagged.append(target)
            scan_result += f"� Клетка {target}: МИНА!\n"
        else:
            # Это гем - открываем
            if target not in scanned_opened:
                scanned_opened.append(target)
            scan_result += f"✅ Клетка {target}: гем! 💎\n"
    
    # Обновляем списки
    current_flagged = data.get('flagged', [])
    new_flagged = list(set(current_flagged + scanned_flagged))
    
    new_opened = list(set(data['opened'] + scanned_opened))
    
    # Вычитаем сканер
    cursor.execute("UPDATE users SET mine_scan = mine_scan - 1 WHERE id = ?", (call.from_user.id,))
    conn.commit()
    
    # Возвращаемся в режим игры
    await state.update_data(opened=new_opened, flagged=new_flagged)
    await state.set_state(MinesState.playing)
    
    # Показываем результат сканирования
    mult = calculate_multiplier(data['total_cells'], data['mine_count'], len(new_opened))
    
    text = (
        f"🔍 <b>РЕЗУЛЬТАТ СКАНИРОВАНИЯ:</b>\n"
        f"{scan_result}\n"
        f"✨ Открыто клеток: {len(new_opened)}\n"
        f"🚩 Найдено мин: {len(scanned_flagged)}\n"
        f"Множитель: {mult}x\n"
        f"Возможный выигрыш: {int(data['bet']*mult):,} 💎"
    )
    
    await call.message.edit_text(text, reply_markup=get_mines_kb(data['side_size'], new_opened, user_id=call.from_user.id, flagged=new_flagged))
    await call.answer("✅ Сканирование завершено!")

@router.callback_query(MinesState.playing, F.data.startswith("mine_click:"))
async def mine_click(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    idx = int(call.data.split(":")[1])
    
    if idx in data['opened']: return await call.answer()
    if idx in data.get('flagged', []): return await call.answer("🚩 Эта клетка помечена как мина!", show_alert=True)
    
    is_mine = idx in data['mines']
    
    # ЛОГИКА ЩИТА (если попали на мину)
    if is_mine:
        cursor.execute("SELECT mine_shield FROM users WHERE id = ?", (call.from_user.id,))
        res = cursor.fetchone()
        if res and res[0] > 0:
            # Щит спасает
            cursor.execute("UPDATE users SET mine_shield = mine_shield - 1 WHERE id = ?", (call.from_user.id,))
            conn.commit()
            
            # Обезвреживаем мину: убираем её из списка мин
            new_mines = [m for m in data['mines'] if m != idx]
            await state.update_data(mines=new_mines)
            is_mine = False
            
            await call.answer("🛡 Щит сработал! Мина обезврежена.", show_alert=True)
            # Продолжаем как будто это не мина (откроется как пустая клетка ниже)

    if is_mine:
        # Ставка уже списана при начале игры.
        # Вызываем update_stats для обработки страховки (если есть)
        db_update_stats(call.from_user.id, data['bet'], 0, deducted=True)
        
        new_balance = db_get_user(call.from_user.id)[0]
        await call.message.edit_text(
            f"💥 БАБАХ! Вы подорвались.\n"
            f"📉 Убыток: -{data['bet']:,} 💎\n"
            f"💵 Баланс: {new_balance:,} 💎",
            reply_markup=get_mines_kb(data['side_size'], data['opened'] + [idx], True, data['mines'], user_id=call.from_user.id, flagged=data.get('flagged', []))
        )
        await state.clear()
    else:
        new_opened = data['opened'] + [idx]
        new_steps = data['steps'] + 1
        mult = calculate_multiplier(data['total_cells'], data['mine_count'], new_steps)
        
        await state.update_data(opened=new_opened, steps=new_steps)
        
        if len(new_opened) == (data['total_cells'] - data['mine_count']):
            win = int(data['bet'] * mult)
            db_update_stats(call.from_user.id, data['bet'], win, deducted=True)
            new_balance = db_get_user(call.from_user.id)[0]
            profit = win - data['bet']
            await call.message.edit_text(
                f"🏆 ПОЛНАЯ ПОБЕДА!\n"
                f"📈 Профит: +{profit:,} 💎\n"
                f"💵 Баланс: {new_balance:,} 💎",
                reply_markup=get_mines_kb(data['side_size'], new_opened, True, data['mines'], user_id=call.from_user.id, flagged=data.get('flagged', []))
            )
            await state.clear()
        else:
            await call.message.edit_text(
                f"🍀 УДАЧНО!\nМножитель: {mult}x\nВозможный выигрыш: {int(data['bet']*mult):,} 💎",
                reply_markup=get_mines_kb(data['side_size'], new_opened, user_id=call.from_user.id, flagged=data.get('flagged', []))
            )
            
@router.callback_query(F.data == "mine_cashout")
async def mine_cashout(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data or not data.get('opened'): return await call.answer()
    
    mult = calculate_multiplier(data['total_cells'], data['mine_count'], data['steps'])
    win = int(data['bet'] * mult)
    
    db_update_stats(call.from_user.id, data['bet'], win, deducted=True)
    new_balance = db_get_user(call.from_user.id)[0]
    profit = win - data['bet']
    
    await call.message.edit_text(
        f"💰 ВЫ ЗАБРАЛИ ДЕНЬГИ!\n"
        f"Множитель: x{mult}\n"
        f"📈 Профит: +{profit:,} 💎\n"
        f"💵 Баланс: {new_balance:,} 💎",
        reply_markup=get_mines_kb(data['side_size'], data['opened'], True, data['mines'], user_id=call.from_user.id, flagged=data.get('flagged', []))
    )
    await state.clear()