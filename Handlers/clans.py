"""Кланы (гильдии) с общим банком и внутренним чатом через рассылку бота."""
from __future__ import annotations

import logging
import time
from typing import List, Optional, Tuple

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import conn, cursor

logger = logging.getLogger(__name__)
router = Router()

CLAN_CREATE_PRICE = 50_000
CLAN_MAX_MEMBERS = 30
CLAN_NAME_MIN = 3
CLAN_NAME_MAX = 24


def _ensure_tables() -> None:
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS clans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            owner_id INTEGER NOT NULL,
            bank INTEGER DEFAULT 0,
            xp INTEGER DEFAULT 0,
            created_at INTEGER NOT NULL,
            week_bank INTEGER DEFAULT 0,
            week_start INTEGER DEFAULT 0
        )"""
    )
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS clan_members (
            clan_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL PRIMARY KEY,
            joined_at INTEGER NOT NULL,
            role TEXT DEFAULT 'member'
        )"""
    )
    conn.commit()


_ensure_tables()


# ─────────── helpers ───────────


def _user_clan(user_id: int) -> Optional[Tuple[int, int, str]]:
    """Возвращает (clan_id, owner_id, clan_name) или None."""
    _ensure_tables()
    cursor.execute(
        "SELECT c.id, c.owner_id, c.name FROM clan_members m "
        "JOIN clans c ON c.id = m.clan_id WHERE m.user_id = ?",
        (user_id,),
    )
    return cursor.fetchone()


def _clan_info(clan_id: int) -> Optional[Tuple]:
    cursor.execute(
        "SELECT id, name, owner_id, bank, xp, created_at, week_bank FROM clans WHERE id = ?",
        (clan_id,),
    )
    return cursor.fetchone()


def _clan_members(clan_id: int) -> List[int]:
    cursor.execute("SELECT user_id FROM clan_members WHERE clan_id = ?", (clan_id,))
    return [r[0] for r in (cursor.fetchall() or [])]


def _render_clan(clan_id: int) -> str:
    info = _clan_info(clan_id)
    if not info:
        return "Клан не найден."
    cid, name, owner_id, bank, xp, created, week_bank = info
    members = _clan_members(cid)
    return (
        f"🛡 <b>{name}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👑 Лидер: <code>{owner_id}</code>\n"
        f"👥 Состав: {len(members)} / {CLAN_MAX_MEMBERS}\n"
        f"🏦 Общий банк: {bank:,} 💎\n"
        f"📈 XP клана: {xp:,}\n"
        f"📅 Банк за неделю: {week_bank:,} 💎\n"
        f"🕰 Создан: <code>{_fmt_ts(created)}</code>"
    )


def _fmt_ts(ts: int) -> str:
    try:
        import datetime as _dt
        return _dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    except Exception:
        return str(ts)


def _menu_kb(user_id: int) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    row = _user_clan(user_id)
    if row:
        kb.button(text="ℹ️ Инфо",        callback_data="cl:info")
        kb.button(text="👥 Состав",      callback_data="cl:members")
        kb.button(text="🏦 Пополнить",   callback_data="cl:deposit")
        kb.button(text="💬 Клан-чат",    callback_data="cl:chat")
        kb.button(text="🏆 Топ кланов",  callback_data="cl:top")
        kb.button(text="🚪 Выйти",       callback_data="cl:leave")
        kb.adjust(2, 2, 2)
    else:
        kb.button(text="➕ Создать",     callback_data="cl:new")
        kb.button(text="🚪 Вступить",    callback_data="cl:join")
        kb.button(text="🏆 Топ кланов",  callback_data="cl:top")
        kb.adjust(2, 1)
    return kb.as_markup()


def add_clan_xp(user_id: int, amount: int) -> None:
    """Начисляет XP клану игрока. Используется играми после выигрыша."""
    if amount <= 0:
        return
    row = _user_clan(user_id)
    if not row:
        return
    try:
        cursor.execute(
            "UPDATE clans SET xp = xp + ? WHERE id = ?",
            (int(amount), row[0]),
        )
        conn.commit()
    except Exception:
        logger.exception("clans:add_xp")


# ─────────── FSM ───────────


class ClanStates(StatesGroup):
    create_name = State()
    join_name = State()
    deposit = State()
    chat = State()


# ─────────── команды и callbacks ───────────


@router.message(Command("clan", "clans"))
async def clan_menu(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🛡 <b>КЛАНЫ</b>\n"
        "Создай свой или присоединись к чужому. Общий банк, XP и недельный топ — всё тут.",
        reply_markup=_menu_kb(message.from_user.id),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "cl:new")
