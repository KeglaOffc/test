"""Лотерейный центр: часовая, недельная, мега, мгновенная и пользовательская.

Система системных лотерей (hourly/weekly/mega) устроена по-классически:
- Покупаешь билет → генерируется набор номеров (tickets.numbers), он сохраняется
  в инвентаре. Можно посмотреть в любой момент.
- В конце тиража бот выбирает набор "выигрышных" номеров и сверяет каждый билет
  текущего тиража. Призы зависят от количества совпавших номеров.
- После розыгрыша билет переходит в "корзину" (status='archived') с записанной
  суммой выигрыша (win) и номерами текущего тиража. Там его можно посмотреть.

Мгновенная лотерея тоже сохраняет билеты: покупаешь → бот сразу выбирает
номера и считает, билет уходит в архив с результатом — его видно в инвентаре.

Пользовательские (созданные игроками) лотереи инвентарь/архив не используют —
как просил пользователь, это одноразовые розыгрыши без следа в истории.
"""
import asyncio
import datetime
import logging
import random
import time
from typing import List, Tuple

from aiogram import F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import conn, cursor, db_get_user, db_update_stats
from Handlers.common import check_user

logger = logging.getLogger(__name__)
router = Router()


HOURLY = {
    "key": "hourly",
    "state": "hourly_state",
    "title": "🕐 Часовая",
    "price": 1_000,
    "limit_per_period": 10,
    "pool_share": 0.95,
    "numbers_count": 4,
    "numbers_pool": 40,
    "period_seconds": 3600,
    "prizes": {4: "jackpot", 3: 20, 2: 5, 1: 1},
}
WEEKLY = {
    "key": "weekly",
    "state": "weekly_state",
    "title": "📅 Недельная",
    "price": 7_000,
    "limit_per_period": 20,
    "pool_share": 0.80,
    "numbers_count": 5,
    "numbers_pool": 45,
    "period_seconds": 7 * 24 * 3600,
    "prizes": {5: "jackpot", 4: 50, 3: 10, 2: 2},
}
MEGA = {
    "key": "mega",
    "state": "mega_state",
    "title": "🐳 Мега",
    "price": 150_000,
    "limit_per_period": 5,
    "pool_share": 1.0,
    "numbers_count": 6,
    "numbers_pool": 50,
    "period_seconds": 7 * 24 * 3600,
    "prizes": {6: "jackpot", 5: 100, 4: 20, 3: 3},
}

LOTTERIES = {cfg["key"]: cfg for cfg in (HOURLY, WEEKLY, MEGA)}

SCRATCH_PRICE = 2_500
SCRATCH_PRIZES = [
    {"mult": 0, "weight": 55},
    {"mult": 1, "weight": 20},
    {"mult": 2, "weight": 15},
    {"mult": 5, "weight": 7},
    {"mult": 20, "weight": 2},
    {"mult": 100, "weight": 1},
]


class CreateLottery(StatesGroup):
    title = State()
    prize_pool = State()
    ticket_price = State()
    max_tickets = State()
    confirm = State()


# ─────────────── утилиты ───────────────

def pick_numbers(count: int, pool: int) -> List[int]:
    """Генерирует отсортированный набор уникальных номеров 1..pool."""
    return sorted(random.sample(range(1, pool + 1), count))


def format_numbers(numbers: List[int]) -> str:
    return " ".join(f"<code>{n:02d}</code>" for n in numbers)


def current_draw(cfg) -> Tuple[int, int]:
    """Возвращает (draw_id, prize_pool) активного тиража (создаёт, если нет)."""
    cursor.execute(f"SELECT draw_id, prize_pool FROM {cfg['state']} WHERE winning_numbers = '' ORDER BY draw_id DESC LIMIT 1")
    row = cursor.fetchone()
    if row:
        return row[0], row[1]

    defaults = {"hourly": 100_000, "weekly": 1_000_000, "mega": 5_000_000}
    base = defaults[cfg["key"]]
    cursor.execute(
        f"INSERT INTO {cfg['state']} (prize_pool) VALUES (?)",
        (base,),
    )
    conn.commit()
    return cursor.lastrowid, base


def period_start(cfg) -> int:
    now = int(time.time())
    if cfg["key"] == "hourly":
        return now - (now % 3600)
    d = datetime.datetime.now()
    start_of_week = d - datetime.timedelta(days=d.weekday())
    start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start_of_week.timestamp())


def user_active_tickets(user_id: int, cfg, draw_id: int) -> List[tuple]:
    cursor.execute(
        "SELECT id, numbers FROM lottery_tickets "
        "WHERE user_id = ? AND lottery_type = ? AND draw_id = ? AND status = 'active' "
        "ORDER BY id",
        (user_id, cfg["key"], draw_id),
    )
    return cursor.fetchall()


def user_archived_tickets(user_id: int, cfg, limit: int = 10) -> List[tuple]:
    cursor.execute(
        "SELECT id, numbers, win, draw_id FROM lottery_tickets "
        "WHERE user_id = ? AND lottery_type = ? AND status = 'archived' "
        "ORDER BY id DESC LIMIT ?",
        (user_id, cfg["key"], limit),
    )
    return cursor.fetchall()


