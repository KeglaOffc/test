"""Европейская рулетка. Игрок собирает набор ставок, потом крутит барабан."""
import asyncio
import logging
import random
from typing import Any, Dict, List

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

MIN_STAKE = 10
MAX_BETS = 8


class RouletteState(StatesGroup):
    building = State()
    picking_number = State()


def describe_number(n: int) -> str:
    if n == 0:
        return "🟢 0"
    color = "🔴" if n in RED_NUMBERS else "⚫"
    parity = "чёт" if n % 2 == 0 else "нечет"
    half = "1-18" if n <= 18 else "19-36"
    return f"{color} {n} ({parity}, {half})"


def bet_label(bet_type: str, bet_value: str) -> str:
    if bet_type == "color":
        return {"red": "🔴 Красное", "black": "⚫ Чёрное"}[bet_value]
    if bet_type == "parity":
        return {"even": "🔢 Чёт", "odd": "🎯 Нечет"}[bet_value]
    if bet_type == "half":
        return {"low": "1-18", "high": "19-36"}[bet_value]
    if bet_type == "dozen":
        return {"d1": "1-12", "d2": "13-24", "d3": "25-36"}[bet_value]
    if bet_type == "num":
        return f"🎯 Число {bet_value}"
    return "?"


def bet_multiplier(bet_type: str, bet_value: str, n: int) -> int:
    """Возвращает множитель для итогового зачисления. 0 = проигрыш."""
    if bet_type == "num":
        return 36 if n == int(bet_value) else 0
    if n == 0:
        return 0
    if bet_type == "color":
        ok = (bet_value == "red" and n in RED_NUMBERS) or (
            bet_value == "black" and n in BLACK_NUMBERS
        )
        return 2 if ok else 0
    if bet_type == "parity":
        ok = (bet_value == "even" and n % 2 == 0) or (
            bet_value == "odd" and n % 2 == 1
        )
        return 2 if ok else 0
    if bet_type == "half":
        ok = (bet_value == "low" and n <= 18) or (bet_value == "high" and n >= 19)
        return 2 if ok else 0
    if bet_type == "dozen":
        rng = {"d1": (1, 12), "d2": (13, 24), "d3": (25, 36)}.get(bet_value)
        if rng and rng[0] <= n <= rng[1]:
            return 3
        return 0
    return 0


def build_menu_text(base_stake: int, bets: List[Dict[str, Any]]) -> str:
    lines = ["🎡 <b>Рулетка</b>"]
    lines.append(f"Ставка на поле: <b>{base_stake:,}</b> 💎")
    if not bets:
        lines.append("\nНи одного поля не выбрано.")
        lines.append("Тыкай кнопки ниже — можно поставить на несколько полей сразу.")
    else:
        total = base_stake * len(bets)
        lines.append(f"\n<b>Поля ({len(bets)}/{MAX_BETS}):</b>")
        for b in bets:
            lines.append(f"• {bet_label(b['type'], b['value'])}")
        lines.append(f"\nИтого к списанию: <b>{total:,}</b> 💎")
    return "\n".join(lines)


def build_menu_kb(bets: List[Dict[str, Any]]) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔴 Красное",   callback_data="rl:add:color:red")
    kb.button(text="⚫ Чёрное",    callback_data="rl:add:color:black")
    kb.button(text="Чёт",          callback_data="rl:add:parity:even")
    kb.button(text="Нечет",        callback_data="rl:add:parity:odd")
    kb.button(text="1-18",         callback_data="rl:add:half:low")
    kb.button(text="19-36",        callback_data="rl:add:half:high")
    kb.button(text="1-12",         callback_data="rl:add:dozen:d1")
    kb.button(text="13-24",        callback_data="rl:add:dozen:d2")
    kb.button(text="25-36",        callback_data="rl:add:dozen:d3")
    kb.button(text="🎯 На число",   callback_data="rl:pick_number")
    if bets:
        kb.button(text=f"🎰 Крутить ({len(bets)})", callback_data="rl:spin")
        kb.button(text="🗑 Очистить",               callback_data="rl:clear")
    kb.button(text="✖️ Отмена", callback_data="rl:cancel")
    kb.adjust(2, 2, 2, 3, 1, 2, 1)
    return kb


