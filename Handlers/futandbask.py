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

class FootballState(StatesGroup):
    choosing_difficulty = State()
    playing_series = State()

class BasketState(StatesGroup):
    choosing_difficulty = State()
    playing_series = State()

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
    builder.button(text="🏠 В меню", callback_data="go:start")
    
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
    builder.button(text="🏠 В меню", callback_data="go:start")
    
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


SLOT_SYMBOLS = {
    1: "🍫", 2: "🍫", 3: "🍫", 4: "🍒",
    5: "🍫", 6: "🍫", 7: "🍒", 8: "🍋",
    9: "🍫", 10: "🍫", 11: "🍋", 12: "🍫",
    13: "🍫", 14: "🍋", 15: "🍒", 16: "🍫",
    17: "🍋", 18: "🍫", 19: "🍒", 20: "🍫",
    21: "🍫", 22: "🍒", 23: "🍫", 24: "🍫",
    25: "🍫", 26: "🍒", 27: "🍋", 28: "🍫",
    29: "🍫", 30: "🍋", 31: "🍒", 32: "🍫",
    33: "🍒", 34: "🍫", 35: "🍫", 36: "🍫",
    37: "🍫", 38: "🍋", 39: "🍋", 40: "🍫",
    41: "🍫", 42: "🍒", 43: "🍋", 44: "🍫",
    45: "🍫", 46: "🍋", 47: "🍫", 48: "🍒",
    49: "🍫", 50: "🍫", 51: "🍫", 52: "🍒",
    53: "🍫", 54: "🍫", 55: "🍒", 56: "🍋",
    57: "🍫", 58: "🍫", 59: "🍋", 60: "🍫",
    61: "🍫", 62: "🍫", 63: "🍋", 64: "7️⃣",
}

SLOT_TRIPLES = {
    1:  {"reels": "🍫🍫🍫", "name": "Три шоколадки",   "coeff": 10},
    22: {"reels": "🍒🍒🍒", "name": "Три вишни",       "coeff": 20},
    43: {"reels": "🍋🍋🍋", "name": "Три лимона",      "coeff": 30},
    64: {"reels": "7️⃣7️⃣7️⃣", "name": "Джекпот 777",  "coeff": 77},
}


def slot_result(value: int) -> dict:
    """Раскладывает значение Telegram-дайса 🎰 (1..64) в результат слота."""
    if value in SLOT_TRIPLES:
        data = SLOT_TRIPLES[value]
        return {"reels": data["reels"], "name": data["name"], "coeff": data["coeff"]}

    v = value - 1
    reels = [SLOT_SYMBOLS[(v % 4) + 1],
             SLOT_SYMBOLS[((v // 4) % 4) + 1],
             SLOT_SYMBOLS[((v // 16) % 4) + 1]]
    counts = {s: reels.count(s) for s in reels}

    if counts.get("7️⃣", 0) == 2:
        return {"reels": "".join(reels), "name": "Два семёрки", "coeff": 5}
    if counts.get("🍒", 0) == 2:
        return {"reels": "".join(reels), "name": "Две вишни", "coeff": 3}
    if counts.get("🍋", 0) == 2:
        return {"reels": "".join(reels), "name": "Два лимона", "coeff": 2}
    if counts.get("🍫", 0) == 2:
        return {"reels": "".join(reels), "name": "Две шоколадки", "coeff": 1}
    return {"reels": "".join(reels), "name": "Мимо", "coeff": 0}


@router.message(Command("slot", "slots"))
async def play_slots(message: types.Message):
    user_data = await check_user(message)
    if not user_data:
        return

    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        return await message.reply(
            "🎰 <b>Слоты</b>\n"
            "Формат: <code>/slot [ставка]</code>\n\n"
            "Выплаты за комбинации:\n"
            "• 🍫🍫🍫 — x10\n"
            "• 🍒🍒🍒 — x20\n"
            "• 🍋🍋🍋 — x30\n"
            "• 7️⃣7️⃣7️⃣ — x77 (джекпот)\n"
            "• Две семёрки — x5\n"
            "• Две вишни — x3\n"
            "• Два лимона — x2\n"
            "• Две шоколадки — x1 (возврат ставки)",
            parse_mode="HTML",
        )

    bet = int(args[1])

    is_no_limit = user_data[9] == 777
    if not is_no_limit and bet > 1_000_000:
        return await message.reply("❌ Максимальная ставка — 1 000 000 💎")

    if bet > user_data[0] or bet < 10:
        return await message.reply(f"❌ Некорректная ставка. Баланс: {user_data[0]:,}")

    await play_single_slot(message, bet)


async def play_single_slot(message: types.Message, bet: int):
    user_id = message.from_user.id
    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute("SELECT balance FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if not row or row[0] < bet:
            cursor.execute("ROLLBACK")
            return await message.reply("❌ Недостаточно средств.")
        cursor.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (bet, user_id))
        conn.commit()
    except Exception:
        cursor.execute("ROLLBACK")
        logger.exception("Слоты: не удалось списать ставку")
        return await message.reply("❌ Ошибка. Попробуй ещё раз.")

    dice_msg = await message.answer_dice(emoji="🎰")
    await asyncio.sleep(2.5)

    result = slot_result(dice_msg.dice.value)
    payout = int(bet * result["coeff"])
    db_update_stats(user_id, bet, payout, deducted=True)

    new_balance = db_get_user(user_id)[0]

    if result["coeff"] >= 2:
        header = "🎉 <b>ВЫИГРЫШ</b>"
    elif result["coeff"] == 1:
        header = "↩️ <b>ВОЗВРАТ</b>"
    else:
        header = "❌ <b>Мимо</b>"

    text = (
        f"{header}\n\n"
        f"🎰 {result['reels']}\n"
        f"▶️ {result['name']}  •  x{result['coeff']}\n"
        f"{'+' if payout - bet >= 0 else ''}{payout - bet:,} 💎\n\n"
        f"💳 Баланс: {new_balance:,} 💎"
    )

    kb = InlineKeyboardBuilder()
    kb.button(text=f"🔄 Ещё за {bet:,}", callback_data=f"replay_slot:{bet}")
    kb.button(text="✖️ x2 ставку", callback_data=f"replay_slot:{bet * 2}")
    kb.button(text="🏠 В меню", callback_data="go:start")
    kb.adjust(1, 1, 1)

    try:
        await message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        await message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")


@router.callback_query(F.data.startswith("replay_slot:"))
async def replay_slot(call: types.CallbackQuery):
    await call.answer()
    bet = int(call.data.split(":")[1])
    user_data = await check_user(call.message)
    if not user_data or user_data[0] < bet:
        return await call.message.answer("❌ Недостаточно средств для повтора.")
    await play_single_slot(call.message, bet)

@router.callback_query(F.data == "back_to_profile")
async def go_back_to_profile(call: types.CallbackQuery, state: FSMContext):
    """Возврат в профиль и удаление игрового сообщения"""
    await state.clear()
    await call.answer("Возвращаемся в профиль...")
    
    try:
        await call.message.delete()
    except Exception:
        pass

    from Handlers.common import _profile_text
    text = _profile_text(call.from_user.id)
    await call.message.answer(text, parse_mode="Markdown")