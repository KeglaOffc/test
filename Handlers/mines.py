"""Игра «Мины».

Поток: `/mines <ставка>` → меню размера → меню кол-ва бомб → игровое поле.
Поддерживается подкрут (`rig_force`), щит, сканер и страховка.
"""
from __future__ import annotations

import logging
import os
import random

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import conn, cursor, db_get_user, db_update_stats, db_get_rig
from Handlers.common import check_user

logger = logging.getLogger(__name__)
router = Router()

ADMIN_ID = int(os.getenv("ADMIN_ID", "5030561581"))


class MinesState(StatesGroup):
    choosing_size = State()
    choosing_mines = State()
    playing = State()
    scanning = State()


FIELD_SIZES = [
    ("5×5", 5),
    ("6×6", 6),
    ("7×7", 7),
    ("8×8", 8),
]


def _bomb_presets(total_cells: int) -> list[int]:
    """Возвращает список предустановленных вариантов количества мин."""
    candidates = [1, 3, 5, 7, max(1, total_cells // 4), total_cells // 2, total_cells - 1]
    uniq = sorted({max(1, min(total_cells - 1, c)) for c in candidates})
    return uniq


def _calc_mult(cells: int, mines: int, steps: int) -> float:
    """Честный множитель (без краевых случаев) с учётом маржи 5%."""
    if steps <= 0:
        return 1.0
    mult = 1.0
    for i in range(steps):
        prob = (cells - mines - i) / (cells - i)
        if prob <= 0:
            return 100.0
        mult /= prob
    return round(mult * 0.95, 2)


def _field_kb(
    side: int,
    *,
    opened: list[int] | None = None,
    reveal: bool = False,
    mines: list[int] | None = None,
    flagged: list[int] | None = None,
    scanning: bool = False,
    user_id: int | None = None,
) -> types.InlineKeyboardMarkup:
    opened = opened or []
    mines = mines or []
    flagged = flagged or []
    kb = InlineKeyboardBuilder()
    total = side * side
    for i in range(total):
        if i in opened:
            kb.button(text="💥" if i in mines else "💎", callback_data="mine_noop")
        elif i in flagged:
            kb.button(text="🚩", callback_data="mine_noop")
        elif reveal and i in mines:
            kb.button(text="💣", callback_data="mine_noop")
        elif scanning:
            kb.button(text="🔍", callback_data=f"mine_scan:{i}")
        else:
            kb.button(text="❓", callback_data=f"mine_click:{i}")
    kb.adjust(side if side <= 8 else 5)

    if not reveal and opened and not scanning:
        kb.row(types.InlineKeyboardButton(text="💰 Забрать", callback_data="mine_cashout"))

    if not reveal and not scanning and user_id and len(opened) == 0:
        cursor.execute("SELECT mine_scan FROM users WHERE id = ?", (user_id,))
        res = cursor.fetchone()
        if res and (res[0] or 0) > 0:
            kb.row(
                types.InlineKeyboardButton(
                    text=f"🔍 Использовать сканер ({res[0]})",
                    callback_data="mine_activate_scan",
                )
            )
    return kb.as_markup()


def _size_kb() -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for label, side in FIELD_SIZES:
        kb.button(text=label, callback_data=f"mine_size:{side}")
    kb.button(text="✖️ Отмена", callback_data="mine_cancel")
    kb.adjust(2, 2, 1)
    return kb.as_markup()


def _bombs_kb(side: int) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    total = side * side
    for n in _bomb_presets(total):
        kb.button(text=f"💣 {n}", callback_data=f"mine_bombs:{n}")
    kb.button(text="⬅️ Размер", callback_data="mine_back_size")
    kb.button(text="✖️ Отмена", callback_data="mine_cancel")
    kb.adjust(3, 3, 2)
    return kb.as_markup()


@router.message(Command("mines"))
async def mines_start(message: types.Message, state: FSMContext):
    user_data = await check_user(message)
    if not user_data:
        return

    args = message.text.split()
    if len(args) < 2 or not args[1].lstrip("-").isdigit():
        return await message.reply(
            "📝 Формат: <code>/mines [ставка]</code>", parse_mode="HTML"
        )

    bet = int(args[1])
    if bet < 10:
        return await message.reply("❌ Минимальная ставка — 10 💎.")
    if bet > user_data[0]:
        return await message.reply(f"❌ Недостаточно средств. Баланс: {user_data[0]:,} 💎")
    is_no_limit = user_data[9] == 777
    if not is_no_limit and bet > 1_000_000:
        return await message.reply("❌ Максимальная ставка — 1 000 000 💎.")

    await state.clear()
    await state.update_data(bet=bet)
    await state.set_state(MinesState.choosing_size)
    await message.answer(
        f"💣 <b>Мины</b>\nСтавка: <b>{bet:,}</b> 💎\n\nВыбери размер поля:",
        reply_markup=_size_kb(),
        parse_mode="HTML",
    )


@router.callback_query(MinesState.choosing_size, F.data.startswith("mine_size:"))
async def mines_choose_size(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    side = int(call.data.split(":")[1])
    if side < 2 or side > 8:
        return
    data = await state.get_data()
    await state.update_data(side_size=side, total_cells=side * side)
    await state.set_state(MinesState.choosing_mines)
    try:
        await call.message.edit_text(
            f"💣 <b>Мины</b>\nСтавка: <b>{data['bet']:,}</b> 💎  •  Поле: {side}×{side}\n\n"
            "Выбери количество бомб:",
            reply_markup=_bombs_kb(side),
            parse_mode="HTML",
        )
    except Exception:
        await call.message.answer(
            f"Выбери количество бомб (1–{side * side - 1}):",
            reply_markup=_bombs_kb(side),
        )


@router.callback_query(MinesState.choosing_mines, F.data == "mine_back_size")
async def mines_back_size(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(MinesState.choosing_size)
    data = await state.get_data()
    try:
        await call.message.edit_text(
            f"💣 <b>Мины</b>\nСтавка: <b>{data['bet']:,}</b> 💎\n\nВыбери размер поля:",
            reply_markup=_size_kb(),
            parse_mode="HTML",
        )
    except Exception:
        pass


@router.callback_query(F.data == "mine_cancel")
async def mines_cancel(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.clear()
    try:
        await call.message.edit_text("❌ Игра отменена.")
    except Exception:
        pass


@router.callback_query(MinesState.choosing_mines, F.data.startswith("mine_bombs:"))
async def mines_choose_bombs(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    m_count = int(call.data.split(":")[1])
    data = await state.get_data()
    total = data["total_cells"]
    if not (1 <= m_count <= total - 1):
        return await call.answer("❌ Некорректное количество мин.", show_alert=True)

    user_id = call.from_user.id
    bet = data["bet"]

    rig = db_get_rig(user_id)
    if rig == "win":
        mines_list: list[int] = []
        mines_encoded = []
    elif rig == "lose":
        mines_list = random.sample(range(total), m_count)
        mines_encoded = mines_list
    else:
        mines_list = random.sample(range(total), m_count)
        mines_encoded = mines_list

    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute("SELECT balance FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if not row or row[0] < bet:
            cursor.execute("ROLLBACK")
            return await call.answer("❌ Недостаточно средств.", show_alert=True)
        cursor.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (bet, user_id))
        cursor.execute(
            """INSERT INTO mines_games (user_id, mines_pos, field_size, bet, status)
               VALUES (?, ?, ?, ?, 'active')
               ON CONFLICT(user_id) DO UPDATE SET
                   mines_pos = excluded.mines_pos,
                   field_size = excluded.field_size,
                   bet = excluded.bet,
                   status = 'active'""",
            (user_id, ",".join(map(str, mines_encoded)), data["side_size"], bet),
        )
        conn.commit()
    except Exception:
        cursor.execute("ROLLBACK")
        logger.exception("mines: не удалось запустить игру")
        return await call.answer("❌ Ошибка запуска игры.", show_alert=True)

    await state.update_data(
        mines=mines_list,
        mine_count=m_count,
        opened=[],
        flagged=[],
        steps=0,
        rig=rig,
    )
    await state.set_state(MinesState.playing)

    try:
        side = data["side_size"]
        grid = f"🚀 <b>Игрок начал Mines</b>\nID: <code>{user_id}</code>\nСтавка: {bet:,} 💎\nПоле: {side}×{side}  •  Бомб: {m_count}\nПодкрут: {rig}\n\n"
        for i in range(total):
            grid += "💣 " if i in mines_list else "💎 "
            if (i + 1) % side == 0:
                grid += "\n"
        await call.message.bot.send_message(ADMIN_ID, grid, parse_mode="HTML")
    except Exception:
        pass

    try:
        await call.message.edit_text(
            f"🎮 <b>Игра началась</b>\nСтавка: {bet:,} 💎  •  Бомб: {m_count}\n"
            f"Поле: {data['side_size']}×{data['side_size']}",
            reply_markup=_field_kb(data["side_size"], user_id=user_id),
            parse_mode="HTML",
        )
    except Exception:
        await call.message.answer(
            "🎮 Игра началась!",
            reply_markup=_field_kb(data["side_size"], user_id=user_id),
        )


@router.callback_query(MinesState.playing, F.data == "mine_activate_scan")
async def mine_activate_scan(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    cursor.execute("SELECT mine_scan FROM users WHERE id = ?", (call.from_user.id,))
    row = cursor.fetchone()
    if not row or (row[0] or 0) < 1:
        return await call.answer("❌ Сканера нет.", show_alert=True)
    await call.answer()
    await state.set_state(MinesState.scanning)
    try:
        await call.message.edit_text(
            "🔍 Выбери клетку для сканирования (будут открыты 3 соседние).",
            reply_markup=_field_kb(
                data["side_size"],
                opened=data.get("opened", []),
                flagged=data.get("flagged", []),
                scanning=True,
                user_id=call.from_user.id,
            ),
        )
    except Exception:
        pass


def _neighbors(idx: int, side: int) -> list[int]:
    row, col = idx // side, idx % side
    out = []
    for dr, dc in ((0, 1), (1, 0), (1, 1)):
        nr, nc = row + dr, col + dc
        if 0 <= nr < side and 0 <= nc < side:
            out.append(nr * side + nc)
    return out


@router.callback_query(MinesState.scanning, F.data.startswith("mine_scan:"))
async def mine_scan_process(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    scan_idx = int(call.data.split(":")[1])
    if scan_idx in data["opened"]:
        return await call.answer("❌ Клетка уже открыта.", show_alert=True)

    targets = [scan_idx] + _neighbors(scan_idx, data["side_size"])
    new_opened = list(data["opened"])
    new_flagged = list(data.get("flagged", []))
    scan_report = []
    for t in targets:
        if t in new_opened or t in new_flagged:
            continue
        if t in data["mines"]:
            new_flagged.append(t)
            scan_report.append(f"🚩 Клетка {t}: мина")
        else:
            new_opened.append(t)
            scan_report.append(f"💎 Клетка {t}: гем")

    cursor.execute("UPDATE users SET mine_scan = mine_scan - 1 WHERE id = ?", (call.from_user.id,))
    conn.commit()

    await state.update_data(opened=new_opened, flagged=new_flagged)
    await state.set_state(MinesState.playing)

    mult = _calc_mult(data["total_cells"], data["mine_count"], len(new_opened))
    try:
        await call.message.edit_text(
            "🔍 <b>Сканер сработал</b>\n"
            + "\n".join(scan_report)
            + f"\n\nМножитель: {mult}×  •  Возможный выигрыш: {int(data['bet'] * mult):,} 💎",
            reply_markup=_field_kb(
                data["side_size"],
                opened=new_opened,
                flagged=new_flagged,
                user_id=call.from_user.id,
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await call.answer("✅ Сканирование завершено.")


@router.callback_query(MinesState.playing, F.data.startswith("mine_click:"))
async def mine_click(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    idx = int(call.data.split(":")[1])
    if idx in data["opened"]:
        return await call.answer()
    if idx in data.get("flagged", []):
        return await call.answer("🚩 Клетка помечена как мина.", show_alert=True)

    rig = data.get("rig", "off")
    mines_list = list(data["mines"])
    is_mine = idx in mines_list

    if rig == "lose" and not is_mine:
        mines_list.append(idx)
        await state.update_data(mines=mines_list)
        is_mine = True

    if is_mine:
        cursor.execute("SELECT mine_shield FROM users WHERE id = ?", (call.from_user.id,))
        res = cursor.fetchone()
        if res and (res[0] or 0) > 0 and rig != "lose":
            cursor.execute(
                "UPDATE users SET mine_shield = mine_shield - 1 WHERE id = ?",
                (call.from_user.id,),
            )
            conn.commit()
            mines_list = [m for m in mines_list if m != idx]
            await state.update_data(mines=mines_list)
            is_mine = False
            await call.answer("🛡 Щит сработал! Мина обезврежена.", show_alert=True)

    if is_mine:
        db_update_stats(call.from_user.id, data["bet"], 0, deducted=True)
        new_balance = db_get_user(call.from_user.id)[0]
        await call.message.edit_text(
            f"💥 <b>БАБАХ</b>\n"
            f"Убыток: −{data['bet']:,} 💎\n"
            f"💳 Баланс: {new_balance:,} 💎",
            reply_markup=_field_kb(
                data["side_size"],
                opened=data["opened"] + [idx],
                reveal=True,
                mines=mines_list,
                flagged=data.get("flagged", []),
                user_id=call.from_user.id,
            ),
            parse_mode="HTML",
        )
        await state.clear()
        return

    new_opened = data["opened"] + [idx]
    new_steps = data["steps"] + 1
    mult = _calc_mult(data["total_cells"], data["mine_count"], new_steps)
    await state.update_data(opened=new_opened, steps=new_steps)

    if len(new_opened) == data["total_cells"] - data["mine_count"]:
        win = int(data["bet"] * mult)
        db_update_stats(call.from_user.id, data["bet"], win, deducted=True)
        new_balance = db_get_user(call.from_user.id)[0]
        profit = win - data["bet"]
        await call.message.edit_text(
            f"🏆 <b>ПОЛНАЯ ПОБЕДА</b>\n"
            f"Множитель: ×{mult}\n"
            f"Профит: +{profit:,} 💎\n"
            f"💳 Баланс: {new_balance:,} 💎",
            reply_markup=_field_kb(
                data["side_size"],
                opened=new_opened,
                reveal=True,
                mines=mines_list,
                flagged=data.get("flagged", []),
                user_id=call.from_user.id,
            ),
            parse_mode="HTML",
        )
        await state.clear()
        return

    await call.message.edit_text(
        f"🍀 <b>УДАЧНО</b>\nМножитель: ×{mult}  •  Возможный выигрыш: {int(data['bet'] * mult):,} 💎",
        reply_markup=_field_kb(
            data["side_size"],
            opened=new_opened,
            flagged=data.get("flagged", []),
            user_id=call.from_user.id,
        ),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "mine_cashout")
async def mine_cashout(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data or not data.get("opened"):
        return await call.answer()

    mult = _calc_mult(data["total_cells"], data["mine_count"], data["steps"])
    win = int(data["bet"] * mult)
    db_update_stats(call.from_user.id, data["bet"], win, deducted=True)
    new_balance = db_get_user(call.from_user.id)[0]
    profit = win - data["bet"]
    try:
        await call.message.edit_text(
            f"💰 <b>ВЫ ЗАБРАЛИ ДЕНЬГИ</b>\n"
            f"Множитель: ×{mult}\n"
            f"Профит: +{profit:,} 💎\n"
            f"💳 Баланс: {new_balance:,} 💎",
            reply_markup=_field_kb(
                data["side_size"],
                opened=data["opened"],
                reveal=True,
                mines=data["mines"],
                flagged=data.get("flagged", []),
                user_id=call.from_user.id,
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await state.clear()


@router.callback_query(F.data == "mine_noop")
async def mine_noop(call: types.CallbackQuery):
    await call.answer()