@router.message(Command("roulette", "rl"))
async def roulette_start(message: types.Message, state: FSMContext):
    user_data = await check_user(message)
    if not user_data:
        return

    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        return await message.reply(
            "🎡 <b>Рулетка</b>\n"
            "Формат: <code>/roulette [ставка]</code>\n\n"
            "Выплаты (на каждое поле ставишь одну и ту же сумму):\n"
            "• Цвет / чёт-нечет / 1-18 / 19-36 — <b>x2</b>\n"
            "• Дюжина (1-12, 13-24, 25-36) — <b>x3</b>\n"
            "• Прямая ставка на число — <b>x36</b>\n"
            "• На 0 всё кроме прямой ставки сгорает.",
            parse_mode="HTML",
        )

    bet = int(args[1])
    if bet < MIN_STAKE:
        return await message.reply(f"❌ Минимальная ставка — {MIN_STAKE} 💎.")
    if bet > 2_000_000:
        return await message.reply("❌ Максимальная ставка на поле — 2 000 000 💎.")
    if bet > user_data[0]:
        return await message.reply(f"❌ Недостаточно средств. Баланс: {user_data[0]:,} 💎")

    await state.clear()
    await state.set_state(RouletteState.building)
    await state.update_data(base_stake=bet, bets=[])

    await message.answer(
        build_menu_text(bet, []),
        reply_markup=build_menu_kb([]).as_markup(),
        parse_mode="HTML",
    )