async def clan_new_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    if _user_clan(call.from_user.id):
        return await call.message.answer("Ты уже в клане. Сначала выйди.")
    await state.set_state(ClanStates.create_name)
    await call.message.answer(
        f"Введи название клана ({CLAN_NAME_MIN}-{CLAN_NAME_MAX} символов).\n"
        f"Создание: {CLAN_CREATE_PRICE:,} 💎.",
    )


@router.message(ClanStates.create_name)
async def clan_new_name(message: types.Message, state: FSMContext):
    await state.clear()
    name = (message.text or "").strip()
    if not (CLAN_NAME_MIN <= len(name) <= CLAN_NAME_MAX):
        return await message.answer("❌ Длина названия не подходит.")
    uid = message.from_user.id
    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute("SELECT 1 FROM clans WHERE name = ?", (name,))
        if cursor.fetchone():
            cursor.execute("ROLLBACK")
            return await message.answer("❌ Клан с таким именем уже есть.")
        cursor.execute("SELECT 1 FROM clan_members WHERE user_id = ?", (uid,))
        if cursor.fetchone():
            cursor.execute("ROLLBACK")
            return await message.answer("❌ Ты уже в клане.")
        cursor.execute(
            "UPDATE users SET balance = balance - ? WHERE id = ? AND balance >= ?",
            (CLAN_CREATE_PRICE, uid, CLAN_CREATE_PRICE),
        )
        if cursor.rowcount == 0:
            cursor.execute("ROLLBACK")
            return await message.answer(
                f"❌ Нужно {CLAN_CREATE_PRICE:,} 💎 для создания клана."
            )
        now = int(time.time())
        cursor.execute(
            "INSERT INTO clans (name, owner_id, created_at, week_start) VALUES (?, ?, ?, ?)",
            (name, uid, now, now),
        )
        clan_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO clan_members (clan_id, user_id, joined_at, role) VALUES (?, ?, ?, 'owner')",
            (clan_id, uid, now),
        )
        conn.commit()
    except Exception:
        cursor.execute("ROLLBACK")
        logger.exception("clan_new")
        return await message.answer("❌ Не удалось создать клан.")
    await message.answer(f"✅ Клан <b>{name}</b> основан!", parse_mode="HTML")


@router.callback_query(F.data == "cl:join")
async def clan_join_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    if _user_clan(call.from_user.id):
        return await call.message.answer("Ты уже в клане.")
    await state.set_state(ClanStates.join_name)
    await call.message.answer("Введи название клана, в который хочешь вступить.")


@router.message(ClanStates.join_name)
async def clan_join_name(message: types.Message, state: FSMContext):
    await state.clear()
    name = (message.text or "").strip()
    uid = message.from_user.id
    cursor.execute("SELECT id FROM clans WHERE name = ?", (name,))
    row = cursor.fetchone()
    if not row:
        return await message.answer("❌ Клан не найден.")
    clan_id = row[0]
    members = _clan_members(clan_id)
    if len(members) >= CLAN_MAX_MEMBERS:
        return await message.answer("❌ Клан переполнен.")
    try:
        cursor.execute(
            "INSERT INTO clan_members (clan_id, user_id, joined_at) VALUES (?, ?, ?)",
            (clan_id, uid, int(time.time())),
        )
        conn.commit()
    except Exception:
        logger.exception("clan_join")
        return await message.answer("❌ Не удалось вступить.")
    await message.answer(f"✅ Ты вступил в <b>{name}</b>.", parse_mode="HTML")


@router.callback_query(F.data == "cl:info")
async def clan_info_cb(call: types.CallbackQuery):
    await call.answer()
    row = _user_clan(call.from_user.id)
    if not row:
        return await call.message.answer("Ты не в клане.")
    await call.message.answer(_render_clan(row[0]), parse_mode="HTML")


@router.callback_query(F.data == "cl:members")
async def clan_members_cb(call: types.CallbackQuery):
    await call.answer()
    row = _user_clan(call.from_user.id)
    if not row:
        return await call.message.answer("Ты не в клане.")
    members = _clan_members(row[0])
    cursor.execute(
        "SELECT id, custom_id FROM users WHERE id IN (%s)" % ",".join("?" * len(members)),
        members,
    )
    rows = cursor.fetchall() or []
    lines = [f"👥 <b>Состав клана:</b> {len(members)}"]
    for uid, nick in rows:
        tag = "👑 " if uid == row[1] else "• "
        name = f"@{nick}" if nick else f"<code>{uid}</code>"
        lines.append(f"{tag}{name}")
    await call.message.answer("\n".join(lines), parse_mode="HTML")


