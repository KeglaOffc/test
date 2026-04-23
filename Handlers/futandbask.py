import asyncio
import random
import time
import logging
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramRetryAfter 
from database import db_get_user, db_update_stats, cursor, conn
from Handlers.common import check_user 

logger = logging.getLogger(__name__)
router = Router()

# Защита от spam
FOOTBALL_COOLDOWN = {}

# === СОСТОЯНИЯ ДЛЯ ФУТБОЛА И БАСКЕТА ===
class FootballState(StatesGroup):
    choosing_difficulty = State()
    playing_series = State()

class BasketState(StatesGroup):
    choosing_difficulty = State()
    playing_series = State()

# === КОНСТАНТЫ СЛОЖНОСТИ ===
DIFFICULTY_SETTINGS = {
    "1": {"name": "🟢 Легко", "wins": [3, 4, 5], "coeff": 1.5, "color": "🟢"},
    "2": {"name": "🔵 Нормально", "wins": [4, 5], "coeff": 1.8, "color": "🔵"},
    "3": {"name": "🟠 Сложно", "wins": [5], "coeff": 2.5, "color": "🟠"},
    "4": {"name": "🔴 Сложнейше", "wins": [4, 5], "coeff": 3.0, "color": "🔴"},
    "5": {"name": "⚫ ЭКСТРИМ", "wins": [5], "coeff": 5.0, "color": "⚫"},
}

DIFFICULTY_SETTINGS_BASKET = {
    "1": {"name": "🟢 Легко", "wins": [4, 5], "coeff": 1.5, "color": "🟢"},
    "2": {"name": "🔵 Нормально", "wins": [4, 5], "coeff": 1.8, "color": "🔵"},
    "3": {"name": "🟠 Сложно", "wins": [5], "coeff": 2.5, "color": "🟠"},
    "4": {"name": "🔴 Сложнейше", "wins": [5], "coeff": 3.0, "color": "🔴"},
    "5": {"name": "⚫ ЭКСТРИМ", "wins": [5], "coeff": 5.0, "color": "⚫"},
}

# === ФУТБОЛ ===
@router.message(Command("football"))
async def football_start(message: types.Message, state: FSMContext):
    user_data = await check_user(message)
    if not user_data: return
    
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        return await message.reply("📝 Формат: /football [ставка]")
    
    bet = int(args[1])
    
    is_no_limit = user_data[9] == 777
    if not is_no_limit and bet > 1000000:
        return await message.reply("❌ Максимальная ставка — 1,000,000 💎")
    
    if bet > user_data[0] or bet < 10:
        return await message.reply(f"❌ Некорректная ставка. Баланс: {user_data[0]:,}")

    # Настройки выплат (ключ - количество голов, значение - множитель)
    payouts = {
        0: 0.0,
        1: 0.0,
        2: 0.5,
        3: 1.2,
        4: 1.8,
        5: 3.5
    }
    
    settings = {"name": "Стандарт", "wins": [3, 4, 5], "payouts": payouts}
    
    await state.update_data(bet=bet, game_type="football", wins=0, losses=0, settings=settings)
    
    await message.answer(
        f"⚽ **СЕРИЯ ПЕНАЛЬТИ** (5 попыток)\n\n"
        f"🎯 **Таблица выплат:**\n"
        f"0-1 гол: x0\n"
        f"2 гола: x0.5\n"
        f"3 гола: x1.2\n"
        f"4 гола: x1.8\n"
        f"5 голов: x3.5\n\n"
        f"Ставка: {bet:,} 💎\n"
        f"🔴 Приготовьтесь! Начинаем серию...",
        parse_mode="Markdown"
    )
    await state.set_state(FootballState.playing_series)
    await asyncio.sleep(2)
    
    # Запускаем серию из 5 пенальти
    await football_penalty_series(message, state)