def bought_in_period(user_id: int, cfg) -> int:
    cursor.execute(
        "SELECT COUNT(*) FROM lottery_tickets "
        "WHERE user_id = ? AND lottery_type = ? AND buy_time >= ?",
        (user_id, cfg["key"], period_start(cfg)),
    )
    return cursor.fetchone()[0]


def time_left_hourly() -> str:
    now = datetime.datetime.now()
    nxt = (now + datetime.timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    diff = nxt - now
    m, s = divmod(diff.seconds, 60)
    return f"{m:02d}:{s:02d}"


def time_left_weekly() -> str:
    now = datetime.datetime.now()
    days_ahead = 6 - now.weekday()
    end = (now + datetime.timedelta(days=days_ahead)).replace(hour=23, minute=59, second=59, microsecond=0)
    diff = end - now
    d = diff.days
    h, rem = divmod(diff.seconds, 3600)
    m, _ = divmod(rem, 60)
    return f"{d}д {h}ч {m}м"


# ─────────────── главное меню ───────────────

def main_menu_kb() -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🕐 Часовая",    callback_data="lot:menu:hourly")
    kb.button(text="📅 Недельная",  callback_data="lot:menu:weekly")
    kb.button(text="🐳 Мега",        callback_data="lot:menu:mega")
    kb.button(text="🎟 Мгновенная", callback_data="lot:scratch")
    kb.button(text="🎪 Пользовательские", callback_data="lot:user")
    kb.button(text="🎒 Инвентарь",        callback_data="lot:inv")
    kb.button(text="🏠 В меню", callback_data="go:start")
    kb.adjust(3, 1, 1, 1, 1)
    return kb.as_markup()


def main_menu_text() -> str:
    return (
        "🎰 <b>Лотерейный центр</b>\n\n"
        "• <b>Часовая</b> — 4 номера из 40, розыгрыш каждый час.\n"
        "• <b>Недельная</b> — 5 из 45, розыгрыш в воскресенье 23:59.\n"
        "• <b>Мега</b> — 6 из 50, раз в неделю, весь банк одному.\n"
        "• <b>Мгновенная</b> — моментальный скретч.\n"
        "• <b>Пользовательские</b> — розыгрыши от игроков.\n\n"
        "Купленные билеты лежат в инвентаре каждой лотереи, "
        "использованные — в «🗑 Мои использованные билеты»."
    )


@router.message(Command("lottery"))
async def lottery_cmd(message: types.Message, state: FSMContext):
    if not await check_user(message):
        return
    await state.clear()
    await message.answer(main_menu_text(), reply_markup=main_menu_kb(), parse_mode="HTML")


@router.callback_query(F.data == "lot:main")
async def lot_main(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    try:
        await call.message.edit_text(main_menu_text(), reply_markup=main_menu_kb(), parse_mode="HTML")
    except Exception:
        await call.message.answer(main_menu_text(), reply_markup=main_menu_kb(), parse_mode="HTML")


@router.callback_query(F.data == "lot:close")
async def lot_close(call: types.CallbackQuery):
    await call.answer()
    try:
        await call.message.delete()
    except Exception:
        pass


# ─────────────── системная лотерея: меню, покупка, инвентарь ───────────────

def render_lottery_menu(user_id: int, cfg) -> Tuple[str, types.InlineKeyboardMarkup]:
    draw_id, pool = current_draw(cfg)
    in_period = bought_in_period(user_id, cfg)
    active = user_active_tickets(user_id, cfg, draw_id)

    if cfg["key"] == "hourly":
        time_str = f"⏳ До розыгрыша: <code>{time_left_hourly()}</code>"
    elif cfg["key"] == "weekly":
        time_str = f"⏳ До розыгрыша: <code>{time_left_weekly()}</code>"
    else:
        time_str = f"⏳ До розыгрыша: <code>{time_left_weekly()}</code>"

    prizes = cfg["prizes"]
    prize_lines = []
    for m in sorted(prizes.keys(), reverse=True):
        v = prizes[m]
        label = "🏆 ВЕСЬ БАНК" if v == "jackpot" else f"×{v} от цены билета"
        prize_lines.append(f"• <b>{m}</b> совпад. — {label}")

    text = (
        f"{cfg['title']} <b>лотерея #{draw_id}</b>\n"
        f"{time_str}\n"
        f"💰 Банк тиража: <b>{pool:,}</b> 💎\n"
        f"🎫 Цена билета: <b>{cfg['price']:,}</b> 💎\n"
        f"📦 Формат: <b>{cfg['numbers_count']} из {cfg['numbers_pool']}</b>\n"
        f"🎯 Лимит в период: <code>{in_period}/{cfg['limit_per_period']}</code>\n\n"
        "<b>Призы:</b>\n" + "\n".join(prize_lines) + "\n\n"
        f"Твои активные билеты: <b>{len(active)}</b>"
    )

    kb = InlineKeyboardBuilder()
    kb.button(text=f"🎫 Купить 1 билет ({cfg['price']:,} 💎)", callback_data=f"lot:buy:{cfg['key']}:1")
    kb.button(text=f"🎫 Купить 3 ({int(cfg['price'] * 3 * 0.9):,} 💎, −10%)", callback_data=f"lot:buy:{cfg['key']}:3")
    kb.button(text=f"📋 Мои билеты ({len(active)})", callback_data=f"lot:tickets:{cfg['key']}")
    kb.button(text="⬅️ Назад", callback_data="lot:main")
    kb.adjust(1)
    return text, kb.as_markup()


@router.callback_query(F.data.startswith("lot:menu:"))
async def lot_menu(call: types.CallbackQuery):
    await call.answer()
    key = call.data.split(":", 2)[2]
    cfg = LOTTERIES.get(key)
    if not cfg:
        return
    text, markup = render_lottery_menu(call.from_user.id, cfg)
    try:
        await call.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    except Exception:
        await call.message.answer(text, reply_markup=markup, parse_mode="HTML")


@router.callback_query(F.data.startswith("lot:buy:"))
async def lot_buy(call: types.CallbackQuery):
    await call.answer()
    parts = call.data.split(":")
    key, count_str = parts[2], parts[3]
    cfg = LOTTERIES.get(key)
    if not cfg:
        return
    count = int(count_str)
    if count not in (1, 3):
        return

    user_id = call.from_user.id
    price_each = cfg["price"]
    total = price_each * count
    if count == 3:
        total = int(total * 0.9)

    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute("SELECT balance FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            cursor.execute("ROLLBACK")
            return await call.message.answer("❌ Профиль не найден.")
        if row[0] < total:
            cursor.execute("ROLLBACK")
            return await call.message.answer(
                f"❌ Нужно {total:,} 💎, а у тебя {row[0]:,} 💎."
            )

        in_period = bought_in_period(user_id, cfg)
        if in_period + count > cfg["limit_per_period"]:
            cursor.execute("ROLLBACK")
            return await call.message.answer(
                f"❌ Лимит {cfg['limit_per_period']} билетов за период. Сейчас у тебя {in_period}."
            )

        cursor.execute(
            "UPDATE users SET balance = balance - ? WHERE id = ?",
            (total, user_id),
        )

        draw_id, _ = current_draw(cfg)
        now = int(time.time())
        created_numbers = []
        for _ in range(count):
            nums = pick_numbers(cfg["numbers_count"], cfg["numbers_pool"])
            created_numbers.append(nums)
            cursor.execute(
                "INSERT INTO lottery_tickets (user_id, lottery_type, buy_time, numbers, draw_id, status, win) "
                "VALUES (?, ?, ?, ?, ?, 'active', 0)",
                (user_id, cfg["key"], now, ",".join(str(n) for n in nums), draw_id),
            )

        into_pool = int(total * cfg["pool_share"])
        cursor.execute(
            f"UPDATE {cfg['state']} SET prize_pool = prize_pool + ? WHERE draw_id = ?",
            (into_pool, draw_id),
        )
        conn.commit()
    except Exception:
        cursor.execute("ROLLBACK")
        logger.exception("lottery:%s: ошибка покупки", cfg["key"])
        return await call.message.answer("❌ Ошибка покупки, попробуй ещё раз.")

    lines = [f"{cfg['title']} тираж #{draw_id} — куплено билетов: <b>{count}</b>"]
    for i, nums in enumerate(created_numbers, 1):
        lines.append(f"№{i}: {format_numbers(nums)}")
    lines.append(f"\nСписано: <b>{total:,}</b> 💎")
    new_bal = db_get_user(user_id)[0]
    lines.append(f"💳 Баланс: <b>{new_bal:,}</b> 💎")

    kb = InlineKeyboardBuilder()
    kb.button(text="📋 Мои билеты", callback_data=f"lot:tickets:{cfg['key']}")
    kb.button(text="⬅️ В меню лотереи", callback_data=f"lot:menu:{cfg['key']}")
    kb.adjust(1)
    try:
        await call.message.edit_text("\n".join(lines), reply_markup=kb.as_markup(), parse_mode="HTML")
    except Exception:
        await call.message.answer("\n".join(lines), reply_markup=kb.as_markup(), parse_mode="HTML")


@router.callback_query(F.data.startswith("lot:tickets:"))
async def lot_tickets(call: types.CallbackQuery):
    await call.answer()
    key = call.data.split(":", 2)[2]
    cfg = LOTTERIES.get(key)
    if not cfg:
        return
    draw_id, _ = current_draw(cfg)
    active = user_active_tickets(call.from_user.id, cfg, draw_id)

    if not active:
        text = f"{cfg['title']} лотерея — у тебя нет активных билетов в тираже #{draw_id}."
    else:
        lines = [f"{cfg['title']} лотерея — твои билеты (тираж #{draw_id})\n"]
        for i, (tid, nums_str) in enumerate(active, 1):
            nums = [int(x) for x in nums_str.split(",")]
            lines.append(f"🎫 №{i} (id {tid}): {format_numbers(nums)}")
        text = "\n".join(lines)

    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data=f"lot:menu:{cfg['key']}")
    kb.adjust(1)
    try:
        await call.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    except Exception:
        await call.message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")


# ─────────────── архив / корзина использованных билетов ───────────────

@router.callback_query(F.data == "lot:inv")
async def lot_inventory_menu(call: types.CallbackQuery):
    """Инвентарь билетов: активные + использованные."""
    await call.answer()
    active_total = 0
    for cfg in (HOURLY, WEEKLY, MEGA):
        draw_id, _ = current_draw(cfg)
        active_total += len(user_active_tickets(call.from_user.id, cfg, draw_id))
    cursor.execute(
        "SELECT COUNT(*) FROM lottery_tickets WHERE user_id = ? AND status = 'archived'",
        (call.from_user.id,),
    )
    archived_total = cursor.fetchone()[0] or 0

    kb = InlineKeyboardBuilder()
    kb.button(text=f"✅ Активные ({active_total})", callback_data="lot:inv:active")
    kb.button(text=f"🗑 Использованные ({archived_total})", callback_data="lot:archive")
    kb.button(text="⬅️ Назад", callback_data="lot:main")
    kb.adjust(1)
    text = (
        "🎒 <b>Инвентарь лотерей</b>\n\n"
        f"✅ Активных билетов: <b>{active_total}</b>\n"
        f"🗑 В корзине: <b>{archived_total}</b>\n\n"
        "Активные — билеты текущих тиражей. Использованные — уже разыгранные."
    )
    try:
        await call.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    except Exception:
        await call.message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")


@router.callback_query(F.data == "lot:inv:active")
async def lot_inventory_active(call: types.CallbackQuery):
    """Показывает активные билеты по всем системным лотереям."""
    await call.answer()
    lines = []
    for cfg in (HOURLY, WEEKLY, MEGA):
        draw_id, _ = current_draw(cfg)
        tickets = user_active_tickets(call.from_user.id, cfg, draw_id)
        if not tickets:
            continue
        lines.append(f"\n{cfg['title']} — тираж #{draw_id}")
        for i, (tid, nums_str) in enumerate(tickets, 1):
            nums = [int(x) for x in nums_str.split(",")]
            lines.append(f"  🎫 №{i} (id {tid}): {format_numbers(nums)}")
    text = "\n".join(lines).strip() if lines else "✅ У тебя нет активных билетов."
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data="lot:inv")
    kb.adjust(1)
    try:
        await call.message.edit_text(text or "✅ Активных билетов нет.", reply_markup=kb.as_markup(), parse_mode="HTML")
    except Exception:
        await call.message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")


@router.callback_query(F.data == "lot:archive")
async def lot_archive_menu(call: types.CallbackQuery):
    await call.answer()
    kb = InlineKeyboardBuilder()
    for cfg in (HOURLY, WEEKLY, MEGA, {"key": "scratch", "title": "🎟 Мгновенная"}):
        kb.button(text=cfg["title"], callback_data=f"lot:arch:{cfg['key']}")
    kb.button(text="⬅️ Назад", callback_data="lot:inv")
    kb.adjust(2, 2, 1)
    try:
        await call.message.edit_text(
            "🗑 <b>Корзина билетов</b>\nЗдесь лежат уже разыгранные билеты. Выбери лотерею:",
            reply_markup=kb.as_markup(),
            parse_mode="HTML",
        )
    except Exception:
        await call.message.answer(
            "🗑 <b>Корзина билетов</b>",
            reply_markup=kb.as_markup(),
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("lot:arch:"))
async def lot_archive_show(call: types.CallbackQuery):
    await call.answer()
    key = call.data.split(":", 2)[2]
    if key == "scratch":
        cursor.execute(
            "SELECT id, numbers, win FROM lottery_tickets "
            "WHERE user_id = ? AND lottery_type = 'scratch' AND status = 'archived' "
            "ORDER BY id DESC LIMIT 15",
            (call.from_user.id,),
        )
        rows = cursor.fetchall()
        title = "🎟 Мгновенная"
    else:
        cfg = LOTTERIES.get(key)
        if not cfg:
            return
        rows = [
            (tid, nums, win) for tid, nums, win, _ in user_archived_tickets(call.from_user.id, cfg, 15)
        ]
        title = cfg["title"]

    if not rows:
        text = f"{title} — архив пуст."
    else:
        lines = [f"{title} — последние {len(rows)} билетов:\n"]
        for tid, nums_str, win in rows:
            nums_disp = (
                format_numbers([int(x) for x in nums_str.split(",")])
                if nums_str
                else "—"
            )
            outcome = f"выигрыш {win:,} 💎" if win > 0 else "без выигрыша"
            lines.append(f"🗑 id {tid}: {nums_disp} — {outcome}")
        text = "\n".join(lines)

    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data="lot:archive")
    kb.adjust(1)
    try:
        await call.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    except Exception:
        await call.message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")