@router.callback_query(F.data == "cl:deposit")
async def clan_deposit_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    if not _user_clan(call.from_user.id):
        return await call.message.answer("Ты не в клане.")
    await state.set_state(ClanStates.deposit)
    await call.message.answer("Введи сумму для пополнения клан-банка.")


@router.message(ClanStates.deposit)
async def clan_deposit_amount(message: types.Message, state: FSMContext):
    await state.clear()
    try:
        amount = int((message.text or "0").strip())
    except ValueError:
        return await message.answer("❌ Введи число.")
    if amount <= 0:
        return await message.answer("❌ Сумма должна быть положительной.")
    uid = message.from_user.id
    row = _user_clan(uid)
    if not row:
        return await message.answer("Ты не в клане.")
    clan_id = row[0]

    # Ивент: двойной взнос
    try:
        from Handlers.events import is_event_active
        if is_event_active("clan_bank_x2"):
            amount_effective = amount * 2
        else:
            amount_effective = amount
    except Exception:
        amount_effective = amount

    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            "UPDATE users SET balance = balance - ? WHERE id = ? AND balance >= ?",
            (amount, uid, amount),
        )
        if cursor.rowcount == 0:
            cursor.execute("ROLLBACK")
            return await message.answer("❌ Недостаточно средств.")
        cursor.execute(
            "UPDATE clans SET bank = bank + ?, week_bank = week_bank + ? WHERE id = ?",
            (amount_effective, amount_effective, clan_id),
        )
        conn.commit()
    except Exception:
        cursor.execute("ROLLBACK")
        logger.exception("clan_deposit")
        return await message.answer("❌ Не удалось пополнить банк.")
    extra = "" if amount_effective == amount else f" (с ивентом — {amount_effective:,})"
    await message.answer(
        f"✅ В банк внесено {amount:,} 💎{extra}.",
        parse_mode="HTML",
    )


@router.callback_query(F.data == "cl:chat")
async def clan_chat_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    if not _user_clan(call.from_user.id):
        return await call.message.answer("Ты не в клане.")
    await state.set_state(ClanStates.chat)
    await call.message.answer(
        "💬 Следующее сообщение будет отправлено всем членам твоего клана."
    )


@router.message(ClanStates.chat)
async def clan_chat_send(message: types.Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    row = _user_clan(uid)
    if not row:
        return await message.answer("Ты не в клане.")
    clan_id, _, clan_name = row
    members = _clan_members(clan_id)
    text_body = (message.text or "").strip()
    if not text_body:
        return await message.answer("Пустое сообщение не отправлено.")
    author = f"@{message.from_user.username}" if message.from_user.username else f"id{uid}"
    body = f"🛡 <b>[{clan_name}]</b> {author}:\n{text_body}"
    bot = message.bot
    sent = 0
    for mid in members:
        if mid == uid:
            continue
        try:
            await bot.send_message(mid, body, parse_mode="HTML")
            sent += 1
        except Exception:
            continue
    await message.answer(f"Сообщение доставлено: {sent} из {len(members) - 1}.")


@router.callback_query(F.data == "cl:leave")
async def clan_leave_cb(call: types.CallbackQuery):
    await call.answer()
    uid = call.from_user.id
    row = _user_clan(uid)
    if not row:
        return await call.message.answer("Ты не в клане.")
    clan_id, owner_id, _ = row
    if uid == owner_id:
        # Лидер не может просто выйти — удаляем клан целиком
        cursor.execute("DELETE FROM clan_members WHERE clan_id = ?", (clan_id,))
        cursor.execute("DELETE FROM clans WHERE id = ?", (clan_id,))
        conn.commit()
        return await call.message.answer("🛡 Клан распущен (ты был лидером).")
    cursor.execute("DELETE FROM clan_members WHERE user_id = ? AND clan_id = ?", (uid, clan_id))
    conn.commit()
    await call.message.answer("Ты покинул клан.")


@router.callback_query(F.data == "cl:top")
async def clan_top_cb(call: types.CallbackQuery):
    await call.answer()
    cursor.execute(
        "SELECT name, week_bank, bank, xp FROM clans ORDER BY week_bank DESC, bank DESC LIMIT 10"
    )
    rows = cursor.fetchall() or []
    if not rows:
        return await call.message.answer("Пока нет ни одного клана.")
    lines = ["🏆 <b>Топ кланов недели:</b>"]
    medals = ["🥇", "🥈", "🥉"]
    for idx, (name, week_bank, bank, xp) in enumerate(rows):
        medal = medals[idx] if idx < 3 else f"{idx + 1}."
        lines.append(f"{medal} <b>{name}</b> — неделя {week_bank:,}, банк {bank:,}, XP {xp:,}")
    await call.message.answer("\n".join(lines), parse_mode="HTML")
