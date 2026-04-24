"""Кланы / гильдии.

Возможности:

* Роли внутри клана: ``owner``, ``officer``, ``member``. Офицеры могут
  кикать участников и управлять тегами клана, владелец — всё.
* Кастомный тег клана: лидер создаёт декоративный тег за монеты из
  магазина кланов, участники могут надеть его в профиль (перезаписывает
  обычный cosmetic_tag).
* Собственный банк клана с депозитами и снятиями (офицер+), журнал
  операций.
* Топ кланов: по недельному и общему банку, с пагинацией.

Таблицы создаются отложенно через ``CREATE IF NOT EXISTS`` — старая БД
не ломается при обновлении.
"""
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

CLAN_CREATE_PRICE   = 50_000
CLAN_TAG_PRICE      = 100_000
CLAN_WITHDRAW_FEE   = 0.05
CLAN_MAX_MEMBERS    = 30
CLAN_NAME_MIN       = 3
CLAN_NAME_MAX       = 24
CLAN_TAG_MAX        = 16

ROLE_LABELS = {
    "owner":   "👑 Лидер",
    "officer": "🛡 Офицер",
    "member":  "• Участник",
}


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
            week_start INTEGER DEFAULT 0,
            tag TEXT DEFAULT ''
        )"""
    )
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS clan_members (
            clan_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL PRIMARY KEY,
            joined_at INTEGER NOT NULL,
            role TEXT DEFAULT 'member',
            wears_tag INTEGER DEFAULT 0
        )"""
    )
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS clan_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clan_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            kind TEXT NOT NULL,
            amount INTEGER NOT NULL,
            created_at INTEGER NOT NULL
        )"""
    )
    conn.commit()
    try:
        cursor.execute("ALTER TABLE clans ADD COLUMN tag TEXT DEFAULT ''")
        conn.commit()
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE clan_members ADD COLUMN wears_tag INTEGER DEFAULT 0")
        conn.commit()
    except Exception:
        pass


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


def _member_role(user_id: int) -> Optional[str]:
    cursor.execute("SELECT role FROM clan_members WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    return row[0] if row else None


def _is_officer(user_id: int) -> bool:
    return _member_role(user_id) in ("owner", "officer")


def _clan_info(clan_id: int) -> Optional[Tuple]:
    cursor.execute(
        "SELECT id, name, owner_id, bank, xp, created_at, week_bank, tag FROM clans WHERE id = ?",
        (clan_id,),
    )
    return cursor.fetchone()


def _clan_members(clan_id: int) -> List[Tuple[int, str]]:
    cursor.execute(
        "SELECT user_id, role FROM clan_members WHERE clan_id = ? ORDER BY role DESC, joined_at",
        (clan_id,),
    )
    return cursor.fetchall() or []


def _log(clan_id: int, user_id: int, kind: str, amount: int) -> None:
    cursor.execute(
        "INSERT INTO clan_ledger (clan_id, user_id, kind, amount, created_at) VALUES (?, ?, ?, ?, ?)",
        (clan_id, user_id, kind, amount, int(time.time())),
    )


def _fmt_ts(ts: int) -> str:
    try:
        import datetime as _dt
        return _dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    except Exception:
        return str(ts)


def clan_tag_for(user_id: int) -> str:
    """Возвращает тег клана игрока, если он его носит (или '')."""
    _ensure_tables()
    cursor.execute(
        "SELECT c.tag FROM clan_members m JOIN clans c ON c.id = m.clan_id "
        "WHERE m.user_id = ? AND m.wears_tag = 1",
        (user_id,),
    )
    row = cursor.fetchone()
    return (row[0] or "") if row else ""


def add_clan_xp(user_id: int, amount: int) -> None:
    """Начисляет XP клану игрока. Зовётся из db_update_stats."""
    if amount <= 0:
        return
    row = _user_clan(user_id)
    if not row:
        return
    try:
        cursor.execute("UPDATE clans SET xp = xp + ? WHERE id = ?", (int(amount), row[0]))
        conn.commit()
    except Exception:
        logger.exception("clans:add_xp")


def _render_clan(clan_id: int) -> str:
    info = _clan_info(clan_id)
    if not info:
        return "Клан не найден."
    cid, name, owner_id, bank, xp, created, week_bank, tag = info
    members = _clan_members(cid)
    tag_line = f"\n🏷 Тег клана: <b>{tag}</b>" if tag else ""
    return (
        f"🛡 <b>{name}</b>{tag_line}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👑 Лидер: <code>{owner_id}</code>\n"
        f"👥 Состав: {len(members)} / {CLAN_MAX_MEMBERS}\n"
        f"🏦 Банк клана: {bank:,} 💎\n"
        f"📈 XP клана: {xp:,}\n"
        f"📅 Банк за неделю: {week_bank:,} 💎\n"
        f"🕰 Создан: <code>{_fmt_ts(created)}</code>"
    )


def _menu_kb(user_id: int) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    row = _user_clan(user_id)
    if row:
        role = _member_role(user_id) or "member"
        kb.button(text="ℹ️ Инфо",       callback_data="cl:info")
        kb.button(text="👥 Состав",     callback_data="cl:members")
        kb.button(text="🏦 Банк",       callback_data="cl:bank")
        kb.button(text="💬 Клан-чат",   callback_data="cl:chat")
        kb.button(text="🏷 Теги",       callback_data="cl:tags")
        kb.button(text="🏆 Топ кланов", callback_data="cl:top:0")
        if role in ("owner", "officer"):
            kb.button(text="⚙️ Управление", callback_data="cl:manage")
        kb.button(text="🚪 Выйти",      callback_data="cl:leave")
        kb.adjust(2, 2, 2, 1, 1)
    else:
        kb.button(text="➕ Создать",    callback_data="cl:new")
        kb.button(text="🚪 Вступить",   callback_data="cl:join")
        kb.button(text="🏆 Топ кланов", callback_data="cl:top:0")
        kb.adjust(2, 1)
    return kb.as_markup()


# ─────────── FSM ───────────


class ClanStates(StatesGroup):
    create_name = State()
    join_name   = State()
    deposit     = State()
    withdraw    = State()
    chat        = State()
    set_tag     = State()
    kick        = State()
    promote     = State()
    demote      = State()


# ─────────── команды ───────────


@router.message(Command("clan", "clans"))
async def clan_menu(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🛡 <b>КЛАНЫ</b>\n"
        "Собери своих: общий банк, свой тег, роли, топ кланов и внутренний чат.",
        reply_markup=_menu_kb(message.from_user.id),
        parse_mode="HTML",
    )


# ─── создание / вступление / выход ───


@router.callback_query(F.data == "cl:new")
async def clan_new_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    if _user_clan(call.from_user.id):
        return await call.message.answer("Ты уже в клане. Сначала выйди.")
    await state.set_state(ClanStates.create_name)
    await call.message.answer(
        f"Введи название клана ({CLAN_NAME_MIN}-{CLAN_NAME_MAX} символов).\n"
        f"Стоимость создания: {CLAN_CREATE_PRICE:,} 💎.",
    )


@router.message(ClanStates.create_name)
async def clan_new_name(message: types.Message, state: FSMContext):
    await state.clear()
    name = (message.text or "").strip()
    if not (CLAN_NAME_MIN <= len(name) <= CLAN_NAME_MAX):
        return await message.answer("❌ Длина названия не подходит.")
    uid = message.from_user.id

    free_create = False
    try:
        from Handlers.events import is_event_active
        free_create = is_event_active("clan_free_create")
    except Exception:
        pass
    price = 0 if free_create else CLAN_CREATE_PRICE

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
        if price > 0:
            cursor.execute(
                "UPDATE users SET balance = balance - ? WHERE id = ? AND balance >= ?",
                (price, uid, price),
            )
            if cursor.rowcount == 0:
                cursor.execute("ROLLBACK")
                return await message.answer(f"❌ Нужно {price:,} 💎.")
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
    extra = " (бесплатно — ивент)" if free_create else ""
    await message.answer(f"✅ Клан <b>{name}</b> основан{extra}!", parse_mode="HTML")


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
    # ивент: подарок за вступление
    try:
        from Handlers.events import active_events
        for ev in active_events():
            if ev["kind"] == "clan_join_gift":
                amount = int(ev.get("value") or 0)
                if amount > 0:
                    cursor.execute(
                        "UPDATE users SET balance = balance + ? WHERE id = ?",
                        (amount, uid),
                    )
                    conn.commit()
                    await message.answer(f"🎁 Ивент-бонус за вступление: {amount:,} 💎.")
                break
    except Exception:
        pass
    await message.answer(f"✅ Ты вступил в <b>{name}</b>.", parse_mode="HTML")


@router.callback_query(F.data == "cl:leave")
async def clan_leave_cb(call: types.CallbackQuery):
    await call.answer()
    uid = call.from_user.id
    row = _user_clan(uid)
    if not row:
        return await call.message.answer("Ты не в клане.")
    clan_id, owner_id, _ = row
    if uid == owner_id:
        cursor.execute("DELETE FROM clan_members WHERE clan_id = ?", (clan_id,))
        cursor.execute("DELETE FROM clan_ledger WHERE clan_id = ?", (clan_id,))
        cursor.execute("DELETE FROM clans WHERE id = ?", (clan_id,))
        conn.commit()
        return await call.message.answer("🛡 Клан распущен (ты был лидером).")
    cursor.execute("DELETE FROM clan_members WHERE user_id = ? AND clan_id = ?", (uid, clan_id))
    conn.commit()
    await call.message.answer("Ты покинул клан.")


# ─── инфо / состав ───


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
    user_ids = [m[0] for m in members]
    role_by_id = {m[0]: m[1] for m in members}
    cursor.execute(
        "SELECT id, custom_id FROM users WHERE id IN (%s)" % ",".join("?" * len(user_ids)),
        user_ids,
    )
    nick_by_id = {r[0]: r[1] for r in (cursor.fetchall() or [])}
    lines = [f"👥 <b>Состав клана:</b> {len(members)}"]
    for uid in user_ids:
        role = role_by_id.get(uid, "member")
        badge = ROLE_LABELS.get(role, "•")
        nick = nick_by_id.get(uid)
        name = f"@{nick}" if nick else f"<code>{uid}</code>"
        lines.append(f"{badge} — {name}")
    await call.message.answer("\n".join(lines), parse_mode="HTML")


# ─── банк ───


@router.callback_query(F.data == "cl:bank")
async def clan_bank_menu(call: types.CallbackQuery):
    await call.answer()
    row = _user_clan(call.from_user.id)
    if not row:
        return await call.message.answer("Ты не в клане.")
    info = _clan_info(row[0])
    cursor.execute(
        "SELECT user_id, kind, amount, created_at FROM clan_ledger "
        "WHERE clan_id = ? ORDER BY id DESC LIMIT 5",
        (row[0],),
    )
    ledger = cursor.fetchall() or []
    led_lines = []
    for uid, kind, amount, ts in ledger:
        sign = "+" if kind == "deposit" else "-"
        led_lines.append(
            f"{_fmt_ts(ts)} · <code>{uid}</code> · {sign}{abs(amount):,} ({kind})"
        )
    led_text = "\n".join(led_lines) if led_lines else "— нет операций —"
    text = (
        f"🏦 <b>Банк клана:</b> {info[3]:,} 💎\n"
        f"📅 За неделю: {info[6]:,}\n"
        f"Комиссия снятия: {int(CLAN_WITHDRAW_FEE * 100)}%\n\n"
        f"<b>Последние операции:</b>\n{led_text}"
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="⬆️ Внести",  callback_data="cl:bank:dep")
    if _is_officer(call.from_user.id):
        kb.button(text="⬇️ Снять", callback_data="cl:bank:wd")
    kb.adjust(2)
    await call.message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")


@router.callback_query(F.data == "cl:bank:dep")
async def clan_bank_dep(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    if not _user_clan(call.from_user.id):
        return await call.message.answer("Ты не в клане.")
    await state.set_state(ClanStates.deposit)
    await call.message.answer("Сколько внести в банк клана?")


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

    effective = amount
    try:
        from Handlers.events import is_event_active
        if is_event_active("clan_bank_x2"):
            effective = amount * 2
    except Exception:
        pass

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
            (effective, effective, clan_id),
        )
        _log(clan_id, uid, "deposit", effective)
        conn.commit()
    except Exception:
        cursor.execute("ROLLBACK")
        logger.exception("clan_deposit")
        return await message.answer("❌ Не удалось пополнить банк.")
    extra = "" if effective == amount else f" (ивент x2 → {effective:,})"
    await message.answer(f"✅ В банк внесено {amount:,} 💎{extra}.")


@router.callback_query(F.data == "cl:bank:wd")
async def clan_bank_wd(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    if not _is_officer(call.from_user.id):
        return await call.message.answer("Снимать могут только лидер и офицеры.")
    await state.set_state(ClanStates.withdraw)
    await call.message.answer(
        f"Сколько снять из банка? Комиссия: {int(CLAN_WITHDRAW_FEE * 100)}%."
    )


@router.message(ClanStates.withdraw)
async def clan_withdraw_amount(message: types.Message, state: FSMContext):
    await state.clear()
    try:
        amount = int((message.text or "0").strip())
    except ValueError:
        return await message.answer("❌ Введи число.")
    if amount <= 0:
        return await message.answer("❌ Сумма должна быть положительной.")
    uid = message.from_user.id
    if not _is_officer(uid):
        return await message.answer("❌ Нет прав.")
    row = _user_clan(uid)
    if not row:
        return await message.answer("Ты не в клане.")
    clan_id = row[0]
    fee = int(amount * CLAN_WITHDRAW_FEE)
    net = amount - fee
    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            "UPDATE clans SET bank = bank - ? WHERE id = ? AND bank >= ?",
            (amount, clan_id, amount),
        )
        if cursor.rowcount == 0:
            cursor.execute("ROLLBACK")
            return await message.answer("❌ В банке недостаточно средств.")
        cursor.execute(
            "UPDATE users SET balance = balance + ? WHERE id = ?", (net, uid)
        )
        _log(clan_id, uid, "withdraw", amount)
        conn.commit()
    except Exception:
        cursor.execute("ROLLBACK")
        logger.exception("clan_withdraw")
        return await message.answer("❌ Не удалось снять.")
    await message.answer(
        f"✅ Снято {amount:,} 💎. Комиссия {fee:,}, на счёт зачислено {net:,}."
    )


# ─── клан-чат ───


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
    for mid, _role in members:
        if mid == uid:
            continue
        try:
            await bot.send_message(mid, body, parse_mode="HTML")
            sent += 1
        except Exception:
            continue
    await message.answer(f"Сообщение доставлено: {sent} из {len(members) - 1}.")


# ─── теги клана ───


@router.callback_query(F.data == "cl:tags")
async def clan_tags_menu(call: types.CallbackQuery):
    await call.answer()
    row = _user_clan(call.from_user.id)
    if not row:
        return await call.message.answer("Ты не в клане.")
    info = _clan_info(row[0])
    tag = info[7] if info else ""
    cursor.execute(
        "SELECT wears_tag FROM clan_members WHERE user_id = ?", (call.from_user.id,)
    )
    wears = cursor.fetchone()
    wears = bool(wears and wears[0])
    status = f"Текущий тег клана: <b>{tag}</b>" if tag else "У клана пока нет тега."
    kb = InlineKeyboardBuilder()
    if _member_role(call.from_user.id) == "owner":
        kb.button(text="✏️ Установить тег", callback_data="cl:tag:set")
        if tag:
            kb.button(text="🗑 Убрать тег",   callback_data="cl:tag:clear")
    if tag:
        if wears:
            kb.button(text="🙈 Снять в профиле", callback_data="cl:tag:off")
        else:
            kb.button(text="🎽 Надеть в профиле", callback_data="cl:tag:on")
    kb.adjust(2, 2)
    await call.message.answer(status, reply_markup=kb.as_markup(), parse_mode="HTML")


@router.callback_query(F.data == "cl:tag:set")
async def clan_tag_set_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    if _member_role(call.from_user.id) != "owner":
        return await call.message.answer("Тег меняет только лидер.")
    await state.set_state(ClanStates.set_tag)
    price = _effective_tag_price()
    await call.message.answer(
        f"Введи тег клана (до {CLAN_TAG_MAX} символов).\n"
        f"Стоимость установки: {price:,} 💎 (списывается с банка клана)."
    )


def _effective_tag_price() -> int:
    try:
        from Handlers.events import active_events
        for ev in active_events():
            if ev["kind"] == "clan_tag_sale":
                return max(1, int(CLAN_TAG_PRICE * (1 - float(ev.get("value") or 0))))
    except Exception:
        pass
    return CLAN_TAG_PRICE


@router.message(ClanStates.set_tag)
async def clan_tag_set_msg(message: types.Message, state: FSMContext):
    await state.clear()
    new_tag = (message.text or "").strip()
    if not (1 <= len(new_tag) <= CLAN_TAG_MAX):
        return await message.answer("❌ Длина тега не подходит.")
    uid = message.from_user.id
    row = _user_clan(uid)
    if not row or _member_role(uid) != "owner":
        return await message.answer("❌ Нет прав.")
    clan_id = row[0]
    price = _effective_tag_price()
    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            "UPDATE clans SET bank = bank - ? WHERE id = ? AND bank >= ?",
            (price, clan_id, price),
        )
        if cursor.rowcount == 0:
            cursor.execute("ROLLBACK")
            return await message.answer(
                f"❌ В банке клана должно быть минимум {price:,} 💎."
            )
        cursor.execute("UPDATE clans SET tag = ? WHERE id = ?", (new_tag, clan_id))
        _log(clan_id, uid, "tag_set", price)
        conn.commit()
    except Exception:
        cursor.execute("ROLLBACK")
        logger.exception("clan_tag_set")
        return await message.answer("❌ Не удалось установить тег.")
    await message.answer(f"🏷 Тег клана установлен: <b>{new_tag}</b>", parse_mode="HTML")


@router.callback_query(F.data == "cl:tag:clear")
async def clan_tag_clear(call: types.CallbackQuery):
    await call.answer()
    if _member_role(call.from_user.id) != "owner":
        return await call.message.answer("Только лидер.")
    row = _user_clan(call.from_user.id)
    if not row:
        return
    cursor.execute("UPDATE clans SET tag = '' WHERE id = ?", (row[0],))
    cursor.execute("UPDATE clan_members SET wears_tag = 0 WHERE clan_id = ?", (row[0],))
    conn.commit()
    await call.message.answer("🗑 Тег клана снят со всех.")


@router.callback_query(F.data == "cl:tag:on")
async def clan_tag_on(call: types.CallbackQuery):
    await call.answer()
    row = _user_clan(call.from_user.id)
    if not row:
        return
    cursor.execute(
        "UPDATE clan_members SET wears_tag = 1 WHERE user_id = ?", (call.from_user.id,)
    )
    conn.commit()
    await call.message.answer("🎽 Тег клана надет. Он будет виден в профиле.")


@router.callback_query(F.data == "cl:tag:off")
async def clan_tag_off(call: types.CallbackQuery):
    await call.answer()
    cursor.execute(
        "UPDATE clan_members SET wears_tag = 0 WHERE user_id = ?", (call.from_user.id,)
    )
    conn.commit()
    await call.message.answer("🙈 Тег клана снят.")


# ─── управление (для офицера/лидера) ───


@router.callback_query(F.data == "cl:manage")
async def clan_manage_menu(call: types.CallbackQuery):
    await call.answer()
    role = _member_role(call.from_user.id)
    if role not in ("owner", "officer"):
        return await call.message.answer("❌ Нет прав.")
    kb = InlineKeyboardBuilder()
    kb.button(text="👢 Кикнуть",  callback_data="cl:manage:kick")
    if role == "owner":
        kb.button(text="⬆️ Повысить",  callback_data="cl:manage:promote")
        kb.button(text="⬇️ Понизить",  callback_data="cl:manage:demote")
    kb.adjust(2)
    await call.message.answer(
        "⚙️ <b>Управление кланом</b>\nВыбери действие.",
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "cl:manage:kick")
async def cl_kick_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    if not _is_officer(call.from_user.id):
        return
    await state.set_state(ClanStates.kick)
    await call.message.answer("Введи ID игрока, которого выкинуть.")


@router.message(ClanStates.kick)
async def cl_kick_msg(message: types.Message, state: FSMContext):
    await state.clear()
    try:
        target = int((message.text or "0").strip())
    except ValueError:
        return await message.answer("❌ Нужен ID числом.")
    uid = message.from_user.id
    if not _is_officer(uid):
        return await message.answer("❌ Нет прав.")
    row = _user_clan(uid)
    target_row = _user_clan(target)
    if not row or not target_row or row[0] != target_row[0]:
        return await message.answer("❌ Игрок не из твоего клана.")
    if target == row[1]:
        return await message.answer("❌ Лидера нельзя кикнуть.")
    if _member_role(target) == "officer" and _member_role(uid) != "owner":
        return await message.answer("❌ Офицеров может кикать только лидер.")
    cursor.execute("DELETE FROM clan_members WHERE user_id = ?", (target,))
    conn.commit()
    await message.answer(f"👢 Игрок <code>{target}</code> выкинут.", parse_mode="HTML")


@router.callback_query(F.data == "cl:manage:promote")
async def cl_promote_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    if _member_role(call.from_user.id) != "owner":
        return
    await state.set_state(ClanStates.promote)
    await call.message.answer("Введи ID игрока для повышения до офицера.")


@router.message(ClanStates.promote)
async def cl_promote_msg(message: types.Message, state: FSMContext):
    await state.clear()
    try:
        target = int((message.text or "0").strip())
    except ValueError:
        return await message.answer("❌ Нужен ID числом.")
    uid = message.from_user.id
    if _member_role(uid) != "owner":
        return await message.answer("❌ Нет прав.")
    row = _user_clan(uid)
    target_row = _user_clan(target)
    if not row or not target_row or row[0] != target_row[0]:
        return await message.answer("❌ Игрок не из твоего клана.")
    if _member_role(target) == "owner":
        return await message.answer("❌ Лидер уже максимальный ранг.")
    cursor.execute(
        "UPDATE clan_members SET role = 'officer' WHERE user_id = ?", (target,)
    )
    conn.commit()
    await message.answer(f"⬆️ <code>{target}</code> повышен до офицера.", parse_mode="HTML")


@router.callback_query(F.data == "cl:manage:demote")
async def cl_demote_cb(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    if _member_role(call.from_user.id) != "owner":
        return
    await state.set_state(ClanStates.demote)
    await call.message.answer("Введи ID офицера для понижения.")


@router.message(ClanStates.demote)
async def cl_demote_msg(message: types.Message, state: FSMContext):
    await state.clear()
    try:
        target = int((message.text or "0").strip())
    except ValueError:
        return await message.answer("❌ Нужен ID числом.")
    uid = message.from_user.id
    if _member_role(uid) != "owner":
        return await message.answer("❌ Нет прав.")
    row = _user_clan(uid)
    target_row = _user_clan(target)
    if not row or not target_row or row[0] != target_row[0]:
        return await message.answer("❌ Игрок не из твоего клана.")
    if _member_role(target) != "officer":
        return await message.answer("❌ Этот игрок не офицер.")
    cursor.execute(
        "UPDATE clan_members SET role = 'member' WHERE user_id = ?", (target,)
    )
    conn.commit()
    await message.answer(f"⬇️ <code>{target}</code> теперь обычный участник.", parse_mode="HTML")


# ─── топ кланов с пагинацией ───


@router.callback_query(F.data.startswith("cl:top:"))
async def clan_top_cb(call: types.CallbackQuery):
    await call.answer()
    page = int(call.data.split(":")[2])
    per = 10
    cursor.execute(
        "SELECT name, week_bank, bank, xp, tag FROM clans "
        "ORDER BY week_bank DESC, bank DESC, xp DESC LIMIT ? OFFSET ?",
        (per, page * per),
    )
    rows = cursor.fetchall() or []
    cursor.execute("SELECT COUNT(*) FROM clans")
    total = cursor.fetchone()[0] or 0
    pages = max(1, (total + per - 1) // per)

    if not rows:
        return await call.message.answer("Пока нет ни одного клана.")
    lines = [f"🏆 <b>Топ кланов · {page + 1}/{pages}</b>"]
    start_idx = page * per
    medals = ["🥇", "🥈", "🥉"]
    for local_i, (name, week_bank, bank, xp, tag) in enumerate(rows):
        global_i = start_idx + local_i
        medal = medals[global_i] if global_i < 3 else f"{global_i + 1}."
        tag_pref = f"{tag} " if tag else ""
        lines.append(
            f"{medal} {tag_pref}<b>{name}</b> — неделя {week_bank:,}, банк {bank:,}, XP {xp:,}"
        )
    kb = InlineKeyboardBuilder()
    if page > 0:
        kb.button(text="⬅️", callback_data=f"cl:top:{page - 1}")
    if page + 1 < pages:
        kb.button(text="➡️", callback_data=f"cl:top:{page + 1}")
    kb.adjust(2)
    await call.message.answer("\n".join(lines), reply_markup=kb.as_markup(), parse_mode="HTML")