# ─────────────── мгновенная лотерея ───────────────

def scratch_pull() -> int:
    weights = [p["weight"] for p in SCRATCH_PRIZES]
    return random.choices(SCRATCH_PRIZES, weights=weights, k=1)[0]["mult"]


def scratch_menu_text() -> str:
    return (
        "🎟 <b>Мгновенная лотерея</b>\n"
        f"Цена билета: <b>{SCRATCH_PRICE:,}</b> 💎\n\n"
        "Покупаешь билет — тут же стирается слой, видно результат.\n"
        "Билет попадает в архив в «🗑 Мои использованные билеты».\n\n"
        "<b>Выплаты (множитель от цены):</b>\n"
        "• ×100 — 1%   • ×20 — 2%\n"
        "• ×5  — 7%    • ×2 — 15%\n"
        "• ×1  — 20%   • ×0 — 55%"
    )


def scratch_menu_kb(free_count: int = 0) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if free_count > 0:
        kb.button(
            text=f"🎁 Использовать свой ({free_count})",
            callback_data="lot:scratch:use_free",
        )
    kb.button(text=f"🎟 1 билет ({SCRATCH_PRICE:,} 💎)", callback_data="lot:scratch:buy:1")
    kb.button(text=f"🎟 5 билетов ({SCRATCH_PRICE * 5:,} 💎)", callback_data="lot:scratch:buy:5")
    kb.button(text="⬅️ Назад", callback_data="lot:main")
    kb.adjust(1)
    return kb.as_markup()


