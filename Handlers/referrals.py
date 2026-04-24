"""Реферальная система.

Игрок делится ссылкой ``https://t.me/<bot>?start=ref_<id>``. Когда по ней
впервые приходит новый пользователь и создаётся его профиль — связка
сохраняется в таблице ``referrals``. Пригласивший получает:

* разовый бонус при регистрации реферала (``REF_SIGNUP_BONUS``);
* 2% от ставки реферала и 2% от его чистых выигрышей, засчитываемые
  автоматически из :func:`db_update_stats` через :func:`on_activity`.

Ивенты ``ref_mult`` (x2/x3) и ``ref_gift`` модифицируют эти значения
на лету.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional, Tuple

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import conn, cursor

logger = logging.getLogger(__name__)
router = Router()

REF_SIGNUP_BONUS = 10_000      # пригласившему при создании нового профиля
REF_SIGNUP_GIFT  = 2_000       # сам реферал получает на старте
REF_BET_PCT      = 0.02        # 2% со ставок реферала
REF_WIN_PCT      = 0.02        # 2% с чистого выигрыша реферала
REF_COOLDOWN_SEC = 2           # защита от флуда начислений


def _ensure_tables() -> None:
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS referrals (
            referred_id INTEGER PRIMARY KEY,
            referrer_id INTEGER NOT NULL,
            created_at INTEGER NOT NULL,
            signup_bonus_paid INTEGER DEFAULT 0,
            total_earned INTEGER DEFAULT 0,
            last_activity INTEGER DEFAULT 0
        )"""
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_referrals_referrer ON referrals(referrer_id)"
    )
    conn.commit()


_ensure_tables()


def _ref_multiplier() -> float:
    try:
        from Handlers.events import active_events
        mult = 1.0
        for ev in active_events():
            if ev["kind"] == "ref_mult":
                mult = max(mult, float(ev.get("value") or 1.0))
        return mult
    except Exception:
        return 1.0


def _signup_gift_from_event() -> int:
    try:
        from Handlers.events import active_events
        for ev in active_events():
            if ev["kind"] == "ref_gift":
                return int(ev.get("value") or 0)
    except Exception:
        pass
    return 0


def register_referral(referrer_id: int, referred_id: int) -> bool:
    """Связывает реферала с пригласившим. Возвращает True при первой привязке."""
    if referrer_id == referred_id:
        return False
    _ensure_tables()
    cursor.execute("SELECT 1 FROM referrals WHERE referred_id = ?", (referred_id,))
    if cursor.fetchone():
        return False
    cursor.execute("SELECT 1 FROM users WHERE id = ?", (referrer_id,))
    if not cursor.fetchone():
        return False
    try:
        cursor.execute(
            "INSERT INTO referrals (referred_id, referrer_id, created_at) VALUES (?, ?, ?)",
            (referred_id, referrer_id, int(time.time())),
        )
        conn.commit()
        return True
    except Exception:
        logger.exception("register_referral")
        return False


def _pay_signup_bonus(referrer_id: int, referred_id: int) -> int:
    """Выдаёт пригласившему разовый бонус. Возвращает фактическую сумму."""
    _ensure_tables()
    cursor.execute(
        "SELECT signup_bonus_paid FROM referrals WHERE referred_id = ?",
        (referred_id,),
    )
    row = cursor.fetchone()
    if not row or row[0]:
        return 0
    mult = _ref_multiplier()
    payout = int(REF_SIGNUP_BONUS * mult)
    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            "UPDATE users SET balance = balance + ? WHERE id = ?",
            (payout, referrer_id),
        )
        cursor.execute(
            "UPDATE referrals SET signup_bonus_paid = 1, total_earned = total_earned + ? "
            "WHERE referred_id = ?",
            (payout, referred_id),
        )
        conn.commit()
    except Exception:
        cursor.execute("ROLLBACK")
        logger.exception("pay_signup_bonus")
        return 0
    return payout


def on_activity(user_id: int, bet: int, win: int) -> None:
    """Начисляет 2% пригласившему со ставки и чистого выигрыша реферала."""
    if bet <= 0:
        return
    _ensure_tables()
    cursor.execute(
        "SELECT referrer_id, last_activity FROM referrals WHERE referred_id = ?",
        (user_id,),
    )
    row = cursor.fetchone()
    if not row:
        return
    referrer_id, last = row
    now = int(time.time())
    if now - (last or 0) < REF_COOLDOWN_SEC:
        return
    mult = _ref_multiplier()
    cut = int((bet * REF_BET_PCT + max(0, win - bet) * REF_WIN_PCT) * mult)
    if cut <= 0:
        return
    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            "UPDATE users SET balance = balance + ? WHERE id = ?",
            (cut, referrer_id),
        )
        cursor.execute(
            "UPDATE referrals SET total_earned = total_earned + ?, last_activity = ? "
            "WHERE referred_id = ?",
            (cut, now, user_id),
        )
        conn.commit()
    except Exception:
        cursor.execute("ROLLBACK")
        logger.exception("on_activity")


