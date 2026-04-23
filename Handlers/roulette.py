"""Классическая европейская рулетка с одним зеро."""
import asyncio
import logging
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


RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
BLACK_NUMBERS = set(range(1, 37)) - RED_NUMBERS


class RouletteState(StatesGroup):
    waiting_bet = State()


def describe_number(n: int) -> str:
    if n == 0:
        return "🟢 0 (зеро)"
    color = "🔴" if n in RED_NUMBERS else "⚫"
    parity = "чёт" if n % 2 == 0 else "нечет"
    half = "1-18" if n <= 18 else "19-36"
    return f"{color} {n} ({parity}, {half})"


def payout(bet_type: str, bet_value: str, n: int) -> int:
    """Возвращает множитель выплаты (0 = проигрыш). Европейская рулетка, 0 — всегда проигрыш, кроме прямой ставки."""
    if bet_type == "num":
        target = int(bet_value)
        return 36 if n == target else 0
    if n == 0:
        return 0
    if bet_type == "color":
        if bet_value == "red" and n in RED_NUMBERS:
            return 2
        if bet_value == "black" and n in BLACK_NUMBERS:
            return 2
        return 0
    if bet_type == "parity":
        if bet_value == "even" and n % 2 == 0:
            return 2
        if bet_value == "odd" and n % 2 == 1:
            return 2
        return 0
    if bet_type == "half":
        if bet_value == "low" and 1 <= n <= 18:
            return 2
        if bet_value == "high" and 19 <= n <= 36:
            return 2
        return 0
    if bet_type == "dozen":
        ranges = {"d1": (1, 12), "d2": (13, 24), "d3": (25, 36)}
        lo, hi = ranges.get(bet_value, (0, 0))
        return 3 if lo <= n <= hi else 0
    return 0


def bet_kb(bet: int) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔴 Красное (x2)", callback_data=f"rl:color:red:{bet}")
    kb.button(text="⚫ Чёрное (x2)", callback_data=f"rl:color:black:{bet}")
    kb.button(text="Чёт (x2)",   callback_data=f"rl:parity:even:{bet}")
    kb.button(text="Нечет (x2)", callback_data=f"rl:parity:odd:{bet}")
    kb.button(text="1-18 (x2)",  callback_data=f"rl:half:low:{bet}")
    kb.button(text="19-36 (x2)", callback_data=f"rl:half:high:{bet}")
    kb.button(text="1-12 (x3)",  callback_data=f"rl:dozen:d1:{bet}")
    kb.button(text="13-24 (x3)", callback_data=f"rl:dozen:d2:{bet}")
    kb.button(text="25-36 (x3)", callback_data=f"rl:dozen:d3:{bet}")
    kb.button(text="🎯 На число (x36)", callback_data=f"rl:pick:{bet}")
    kb.adjust(2, 2, 2, 3, 1)
    return kb


@router.message(Command("roulette", "rl"))
async def roulette_start(message: types.Message):
    user_data = await check_user(message)
    if not user_data:
        return

    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        return await message.reply(
            "🎡 <b>Рулетка</b>\n"
            "Формат: <code>/roulette [ставка]</code>\n\n"
            "Выплаты:\n"
            "• Цвет / чёт-нечет / 1-18 / 19-36 — <b>x2</b>\n"
            "• Дюжина (1-12, 13-24, 25-36) — <b>x3</b>\n"
            "• Прямая ставка на число — <b>x36</b>\n"
            "• 0 — проигрыш для всех ставок кроме прямой на 0",
            parse_mode="HTML",
        )

    bet = int(args[1])
    if bet < 10:
        return await message.reply("❌ Минимальная ставка — 10 💎.")
    if bet > user_data[0]:
        return await message.reply(f"❌ Недостаточно средств. Баланс: {user_data[0]:,} 💎")
    if bet > 2_000_000:
        return await message.reply("❌ Максимальная ставка — 2 000 000 💎.")

    await message.answer(
        f"🎡 <b>Рулетка</b>\nСтавка: <b>{bet:,}</b> 💎\n\nВыбери тип ставки:",
        reply_markup=bet_kb(bet).as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("rl:pick:"))
async def roulette_pick_number(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    bet = int(call.data.split(":")[2])
    await state.set_state(RouletteState.waiting_bet)
    await state.update_data(bet=bet)
    await call.message.answer(
        f"🎯 Введи число от 0 до 36 на которое ставишь {bet:,} 💎.\nВыигрыш x36."
    )


@router.message(RouletteState.waiting_bet)
async def roulette_pick_number_value(message: types.Message, state: FSMContext):
    data = await state.get_data()
    bet = data.get("bet", 0)
    await state.clear()

    if not message.text or not message.text.isdigit():
        return await message.reply("❌ Нужно прислать число от 0 до 36.")
    n = int(message.text)
    if n < 0 or n > 36:
        return await message.reply("❌ Число должно быть в диапазоне 0–36.")

    await resolve_spin(message, message.from_user.id, bet, "num", str(n))


@router.callback_query(F.data.regexp(r"^rl:(color|parity|half|dozen):[^:]+:\d+$"))
async def roulette_resolve_simple(call: types.CallbackQuery):
    await call.answer()
    _, bet_type, bet_value, bet_str = call.data.split(":")
    bet = int(bet_str)
    await resolve_spin(call.message, call.from_user.id, bet, bet_type, bet_value)


async def resolve_spin(target, user_id: int, bet: int, bet_type: str, bet_value: str):
    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute("SELECT balance FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if not row or row[0] < bet:
            cursor.execute("ROLLBACK")
            return await target.answer("❌ Недостаточно средств.")
        cursor.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (bet, user_id))
        conn.commit()
    except Exception:
        cursor.execute("ROLLBACK")
        logger.exception("roulette: ошибка списания ставки")
        return await target.answer("❌ Ошибка, попробуй ещё раз.")

    spin_msg = await target.answer("🎡 Крутится барабан…")
    await asyncio.sleep(1.2)

    n = random.randint(0, 36)
    mult = payout(bet_type, bet_value, n)
    win = bet * mult
    db_update_stats(user_id, bet, win, deducted=True)

    new_balance = db_get_user(user_id)[0]
    delta = win - bet
    status = "🎉 ПОБЕДА" if mult > 0 else "❌ Проигрыш"

    text = (
        f"🎡 <b>Выпало: {describe_number(n)}</b>\n\n"
        f"{status}  •  множитель x{mult}\n"
        f"{'+' if delta >= 0 else ''}{delta:,} 💎\n"
        f"💳 Баланс: {new_balance:,} 💎"
    )

    kb = InlineKeyboardBuilder()
    kb.button(text=f"🔄 Ещё раз за {bet:,}", callback_data=f"rl_again:{bet}")
    kb.adjust(1)
    try:
        await spin_msg.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    except Exception:
        await target.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")


@router.callback_query(F.data.startswith("rl_again:"))
async def roulette_again(call: types.CallbackQuery):
    await call.answer()
    bet = int(call.data.split(":")[1])
    user_data = db_get_user(call.from_user.id)
    if not user_data or user_data[0] < bet:
        return await call.message.answer("❌ Недостаточно средств.")
    await call.message.answer(
        f"🎡 Ставка: <b>{bet:,}</b> 💎\nВыбери тип ставки:",
        reply_markup=bet_kb(bet).as_markup(),
        parse_mode="HTML",
    )