def _user_free_scratch(user_id: int) -> int:
    cursor.execute("SELECT COALESCE(scratch_pack, 0) FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    return int(row[0]) if row else 0


@router.callback_query(F.data == "lot:scratch")
async def lot_scratch_menu(call: types.CallbackQuery):
    await call.answer()
    free = _user_free_scratch(call.from_user.id)
    try:
        await call.message.edit_text(scratch_menu_text(), reply_markup=scratch_menu_kb(free), parse_mode="HTML")
    except Exception:
        await call.message.answer(scratch_menu_text(), reply_markup=scratch_menu_kb(free), parse_mode="HTML")


@router.message(Command("scratch"))
async def scratch_cmd(message: types.Message):
    if not await check_user(message):
        return
    free = _user_free_scratch(message.from_user.id)
    await message.answer(scratch_menu_text(), reply_markup=scratch_menu_kb(free), parse_mode="HTML")


@router.callback_query(F.data == "lot:scratch:use_free")
async def lot_scratch_use_free(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            "UPDATE users SET scratch_pack = scratch_pack - 1 "
            "WHERE id = ? AND COALESCE(scratch_pack, 0) > 0",
            (user_id,),
        )
        if cursor.rowcount == 0:
            cursor.execute("ROLLBACK")
            return await call.answer("❌ Бесплатных скретчей нет.", show_alert=True)
        mult = scratch_pull()
        win = SCRATCH_PRICE * mult
        now = int(time.time())
        cursor.execute(
            "INSERT INTO lottery_tickets (user_id, lottery_type, buy_time, numbers, draw_id, status, win) "
            "VALUES (?, 'scratch', ?, ?, 0, 'archived', ?)",
            (user_id, now, f"×{mult}", win),
        )
        if win > 0:
            cursor.execute(
                "UPDATE users SET balance = balance + ? WHERE id = ?",
                (win, user_id),
            )
        conn.commit()
    except Exception:
        cursor.execute("ROLLBACK")
        logger.exception("lot:scratch:use_free")
        return await call.answer("❌ Ошибка.", show_alert=True)

    bal = db_get_user(user_id)[0]
    emoji = "🎉" if mult >= 5 else ("✨" if mult >= 1 else "❌")
    kb = InlineKeyboardBuilder()
    kb.button(text="🎟 Ещё скретч", callback_data="lot:scratch")
    kb.button(text="⬅️ В лотереи", callback_data="lot:main")
    kb.adjust(1)
    try:
        await call.message.edit_text(
            f"{emoji} Скретч сыграл: ×{mult} → <b>{win:,}</b> 💎\n"
            f"💳 Баланс: {bal:,} 💎",
            reply_markup=kb.as_markup(),
            parse_mode="HTML",
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("lot:scratch:buy:"))
async def lot_scratch_buy(call: types.CallbackQuery):
    await call.answer()
    count = int(call.data.split(":")[3])
    if count not in (1, 5):
        return
    total_price = SCRATCH_PRICE * count
    user_id = call.from_user.id

    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            "UPDATE users SET balance = balance - ? WHERE id = ? AND balance >= ?",
            (total_price, user_id, total_price),
        )
        if cursor.rowcount == 0:
            cursor.execute("ROLLBACK")
            return await call.message.answer(
                f"❌ Нужно {total_price:,} 💎 на {count} билет(ов)."
            )

        now = int(time.time())
        lines = []
        total_win = 0
        for _ in range(count):
            mult = scratch_pull()
            win = SCRATCH_PRICE * mult
            total_win += win
            emoji = "🎉" if mult >= 5 else ("✨" if mult >= 1 else "❌")
            lines.append(f"{emoji} ×{mult} → {win:,} 💎")
            cursor.execute(
                "INSERT INTO lottery_tickets (user_id, lottery_type, buy_time, numbers, draw_id, status, win) "
                "VALUES (?, 'scratch', ?, ?, 0, 'archived', ?)",
                (user_id, now, f"×{mult}", win),
            )

        if total_win > 0:
            cursor.execute(
                "UPDATE users SET balance = balance + ? WHERE id = ?",
                (total_win, user_id),
            )
        conn.commit()
    except Exception:
        cursor.execute("ROLLBACK")
        logger.exception("lot:scratch: ошибка")
        return await call.message.answer("❌ Ошибка покупки, попробуй ещё раз.")

    new_bal = db_get_user(user_id)[0]
    delta = total_win - total_price
    text = (
        f"🎟 Куплено билетов: <b>{count}</b>\n\n"
        + "\n".join(lines)
        + f"\n\nИтог: {'+' if delta >= 0 else ''}{delta:,} 💎\n"
        + f"💳 Баланс: <b>{new_bal:,}</b> 💎"
    )
    kb = InlineKeyboardBuilder()
    kb.button(text=f"🎟 Ещё 1", callback_data="lot:scratch:buy:1")
    kb.button(text="⬅️ В лотереи", callback_data="lot:main")
    kb.adjust(1)
    try:
        await call.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    except Exception:
        await call.message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")