async def football_penalty_series(event: types.Message | types.CallbackQuery, state: FSMContext):
    # Определяем message и user_id
    if isinstance(event, types.CallbackQuery):
        message = event.message
        user_id = event.from_user.id
    else:
        message = event
        user_id = event.from_user.id

    data = await state.get_data()
    bet = data['bet']
    settings = data['settings']
    win_values = settings['wins']
    
    # ИСПОЛЬЗУЕМ ТРАНЗАКЦИЮ для защиты от дюпов
    try:
        cursor.execute("BEGIN IMMEDIATE")
        
        # Проверяем баланс внутри транзакции
        cursor.execute("SELECT balance FROM users WHERE id = ?", (user_id,))
        res = cursor.fetchone()
        if not res or res[0] < bet:
            cursor.execute("ROLLBACK")
            await message.answer("❌ Недостаточно средств!")
            await state.clear()
            return
        
        # Списываем ставку АТОМАРНО
        cursor.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (bet, user_id))
        conn.commit()
        
    except Exception as e:
        cursor.execute("ROLLBACK")
        logger.error(f"Error in football_penalty_series transaction: {e}")
        await message.answer("❌ Ошибка при запуске игры.")
        await state.clear()
        return
    
    wins = 0
    losses = 0
    results_text = "⚽ **РЕЗУЛЬТАТЫ СЕРИИ:**\n\n"
    
    try:
        for attempt in range(1, 6):
            # Отправляем дайс
            msg = await message.answer_dice(emoji="⚽")
            val = msg.dice.value
            
            await asyncio.sleep(3.5)
            
            if val in win_values:
                wins += 1
                results_text += f"✅ Попытка {attempt}: **ГОЛ!** ({val})\n"
            else:
                losses += 1
                results_text += f"❌ Попытка {attempt}: Мимо ({val})\n"
        
        # Расчет прибыли
        final_coeff = settings.get('payouts', {}).get(wins, 0)
        win_payout = int(bet * final_coeff)
        
        # ФИНАЛЬНАЯ ТРАНЗАКЦИЯ: добавляем выигрыш
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (win_payout, user_id))
        
        if win_payout > 0:
            cursor.execute("UPDATE users SET total_wins = total_wins + ? WHERE id = ?", (win_payout, user_id))
        cursor.execute("UPDATE users SET total_bets = total_bets + ? WHERE id = ?", (bet, user_id))
        
        cursor.execute("SELECT balance FROM users WHERE id = ?", (user_id,))
        new_balance = cursor.fetchone()[0]
        conn.commit()
        
        results_text += f"\n📊 Забито: {wins}/5\n"
        results_text += f"💰 Множитель: x{final_coeff:.2f}\n"
        results_text += f"🎁 Выигрыш: {win_payout:,} 💎\n"
        results_text += f"💳 Баланс: {new_balance:,} 💎"
        
    except Exception as e:
        cursor.execute("ROLLBACK")
        logger.error(f"Error in football_penalty_series game: {e}")
        # Возвращаем ставку если произошла ошибка
        cursor.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (bet, user_id))
        conn.commit()
        await message.answer(f"❌ Ошибка во время игры! Ставка возвращена.")
        await state.clear()
        return
    
    # Кнопка переиграть
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Переиграть", callback_data=f"replay_football:{bet}")
    builder.button(text="🏠 В меню", callback_data="back_to_profile")
    
    try:
        await message.answer(results_text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        await message.answer(results_text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@router.callback_query(F.data.startswith("replay_football:"))
async def replay_football(call: types.CallbackQuery, state: FSMContext):
    bet = int(call.data.split(":")[1])
    user_data = await check_user(call.message)
    if not user_data or user_data[0] < bet:
        return await call.answer("❌ Недостаточно средств!", show_alert=True)
    
    # Стандартные настройки
    payouts = {
        0: 0.0,
        1: 0.0,
        2: 0.5,
        3: 1.2,
        4: 1.8,
        5: 3.5
    }
    settings = {"name": "Стандарт", "wins": [3, 4, 5], "payouts": payouts}
    await state.update_data(bet=bet, game_type="football", settings=settings)
    
    await call.message.edit_text(
        f"⚽ **ПРОБИТЬ ПЕНАЛЬТИ** (переигровка)\n\n"
        f"Ставка: {bet:,} 💎\n"
        f"🎯 **Таблица выплат:**\n"
        f"0-1 гол: x0\n"
        f"2 гола: x0.5\n"
        f"3 гола: x1.2\n"
        f"4 гола: x1.8\n"
        f"5 голов: x3.5\n\n"
        f"🔴 Приготовьтесь! Начинаем серию...",
        parse_mode="Markdown"
    )
    
    await state.set_state(FootballState.playing_series)
    await asyncio.sleep(2)
    await football_penalty_series(call, state)

# === БАСКЕТ ===
@router.message(Command("basket"))
async def basket_start(message: types.Message, state: FSMContext):
    user_data = await check_user(message)
    if not user_data: return
    
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        return await message.reply("📝 Формат: /basket [ставка]")
    
    bet = int(args[1])
    
    is_no_limit = user_data[9] == 777
    if not is_no_limit and bet > 1000000:
        return await message.reply("❌ Максимальная ставка — 1,000,000 💎")
    
    if bet > user_data[0] or bet < 10:
        return await message.reply(f"❌ Некорректная ставка. Баланс: {user_data[0]:,}")

    # Настройки выплат (ключ - количество попаданий, значение - множитель)
    payouts = {
        0: 0.0,
        1: 0.0,
        2: 0.5,
        3: 1.5,
        4: 3.0,
        5: 10.0
    }
    
    settings = {"name": "Стандарт", "wins": [4, 5], "payouts": payouts}
    await state.update_data(bet=bet, game_type="basket", settings=settings)
    
    await message.answer(
        f"🏀 **БРОСОК В КОЛЬЦО**\n\n"
        f"🎯 **Таблица выплат:**\n"
        f"0-1 попадание: x0\n"
        f"2 попадания: x0.5\n"
        f"3 попадания: x1.5\n"
        f"4 попадания: x3.0\n"
        f"5 попаданий: x10.0\n\n"
        f"Ставка: {bet:,} 💎\n"
        f"🔴 Приготовьтесь! Начинаем серию...",
        parse_mode="Markdown"
    )
    await state.set_state(BasketState.playing_series)
    await asyncio.sleep(2)
    
    await basket_penalty_series(message, state)

async def basket_penalty_series(event: types.Message | types.CallbackQuery, state: FSMContext):
    # Определяем message и user_id
    if isinstance(event, types.CallbackQuery):
        message = event.message
        user_id = event.from_user.id
    else:
        message = event
        user_id = event.from_user.id

    data = await state.get_data()
    bet = data['bet']
    settings = data['settings']
    win_values = settings['wins']
    
    # Проверяем баланс перед игрой
    user_data = db_get_user(user_id)
    if not user_data or user_data[0] < bet:
        await message.answer("❌ Недостаточно средств!")
        await state.clear()
        return
    
    # Вычитаем ставку со счета ДО игры
    cursor.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (bet, user_id))
    conn.commit()
    
    wins = 0
    losses = 0
    results_text = "🏀 **РЕЗУЛЬТАТЫ СЕРИИ:**\n\n"
    
    for attempt in range(1, 6):
        msg = await message.answer_dice(emoji="🏀")
        val = msg.dice.value
        
        await asyncio.sleep(3.5)
        
        if val in win_values:
            wins += 1
            results_text += f"✅ Попытка {attempt}: **ПОПАДАНИЕ!** ({val})\n"
        else:
            losses += 1
            results_text += f"❌ Попытка {attempt}: Мимо ({val})\n"
    
    final_coeff = settings.get('payouts', {}).get(wins, 0)
    win_payout = int(bet * final_coeff)
    
    # Добавляем выигрыш (ставка уже вычтена выше)
    db_update_stats(user_id, bet, win_payout, deducted=True)
    
    new_balance = db_get_user(user_id)[0]
    
    results_text += f"\n📊 Попадания: {wins}/5\n"
    results_text += f"💰 Множитель: x{final_coeff:.2f}\n"
    results_text += f"🎁 Выигрыш: {win_payout:,} 💎\n"
    results_text += f"💳 Баланс: {new_balance:,} 💎"
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Переиграть", callback_data=f"replay_basket:{bet}")
    builder.button(text="🏠 В меню", callback_data="back_to_profile")
    
    try:
        await message.answer(results_text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        await message.answer(results_text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@router.callback_query(F.data.startswith("replay_basket:"))
async def replay_basket(call: types.CallbackQuery, state: FSMContext):
    bet = int(call.data.split(":")[1])
    user_data = await check_user(call.message)
    if not user_data or user_data[0] < bet:
        return await call.answer("❌ Недостаточно средств!", show_alert=True)
    
    payouts = {
        0: 0.0,
        1: 0.0,
        2: 0.5,
        3: 1.5,
        4: 3.0,
        5: 10.0
    }
    settings = {"name": "Стандарт", "wins": [4, 5], "payouts": payouts}
    await state.update_data(bet=bet, game_type="basket", settings=settings)
    
    await call.message.edit_text(
        f"🏀 **БРОСОК В КОЛЬЦО** (переигровка)\n\n"
        f"Ставка: {bet:,} 💎\n"
        f"🎯 **Таблица выплат:**\n"
        f"0-1 попаданий: x0\n"
        f"2 попадания: x0.5\n"
        f"3 попадания: x1.5\n"
        f"4 попадания: x3.0\n"
        f"5 попаданий: x10.0\n\n"
        f"🔴 Приготовьтесь! Начинаем серию...",
        parse_mode="Markdown"
    )
    await state.set_state(BasketState.playing_series)
    await asyncio.sleep(2)
    
    await basket_penalty_series(call, state)

# === SLOT (Новая система с комбинациями и двойным режимом) ===

# Выигрышные комбинации слотов
SLOT_COMBINATIONS = {
    "🍒🍒🍒": {"name": "ТРОЙНАЯ ВИШНЯ", "coeff": 10, "icon": "🍒💎🍒"},
    "🍋🍋🍋": {"name": "ТРОЙНОЙ ЛИМОН", "coeff": 8, "icon": "🍋✨🍋"},
    "🍊🍊🍊": {"name": "ТРОЙНОЙ АПЕЛЬСИН", "coeff": 6, "icon": "🍊🎯🍊"},
    "🔔🔔🔔": {"name": "ТРОЙНОЙ КОЛОКОЛ", "coeff": 5, "icon": "🔔💫🔔"},
    "7️⃣7️⃣7️⃣": {"name": "ТРОЙНАЯ СЕМЁРКА", "coeff": 15, "icon": "🎰🌟🎰"},
    "💰💰💰": {"name": "ТРОЙНОЙ ДЖЕКПОТ", "coeff": 20, "icon": "💰🔥💰"},
    # Двойные комбинации (малые выигрыши)
    "🍒🍒": {"name": "ДВЕ ВИШНИ", "coeff": 2, "icon": "🍒🍒"},
    "7️⃣7️⃣": {"name": "ДВЕ СЕМЁРКИ", "coeff": 3, "icon": "7️⃣7️⃣"},
}

@router.message(Command("slot", "slots"))
async def play_slots(message: types.Message):
    user_data = await check_user(message)
    if not user_data: return
    
    args = message.text.split()
    if len(args) < 2:
        return await message.reply("📝 Формат: /slot [ставка] [режим]\n/slot 1000 - одиночная крутка\n/slot 1000 double - двойная крутка (x3 при 2 выигрышах)")
    
    if not args[1].isdigit():
        return await message.reply("❌ Ставка должна быть числом!")
    
    bet = int(args[1])

    is_no_limit = user_data[9] == 777
    if not is_no_limit and bet > 1000000:
        return await message.reply("❌ Максимальная ставка — 1,000,000 💎")

    if bet > user_data[0] or bet < 10:
        return await message.reply(
            f"❌ Некорректная ставка. Баланс: {user_data[0]:,}"
        )

    await play_single_slot(message, bet, user_data)

async def play_single_slot(message: types.Message, bet: int, user_data: tuple):
    """Одиночная крутка слота"""
    try:
        # Честная игра - 30% на выигрыш + бонус от клевера (rig_prob)
        # rig_prob по умолчанию 50. Каждые +5 дают +5% к шансу.
        base_chance = 0.30
        luck_bonus = max(0, (user_data[1] - 50) * 0.01)
        final_chance = min(0.60, base_chance + luck_bonus) # Максимум 60% шанс
        
        if random.random() < final_chance:
            combo = random.choice(list(SLOT_COMBINATIONS.keys()))
        else:
            combo = random.choice(["🍓🍌🍇", "🎭🎪🎨", "🌟🌙⭐", "🎯🎲🎰"])
        
        # Вычитаем ставку
        cursor.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (bet, message.from_user.id))
        conn.commit()
        
        # Отправляем анимацию
        msg = await message.answer_dice(emoji="🎰")
        await asyncio.sleep(3.5)
        
        # Проверяем выигрыш
        if combo in SLOT_COMBINATIONS:
            combo_data = SLOT_COMBINATIONS[combo]
            win_payout = int(bet * combo_data["coeff"])
            
            # Добавляем выигрыш
            db_update_stats(message.from_user.id, bet, win_payout, deducted=True)
            
            result_text = f"🎰 **{combo_data['icon']} ВЫИГРЫШ!** 🎰\n\n"
            result_text += f"🏆 Комбинация: {combo_data['name']}\n"
            result_text += f"💰 Множитель: x{combo_data['coeff']}\n"
            result_text += f"💎 Выигрыш: +{win_payout:,} 💎\n"
        else:
            db_update_stats(message.from_user.id, bet, 0, deducted=True)
            result_text = f"❌ **ПРОИГРЫШ** {combo}\n\n"
            result_text += f"💎 Ставка: -{bet:,} 💎\n"
        
        new_balance = db_get_user(message.from_user.id)[0]
        result_text += f"\n💳 Баланс: {new_balance:,} 💎"
        
        builder = InlineKeyboardBuilder()
        builder.button(text="🔄 Переиграть", callback_data=f"replay_slot:{bet}")
        builder.button(text="🏠 В меню", callback_data="back_to_profile")
        builder.adjust(1)
        
        try:
            await message.answer(result_text, reply_markup=builder.as_markup(), parse_mode="Markdown")
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            await message.answer(result_text, reply_markup=builder.as_markup(), parse_mode="Markdown")
        except Exception as e:
            await message.answer(f"❌ Ошибка отправки: {str(e)}\n\nРезультат:\n{result_text}", parse_mode="Markdown")
    except Exception as e:
        import logging
        logging.error(f"Ошибка в play_single_slot: {str(e)}")
        await message.answer(f"❌ Ошибка в игре слотов: {str(e)}", parse_mode="Markdown")

@router.callback_query(F.data.startswith("replay_slot:"))
async def replay_slot(call: types.CallbackQuery):
    bet = int(call.data.split(":")[1])
    user_data = await check_user(call.message)
    if not user_data or user_data[0] < bet:
        return await call.answer("❌ Недостаточно средств!", show_alert=True)
    
    await play_single_slot(call.message, bet, user_data)

# === Обработчик кнопки "В меню" ===
@router.callback_query(F.data == "back_to_profile")
async def go_back_to_profile(call: types.CallbackQuery, state: FSMContext):
    """Возврат в профиль и удаление игрового сообщения"""
    await state.clear()
    await call.answer("Возвращаемся в профиль...")
    
    try:
        await call.message.delete()
    except:
        pass
    
    # Отправляем новое сообщение вместо reply на удалённое
    from Handlers.common import cmd_start
    
    # Создаём новое сообщение вместо reply
    user_id = call.from_user.id
    user_data = db_get_user(user_id)
    
    if not user_data:
        return await call.message.answer("❌ Ошибка данных пользователя")
    
    u = user_data
    
    boost_text = "✅ Активен" if u[6] > 0 else "❌ Нет"
    
    text = (
        f"👤 **ПРОФИЛЬ** {call.from_user.first_name}\n"
        f"ID: `{user_id}`\n\n"
        f"💰 Баланс: `{u[0]:,}` 💎\n\n"
        f"📊 **СТАТИСТИКА:**\n"
        f"┃ 🎮 Игр сыграно: `{u[5]}`\n"
        f"┃ 🏆 Всего выиграно: `{u[4]:,}` 💎\n"
        f"┃ 📈 Всего ставлено: `{u[3]:,}` 💎\n"
        f"┃ ⚡️ X2 Буст: `{boost_text}`\n"
        f"┃\n"
        f"┃ 🎒 **ИНВЕНТАРЬ:**\n"
        f"┃ 🛡 Щиты: `{u[7] if len(u) > 7 else 0}` | 🔍 Сканеры: `{u[8] if len(u) > 8 else 0}`\n"
        f"┃ 🔄 Рэроллы: `{u[9] if len(u) > 9 else 0}` | ⚡️ Энергетики: `{u[10] if len(u) > 10 else 0}`\n"
        f"┃ 🎟 Золотой билет: `{'✅ Есть' if u[11] and u[11] > 0 else '❌ Нет'}`\n"
        f"———————————————————\n"
        f"🆘 *Помощь по командам:* `/help`"
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🎮 Игры", callback_data="games_menu")
    builder.button(text="🏪 Магазин", callback_data="shop:back")
    builder.button(text="🏆 Лидеры", callback_data="qtop")
    builder.adjust(2, 1)
    
    try:
        await call.message.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    except Exception as e:
        await call.message.answer(f"✅ Добро пожаловать в профиль!\n\n/help для справки", parse_mode="Markdown")