def _get_referrer(user_id: int) -> Optional[int]:
    cursor.execute("SELECT referrer_id FROM referrals WHERE referred_id = ?", (user_id,))
    row = cursor.fetchone()
    return row[0] if row else None


def _stats_for(referrer_id: int) -> Tuple[int, int]:
    cursor.execute(
        "SELECT COUNT(*), COALESCE(SUM(total_earned), 0) FROM referrals WHERE referrer_id = ?",
        (referrer_id,),
    )
    row = cursor.fetchone()
    return (row[0] or 0), (row[1] or 0)


async def _bot_username(message: types.Message) -> str:
    me = await message.bot.get_me()
    return me.username or os.getenv("BOT_USERNAME", "casino_bot")


# ─────────── обработчики ───────────


async def handle_start_referral(message: types.Message) -> None:
    """Вызывается из common.cmd_start. Разбирает ``/start ref_<id>``.

    Связывает реферала с пригласившим и выдаёт бонусы. Безопасно вызывать
    на любом /start: если аргумента нет, функция просто выходит.
    """
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        return
    arg = parts[1].strip()
    if not arg.startswith("ref_"):
        return
    try:
        referrer_id = int(arg[4:])
    except ValueError:
        return
    referred_id = message.from_user.id
    linked = register_referral(referrer_id, referred_id)
    if not linked:
        return
    gift = _signup_gift_from_event()
    if gift > 0:
        try:
            cursor.execute(
                "UPDATE users SET balance = balance + ? WHERE id = ?",
                (gift, referred_id),
            )
            conn.commit()
            await message.answer(
                f"🎁 Приветственный подарок: {gift:,} 💎 за регистрацию по реферальной ссылке."
            )
        except Exception:
            logger.exception("handle_start_referral:gift")
    paid = _pay_signup_bonus(referrer_id, referred_id)
    if paid > 0:
        try:
            await message.bot.send_message(
                referrer_id,
                f"🤝 Новый реферал пришёл! Тебе начислено {paid:,} 💎.",
            )
        except Exception:
            pass


@router.message(Command("ref", "referral", "refs"))
async def ref_cmd(message: types.Message):
    uid = message.from_user.id
    username = await _bot_username(message)
    link = f"https://t.me/{username}?start=ref_{uid}"
    count, earned = _stats_for(uid)
    parent = _get_referrer(uid)
    parent_line = ""
    if parent:
        parent_line = f"\n👥 Твой пригласивший: <code>{parent}</code>"
    mult = _ref_multiplier()
    bonus_hint = ""
    if mult != 1.0:
        bonus_hint = f"\n🎉 Сейчас активен ивент: бонусы рефералки x{mult:g}"
    gift = _signup_gift_from_event()
    if gift > 0:
        bonus_hint += f"\n🎁 Новичкам по ссылке сейчас выдают +{gift:,} 💎."
    text = (
        "🤝 <b>РЕФЕРАЛЬНАЯ ПРОГРАММА</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"Твоя ссылка:\n<code>{link}</code>\n\n"
        f"👥 Приглашено: <b>{count}</b>\n"
        f"💰 Заработано: <b>{earned:,}</b> 💎\n"
        f"🎁 Разовый бонус за нового: {REF_SIGNUP_BONUS:,} 💎\n"
        f"💼 Процент со ставок и чистого выигрыша: {int(REF_BET_PCT*100)}% / {int(REF_WIN_PCT*100)}%"
        f"{parent_line}{bonus_hint}"
    )
    kb = InlineKeyboardBuilder()
    kb.button(
        text="📤 Поделиться",
        url=f"https://t.me/share/url?url={link}&text=%D0%98%D0%B3%D1%80%D0%B0%D0%B9%20%D0%B2%D0%BC%D0%B5%D1%81%D1%82%D0%B5%20%D1%81%D0%BE%20%D0%BC%D0%BD%D0%BE%D0%B9",
    )
    kb.button(text="🏆 Топ рефереров", callback_data="ref:top")
    kb.adjust(1, 1)
    await message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")


@router.callback_query(F.data == "ref:top")
async def ref_top_cb(call: types.CallbackQuery):
    await call.answer()
    cursor.execute(
        "SELECT referrer_id, COUNT(*) AS c, COALESCE(SUM(total_earned), 0) AS e "
        "FROM referrals GROUP BY referrer_id ORDER BY e DESC, c DESC LIMIT 10"
    )
    rows = cursor.fetchall() or []
    if not rows:
        return await call.message.answer("Пока никто никого не пригласил.")
    lines = ["🏆 <b>Топ рефереров:</b>"]
    medals = ["🥇", "🥈", "🥉"]
    for idx, (ref_id, cnt, earned) in enumerate(rows):
        medal = medals[idx] if idx < 3 else f"{idx + 1}."
        lines.append(f"{medal} <code>{ref_id}</code> — {cnt} приглашён., {earned:,} 💎")
    await call.message.answer("\n".join(lines), parse_mode="HTML")