# ─────────────── пользовательские лотереи ───────────────

@router.callback_query(F.data == "lot:user")
async def lot_user_list(call: types.CallbackQuery):
    await call.answer()
    cursor.execute(
        "SELECT id, title, prize_pool, ticket_price, max_tickets, sold_tickets "
        "FROM user_lotteries WHERE sold_tickets < max_tickets AND end_time > ?",
        (int(time.time()),),
    )
    rows = cursor.fetchall()

    kb = InlineKeyboardBuilder()
    if not rows:
        text = "🎪 <b>Пользовательские лотереи</b>\n\nСейчас нет активных розыгрышей. Создай свой!"
    else:
        lines = ["🎪 <b>Пользовательские лотереи</b>\n"]
        for lid, title, prize, price, mx, sold in rows:
            lines.append(
                f"▪️ <b>{title}</b>\n"
                f"   💰 Приз: <code>{prize:,}</code> · 🎫 Цена: <code>{price:,}</code>\n"
                f"   🎟 Остаток: <code>{mx - sold}/{mx}</code>"
            )
            kb.button(text=f"🎫 {title}", callback_data=f"lot:ubuy:{lid}")
        text = "\n\n".join(lines)

    kb.button(text="➕ Создать", callback_data="lot:ucreate")
    kb.button(text="⬅️ Назад", callback_data="lot:main")
    kb.adjust(1)
    try:
        await call.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    except Exception:
        await call.message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")