async def _refresh_menu(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    base_stake = data.get("base_stake", 0)
    bets = data.get("bets", [])
    try:
        await call.message.edit_text(
            build_menu_text(base_stake, bets),
            reply_markup=build_menu_kb(bets).as_markup(),
            parse_mode="HTML",
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("rl:add:"), RouletteState.building)
async def rl_add_bet(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    parts = call.data.split(":")
    bet_type, bet_value = parts[2], parts[3]
    data = await state.get_data()
    bets: List[Dict[str, Any]] = data.get("bets", [])

    if any(b["type"] == bet_type and b["value"] == bet_value for b in bets):
        return await call.answer("Это поле уже выбрано.", show_alert=False)
    if len(bets) >= MAX_BETS:
        return await call.answer(f"Максимум {MAX_BETS} полей за раз.", show_alert=True)

    bets.append({"type": bet_type, "value": bet_value})
    await state.update_data(bets=bets)
    await _refresh_menu(call, state)


@router.callback_query(F.data == "rl:pick_number", RouletteState.building)
async def rl_pick_number(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(RouletteState.picking_number)
    await call.message.answer(
        "🎯 Напиши число от 0 до 36 — на него поставим сумму поля.\n"
        "Команда /cancel — отмена."
    )


@router.message(RouletteState.picking_number, Command("cancel"))
async def rl_cancel_number(message: types.Message, state: FSMContext):
    await state.set_state(RouletteState.building)
    await message.answer("Ок, возврат в меню.")


@router.message(RouletteState.picking_number)
async def rl_receive_number(message: types.Message, state: FSMContext):
    if not message.text or not message.text.strip().lstrip("-").isdigit():
        return await message.reply("Нужно число 0–36.")
    n = int(message.text.strip())
    if n < 0 or n > 36:
        return await message.reply("Число должно быть 0–36.")

    data = await state.get_data()
    bets: List[Dict[str, Any]] = data.get("bets", [])
    if any(b["type"] == "num" and b["value"] == str(n) for b in bets):
        await state.set_state(RouletteState.building)
        return await message.reply("Это число уже в списке. Возврат в меню.")
    if len(bets) >= MAX_BETS:
        await state.set_state(RouletteState.building)
        return await message.reply(f"Максимум {MAX_BETS} полей. Возврат в меню.")

    bets.append({"type": "num", "value": str(n)})
    base_stake = data.get("base_stake", 0)
    await state.update_data(bets=bets)
    await state.set_state(RouletteState.building)
    await message.answer(
        build_menu_text(base_stake, bets),
        reply_markup=build_menu_kb(bets).as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "rl:clear", RouletteState.building)
async def rl_clear(call: types.CallbackQuery, state: FSMContext):
    await call.answer("Поля очищены.")
    await state.update_data(bets=[])
    await _refresh_menu(call, state)


@router.callback_query(F.data == "rl:cancel")
async def rl_cancel(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.clear()
    try:
        await call.message.edit_text("🎡 Игра отменена. Запусти /roulette чтобы начать заново.")
    except Exception:
        pass


@router.callback_query(F.data == "rl:spin", RouletteState.building)
async def rl_spin(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    user_id = call.from_user.id
    data = await state.get_data()
    base_stake: int = data.get("base_stake", 0)
    bets: List[Dict[str, Any]] = data.get("bets", [])

    if not bets or base_stake <= 0:
        return

    total_stake = base_stake * len(bets)

    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            "UPDATE users SET balance = balance - ? WHERE id = ? AND balance >= ?",
            (total_stake, user_id, total_stake),
        )
        if cursor.rowcount == 0:
            cursor.execute("ROLLBACK")
            await state.clear()
            return await call.message.answer(
                f"❌ Недостаточно средств. Нужно {total_stake:,} 💎."
            )
        conn.commit()
    except Exception:
        cursor.execute("ROLLBACK")
        logger.exception("roulette: spin list — ошибка списания")
        return await call.message.answer("❌ Ошибка, попробуй ещё раз.")

    spin_msg = await call.message.answer("🎡 Крутится барабан…")
    await asyncio.sleep(1.4)

    balance_after_stake = db_get_user(user_id)[0]

    n = random.randint(0, 36)
    total_win = 0
    report_lines = []
    for b in bets:
        mult = bet_multiplier(b["type"], b["value"], n)
        win = base_stake * mult
        total_win += win
        marker = "✅" if mult > 0 else "❌"
        diff = win - base_stake
        report_lines.append(
            f"{marker} {bet_label(b['type'], b['value'])}: "
            f"{'+' if diff >= 0 else ''}{diff:,} 💎"
        )

    db_update_stats(user_id, total_stake, total_win, deducted=True)
    new_balance = db_get_user(user_id)[0]

    credited = new_balance - balance_after_stake
    delta = credited - total_stake
    header = "🎉 <b>ПОБЕДА</b>" if delta > 0 else ("➖ <b>Ноль</b>" if delta == 0 else "❌ <b>Проигрыш</b>")
    bonus_note = ""
    if credited != total_win:
        bonus_note = f"\n<i>(с учётом буста/кэшбэка/страховки зачислено: {credited:,} 💎)</i>"

    text = (
        f"{header}\n"
        f"Выпало: <b>{describe_number(n)}</b>\n\n"
        + "\n".join(report_lines)
        + f"\n\nИтог: {'+' if delta >= 0 else ''}{delta:,} 💎"
        + bonus_note
        + f"\n💳 Баланс: {new_balance:,} 💎"
    )

    kb = InlineKeyboardBuilder()
    kb.button(text=f"🔁 Те же ставки ещё раз", callback_data="rl:again_same")
    kb.button(text=f"🎡 Новая игра", callback_data="rl:again_new")
    kb.adjust(1)

    await state.update_data(last_bets=bets, last_stake=base_stake)
    try:
        await spin_msg.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    except Exception:
        await call.message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")


@router.callback_query(F.data == "rl:again_same")
async def rl_again_same(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    data = await state.get_data()
    bets = data.get("last_bets")
    base_stake = data.get("last_stake")
    if not bets or not base_stake:
        return await call.message.answer("Нет прошлой ставки. Запусти /roulette.")
    await state.set_state(RouletteState.building)
    await state.update_data(base_stake=base_stake, bets=bets)
    await call.message.answer(
        build_menu_text(base_stake, bets),
        reply_markup=build_menu_kb(bets).as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "rl:again_new")
async def rl_again_new(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.clear()
    await call.message.answer("Запусти /roulette [ставка] для новой игры.")