@router.callback_query(F.data == "lot:ucreate")
async def lot_ucreate(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    user = db_get_user(call.from_user.id)
    if not user or user[5] < 10:
        return await call.answer("❌ Нужно сыграть минимум 10 игр.", show_alert=True)
    await state.set_state(CreateLottery.title)
    await state.update_data(msg_id=call.message.message_id)
    try:
        await call.message.edit_text(
            "🎪 <b>Создание лотереи (1/4)</b>\n\nПридумай название (до 30 символов):",
            parse_mode="HTML",
        )
    except Exception:
        pass


@router.message(CreateLottery.title)
async def lot_ucreate_title(message: types.Message, state: FSMContext):
    data = await state.get_data()
    title = (message.text or "").strip()[:30]
    if not title:
        return await message.answer("❌ Пустое название.")
    await state.update_data(title=title)
    await state.set_state(CreateLottery.prize_pool)
    try:
        await message.delete()
    except Exception:
        pass
    await message.bot.edit_message_text(
        chat_id=message.chat.id,
        message_id=data["msg_id"],
        text=f"🎪 <b>Шаг 2/4</b> — «{title}»\n\nКакой призовой фонд? (минимум 10 000 💎)",
        parse_mode="HTML",
    )


@router.message(CreateLottery.prize_pool)
async def lot_ucreate_pool(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if not (message.text or "").isdigit():
        return await message.answer("❌ Нужно число.")
    val = int(message.text)
    if val < 10_000:
        return await message.answer("❌ Минимум 10 000 💎.")
    await state.update_data(prize_pool=val)
    await state.set_state(CreateLottery.ticket_price)
    try:
        await message.delete()
    except Exception:
        pass
    await message.bot.edit_message_text(
        chat_id=message.chat.id,
        message_id=data["msg_id"],
        text=f"🎪 <b>Шаг 3/4</b> — приз {val:,} 💎\n\nЦена одного билета?",
        parse_mode="HTML",
    )


@router.message(CreateLottery.ticket_price)
async def lot_ucreate_price(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if not (message.text or "").isdigit():
        return await message.answer("❌ Нужно число.")
    price = int(message.text)
    if price < 100:
        return await message.answer("❌ Цена билета минимум 100 💎.")
    await state.update_data(ticket_price=price)
    await state.set_state(CreateLottery.max_tickets)
    try:
        await message.delete()
    except Exception:
        pass
    await message.bot.edit_message_text(
        chat_id=message.chat.id,
        message_id=data["msg_id"],
        text=f"🎪 <b>Шаг 4/4</b> — цена {price:,} 💎\n\nСколько всего билетов?",
        parse_mode="HTML",
    )


@router.message(CreateLottery.max_tickets)
async def lot_ucreate_max(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if not (message.text or "").isdigit():
        return await message.answer("❌ Нужно число.")
    count = int(message.text)
    if count < 2:
        return await message.answer("❌ Минимум 2 билета.")
    fee = int(data["prize_pool"] * 0.05)
    total = data["prize_pool"] + fee
    await state.update_data(max_tickets=count, total_cost=total)
    await state.set_state(CreateLottery.confirm)
    try:
        await message.delete()
    except Exception:
        pass
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Подтвердить", callback_data="lot:ucreate_ok")
    kb.button(text="❌ Отмена", callback_data="lot:main")
    kb.adjust(1)
    await message.bot.edit_message_text(
        chat_id=message.chat.id,
        message_id=data["msg_id"],
        text=(
            f"🎪 <b>Проверь лотерею</b>\n\n"
            f"🏷 Название: <code>{data['title']}</code>\n"
            f"💰 Приз: <code>{data['prize_pool']:,}</code> 💎\n"
            f"🎫 Цена билета: <code>{data['ticket_price']:,}</code> 💎\n"
            f"🎟 Всего билетов: <code>{count}</code>\n\n"
            f"К списанию (приз + 5% комиссии): <b>{total:,}</b> 💎"
        ),
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "lot:ucreate_ok")
async def lot_ucreate_confirm(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user = db_get_user(call.from_user.id)
    total = data.get("total_cost", 0)
    if not user or user[0] < total:
        return await call.answer("❌ Недостаточно средств.", show_alert=True)

    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            "UPDATE users SET balance = balance - ? WHERE id = ? AND balance >= ?",
            (total, call.from_user.id, total),
        )
        if cursor.rowcount == 0:
            cursor.execute("ROLLBACK")
            return await call.answer("❌ Не хватило баланса.", show_alert=True)
        cursor.execute(
            "INSERT INTO user_lotteries (creator_id, title, prize_pool, ticket_price, max_tickets, end_time, sold_tickets) "
            "VALUES (?, ?, ?, ?, ?, ?, 0)",
            (
                call.from_user.id,
                data["title"],
                data["prize_pool"],
                data["ticket_price"],
                data["max_tickets"],
                int(time.time()) + 86400,
            ),
        )
        conn.commit()
    except Exception:
        cursor.execute("ROLLBACK")
        logger.exception("lot:ucreate: ошибка")
        return await call.answer("❌ Ошибка при создании.", show_alert=True)

    await state.clear()
    kb = InlineKeyboardBuilder()
    kb.button(text="🎪 Пользовательские", callback_data="lot:user")
    kb.button(text="⬅️ В лотереи", callback_data="lot:main")
    kb.adjust(1)
    try:
        await call.message.edit_text(
            f"✅ Лотерея «{data['title']}» запущена. Игроки её увидят в списке.",
            reply_markup=kb.as_markup(),
        )
    except Exception:
        await call.message.answer("✅ Лотерея запущена.", reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("lot:ubuy:"))
async def lot_ubuy(call: types.CallbackQuery):
    lid = int(call.data.split(":")[2])
    cursor.execute(
        "SELECT title, prize_pool, ticket_price, max_tickets, sold_tickets FROM user_lotteries WHERE id = ?",
        (lid,),
    )
    lot = cursor.fetchone()
    if not lot:
        return await call.answer("❌ Лотерея уже закрыта.", show_alert=True)
    title, prize, price, mx, sold = lot
    if sold >= mx:
        return await call.answer("❌ Все билеты проданы.", show_alert=True)

    user_id = call.from_user.id
    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            "UPDATE users SET balance = balance - ? WHERE id = ? AND balance >= ?",
            (price, user_id, price),
        )
        if cursor.rowcount == 0:
            cursor.execute("ROLLBACK")
            return await call.answer(f"❌ Нужно {price:,} 💎.", show_alert=True)
        cursor.execute(
            "INSERT INTO user_lottery_tickets (lottery_id, user_id) VALUES (?, ?)",
            (lid, user_id),
        )
        cursor.execute(
            "UPDATE user_lotteries SET sold_tickets = sold_tickets + 1 WHERE id = ?",
            (lid,),
        )
        conn.commit()
    except Exception:
        cursor.execute("ROLLBACK")
        logger.exception("lot:ubuy")
        return await call.answer("❌ Ошибка покупки.", show_alert=True)

    await call.answer(f"✅ Билет в «{title}» куплен.")

    cursor.execute("SELECT sold_tickets, max_tickets FROM user_lotteries WHERE id = ?", (lid,))
    sold_after, max_after = cursor.fetchone()
    if sold_after >= max_after:
        await finish_user_lottery(lid, call.message)
    else:
        await lot_user_list(call)


async def finish_user_lottery(lid: int, message: types.Message) -> None:
    try:
        cursor.execute("SELECT title, prize_pool, creator_id FROM user_lotteries WHERE id = ?", (lid,))
        data = cursor.fetchone()
        if not data:
            return
        title, prize, creator_id = data

        cursor.execute("SELECT user_id FROM user_lottery_tickets WHERE lottery_id = ?", (lid,))
        players = [r[0] for r in cursor.fetchall()]
        if not players:
            return
        winner_id = random.choice(players)

        cursor.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (prize, winner_id))
        cursor.execute("DELETE FROM user_lotteries WHERE id = ?", (lid,))
        cursor.execute("DELETE FROM user_lottery_tickets WHERE lottery_id = ?", (lid,))
        conn.commit()

        text = (
            f"🎊 <b>«{title}» — итог</b>\n\n"
            f"Победитель: <code>{winner_id}</code>\n"
            f"Приз: <b>{prize:,}</b> 💎"
        )
        try:
            await message.answer(text, parse_mode="HTML")
        except Exception:
            pass
        for uid in set(players + [creator_id]):
            try:
                await message.bot.send_message(uid, text, parse_mode="HTML")
            except Exception:
                pass
    except Exception:
        logger.exception("finish_user_lottery")


# ─────────────── проведение розыгрышей (фоновые функции) ───────────────

async def run_draw(cfg, bot, notify_fn=None) -> None:
    """Проводит розыгрыш: определяет выигрышные номера, сверяет билеты, закрывает тираж."""
    try:
        draw_id, pool = current_draw(cfg)

        cursor.execute(
            "SELECT id, user_id, numbers FROM lottery_tickets "
            "WHERE lottery_type = ? AND draw_id = ? AND status = 'active'",
            (cfg["key"], draw_id),
        )
        tickets = cursor.fetchall()

        winning_numbers = pick_numbers(cfg["numbers_count"], cfg["numbers_pool"])
        winning_set = set(winning_numbers)
        now = int(time.time())

        if not tickets:
            cursor.execute(
                f"UPDATE {cfg['state']} SET winning_numbers = ?, drawn_at = ? WHERE draw_id = ?",
                (",".join(str(n) for n in winning_numbers), now, draw_id),
            )
            cursor.execute(f"INSERT INTO {cfg['state']} (prize_pool) VALUES (?)", (pool,))
            conn.commit()
            return

        winners_by_tier = {m: [] for m in cfg["prizes"].keys()}
        for tid, uid, nums_str in tickets:
            t_nums = set(int(x) for x in nums_str.split(","))
            matches = len(t_nums & winning_set)
            if matches in winners_by_tier:
                winners_by_tier[matches].append((tid, uid))

        jackpot_tier = max(k for k, v in cfg["prizes"].items() if v == "jackpot")
        payouts = {}
        jackpot_winners = winners_by_tier.get(jackpot_tier, [])
        if jackpot_winners:
            each = pool // len(jackpot_winners)
            for tid, uid in jackpot_winners:
                payouts[tid] = (uid, each)

        for matches, entries in winners_by_tier.items():
            if matches == jackpot_tier or not entries:
                continue
            mult = cfg["prizes"][matches]
            win_amount = cfg["price"] * int(mult)
            for tid, uid in entries:
                payouts[tid] = (uid, win_amount)

        for tid, uid, _ in tickets:
            if tid in payouts:
                _, win_amount = payouts[tid]
                cursor.execute(
                    "UPDATE users SET balance = balance + ? WHERE id = ?",
                    (win_amount, uid),
                )
                cursor.execute(
                    "UPDATE lottery_tickets SET status = 'archived', win = ? WHERE id = ?",
                    (win_amount, tid),
                )
            else:
                cursor.execute(
                    "UPDATE lottery_tickets SET status = 'archived', win = 0 WHERE id = ?",
                    (tid,),
                )

        cursor.execute(
            f"UPDATE {cfg['state']} SET winning_numbers = ?, drawn_at = ? WHERE draw_id = ?",
            (",".join(str(n) for n in winning_numbers), now, draw_id),
        )
        defaults = {"hourly": 100_000, "weekly": 1_000_000, "mega": 5_000_000}
        next_pool = defaults[cfg["key"]]
        if not jackpot_winners:
            next_pool += pool
        cursor.execute(f"INSERT INTO {cfg['state']} (prize_pool) VALUES (?)", (next_pool,))
        conn.commit()

        unique_users = {uid for _, uid, _ in tickets}
        summary = (
            f"{cfg['title']} — тираж #{draw_id}\n"
            f"Выигрышные номера: {format_numbers(winning_numbers)}\n"
            f"Банк: <b>{pool:,}</b> 💎, призы разыграны."
        )
        for uid in unique_users:
            try:
                await bot.send_message(uid, summary, parse_mode="HTML")
            except (TelegramBadRequest, Exception):
                pass
    except Exception:
        logger.exception("lottery run_draw(%s)", cfg["key"])


async def hourly_loop(bot) -> None:
    while True:
        try:
            now = datetime.datetime.now()
            nxt = (now + datetime.timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
            await asyncio.sleep(max(1, (nxt - datetime.datetime.now()).total_seconds()))
            await run_draw(HOURLY, bot)
        except Exception:
            logger.exception("hourly_loop")
            await asyncio.sleep(60)


async def weekly_loop(bot) -> None:
    while True:
        try:
            now = datetime.datetime.now()
            days_ahead = 6 - now.weekday()
            end = (now + datetime.timedelta(days=days_ahead)).replace(hour=23, minute=59, second=30, microsecond=0)
            await asyncio.sleep(max(1, (end - datetime.datetime.now()).total_seconds()))
            await run_draw(WEEKLY, bot)
            await run_draw(MEGA, bot)
            await asyncio.sleep(120)
        except Exception:
            logger.exception("weekly_loop")
            await asyncio.sleep(600)
