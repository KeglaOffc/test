"""Боевой пропуск: 30 уровней, бесплатная и платная ветки."""
from __future__ import annotations

import logging
import time
from typing import Dict, List

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import conn, cursor

logger = logging.getLogger(__name__)
router = Router()

LEVELS = 30
XP_PER_LEVEL = 300
PREMIUM_PRICE = 500_000


def _reward(kind: str, amount: int = 0, item: str = "", qty: int = 0, label: str = "") -> Dict:
    return {"kind": kind, "amount": amount, "item": item, "qty": qty, "label": label}


def _tier(level: int, free: Dict, premium: Dict) -> Dict:
    xp_to = level * XP_PER_LEVEL
    return {"level": level, "xp_total": xp_to, "free": free, "premium": premium}


# Каталог наград на 30 уровней
TIERS: List[Dict] = []


def _build_tiers() -> None:
    coin = lambda n: _reward("coin", amount=n, label=f"{n:,} 💎")
    item = lambda key, q, label: _reward("item", item=key, qty=q, label=label)

    TIERS.append(_tier(1,  coin(5_000),        item("scratch_pack", 1, "🎟 Скретч ×1")))
    TIERS.append(_tier(2,  item("mine_shield", 1, "🛡 Щит мин ×1"), coin(25_000)))
    TIERS.append(_tier(3,  coin(10_000),        item("gold_ticket", 1, "🎫 Зол. билет")))
    TIERS.append(_tier(4,  item("mine_scan", 1, "🔍 Сканер ×1"), item("wheel_token", 1, "🎡 Жетон")))
    TIERS.append(_tier(5,  coin(25_000),        coin(80_000)))
    TIERS.append(_tier(6,  item("rerolls", 1, "🔄 Реролл"), item("energy_drink", 2, "⚡️ Энергетик ×2")))
    TIERS.append(_tier(7,  coin(15_000),        item("scratch_pack", 3, "🎟 Скретч ×3")))
    TIERS.append(_tier(8,  item("gold_ticket", 1, "🎫 Зол. билет"), coin(100_000)))
    TIERS.append(_tier(9,  coin(20_000),        item("bet_insure", 2, "🃏 Страховка ×2")))
    TIERS.append(_tier(10, item("mine_shield", 2, "🛡 Щит ×2"), _reward("privilege", amount=1, label="🥉 VIP-Bronze 24ч")))
    TIERS.append(_tier(11, coin(30_000),        coin(150_000)))
    TIERS.append(_tier(12, item("mine_scan", 2, "🔍 Сканер ×2"), item("wheel_token", 3, "🎡 Жетон ×3")))
    TIERS.append(_tier(13, coin(40_000),        item("scratch_pack", 5, "🎟 Скретч ×5")))
    TIERS.append(_tier(14, item("energy_drink", 1, "⚡️ Энергетик"), coin(200_000)))
    TIERS.append(_tier(15, coin(50_000),        _reward("privilege", amount=2, label="🥈 VIP-Silver 24ч")))
    TIERS.append(_tier(16, item("rerolls", 2, "🔄 Реролл ×2"), item("gold_ticket", 2, "🎫 Зол. билет ×2")))
    TIERS.append(_tier(17, coin(60_000),        coin(250_000)))
    TIERS.append(_tier(18, item("mine_shield", 3, "🛡 Щит ×3"), item("mine_scan", 3, "🔍 Сканер ×3")))
    TIERS.append(_tier(19, coin(80_000),        item("scratch_pack", 10, "🎟 Скретч ×10")))
    TIERS.append(_tier(20, item("bet_insure", 3, "🃏 Страховка ×3"), coin(400_000)))
    TIERS.append(_tier(21, coin(100_000),       _reward("privilege", amount=3, label="🥇 VIP-Gold 24ч")))
    TIERS.append(_tier(22, item("wheel_token", 2, "🎡 Жетон ×2"), coin(500_000)))
    TIERS.append(_tier(23, coin(120_000),       item("gold_ticket", 3, "🎫 Зол. билет ×3")))
    TIERS.append(_tier(24, item("mine_scan", 4, "🔍 Сканер ×4"), item("scratch_pack", 15, "🎟 Скретч ×15")))
    TIERS.append(_tier(25, coin(150_000),       coin(700_000)))
    TIERS.append(_tier(26, item("mine_shield", 5, "🛡 Щит ×5"), item("wheel_token", 5, "🎡 Жетон ×5")))
    TIERS.append(_tier(27, coin(200_000),       item("gold_ticket", 5, "🎫 Зол. билет ×5")))
    TIERS.append(_tier(28, item("rerolls", 3, "🔄 Реролл ×3"), coin(1_000_000)))
    TIERS.append(_tier(29, coin(300_000),       item("scratch_pack", 30, "🎟 Скретч ×30")))
    TIERS.append(_tier(30, _reward("coin", amount=500_000, label="500 000 💎"), _reward("coin", amount=3_000_000, label="💎 Золотой сундук 3M")))


_build_tiers()
assert len(TIERS) == LEVELS


def _ensure_tables() -> None:
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS battlepass (
            user_id INTEGER PRIMARY KEY,
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 0,
            premium INTEGER DEFAULT 0,
            free_claimed TEXT DEFAULT '',
            premium_claimed TEXT DEFAULT '',
            season INTEGER DEFAULT 1,
            updated_at INTEGER DEFAULT 0
        )"""
    )
    conn.commit()


_ensure_tables()


def _get_state(user_id: int) -> Dict:
    _ensure_tables()
    cursor.execute(
        "SELECT xp, level, premium, free_claimed, premium_claimed FROM battlepass WHERE user_id = ?",
        (user_id,),
    )
    row = cursor.fetchone()
    if not row:
        cursor.execute(
            "INSERT INTO battlepass (user_id, updated_at) VALUES (?, ?)",
            (user_id, int(time.time())),
        )
        conn.commit()
        return {"xp": 0, "level": 0, "premium": 0, "free": set(), "prem": set()}
    xp, level, prem, fc, pc = row
    return {
        "xp": xp,
        "level": level,
        "premium": prem,
        "free": {int(x) for x in fc.split(",") if x},
        "prem": {int(x) for x in pc.split(",") if x},
    }


def _save_state(user_id: int, st: Dict) -> None:
    cursor.execute(
        "UPDATE battlepass SET xp = ?, level = ?, premium = ?, free_claimed = ?, "
        "premium_claimed = ?, updated_at = ? WHERE user_id = ?",
        (
            st["xp"],
            st["level"],
            st["premium"],
            ",".join(str(x) for x in sorted(st["free"])),
            ",".join(str(x) for x in sorted(st["prem"])),
            int(time.time()),
            user_id,
        ),
    )
    conn.commit()


def _level_for_xp(xp: int) -> int:
    return min(LEVELS, xp // XP_PER_LEVEL)


# ─────────── публичные хуки ───────────


def add_xp(user_id: int, amount: int) -> None:
    """Начисляет XP игроку. Вызывается из игровых handlers.

    Учитывает активные ивенты xp_mult.
    """
    if amount <= 0:
        return
    try:
        from Handlers.events import active_events
        for ev in active_events():
            if ev["kind"] == "xp_mult":
                amount = int(amount * float(ev.get("value") or 1.0))
    except Exception:
        pass
    st = _get_state(user_id)
    st["xp"] = min(XP_PER_LEVEL * LEVELS, st["xp"] + amount)
    st["level"] = _level_for_xp(st["xp"])
    _save_state(user_id, st)


# ─────────── UI ───────────


def _render_bp(user_id: int) -> str:
    st = _get_state(user_id)
    level = st["level"]
    xp = st["xp"]
    next_lvl_xp = min(LEVELS, level + 1) * XP_PER_LEVEL
    progress_pct = int(100 * xp / (XP_PER_LEVEL * LEVELS))
    bar = "█" * (progress_pct // 5) + "░" * (20 - progress_pct // 5)
    prem = "✅ активен" if st["premium"] else "❌ нет"
    free_ready = sum(1 for i in range(1, level + 1) if i not in st["free"])
    prem_ready = sum(1 for i in range(1, level + 1) if i not in st["prem"]) if st["premium"] else 0
    return (
        "<b>🎫 БОЕВОЙ ПРОПУСК · СЕЗОН 1</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"Уровень: <b>{level}/{LEVELS}</b>\n"
        f"XP: <b>{xp:,}</b> / {LEVELS * XP_PER_LEVEL:,}\n"
        f"[<code>{bar}</code>] {progress_pct}%\n"
        f"Премиум: {prem}\n"
        f"До следующего уровня: {max(0, next_lvl_xp - xp)} XP\n\n"
        f"Готовы к получению — бесплатно: <b>{free_ready}</b>"
        + (f", премиум: <b>{prem_ready}</b>" if st["premium"] else "")
    )


def _bp_menu_kb(has_premium: bool) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🎁 Забрать бесплатные",  callback_data="bp:claim:free")
    if has_premium:
        kb.button(text="💎 Забрать премиум",    callback_data="bp:claim:prem")
    else:
        kb.button(text=f"🛒 Премиум ({PREMIUM_PRICE:,})", callback_data="bp:buy")
    kb.button(text="📜 Награды", callback_data="bp:rewards:0")
    kb.button(text="❌ Закрыть", callback_data="bp:close")
    kb.adjust(2, 2)
    return kb.as_markup()


@router.message(Command("bp", "pass", "battlepass"))
async def bp_cmd(message: types.Message):
    st = _get_state(message.from_user.id)
    await message.answer(
        _render_bp(message.from_user.id),
        reply_markup=_bp_menu_kb(bool(st["premium"])),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "bp:close")
async def bp_close(call: types.CallbackQuery):
    await call.answer()
    try:
        await call.message.delete()
    except Exception:
        pass


@router.callback_query(F.data == "bp:buy")
async def bp_buy(call: types.CallbackQuery):
    await call.answer()
    uid = call.from_user.id

    discount = 0.0
    try:
        from Handlers.events import active_events
        for ev in active_events():
            if ev["kind"] == "bp_sale":
                discount = max(discount, float(ev.get("value") or 0))
    except Exception:
        pass
    price = int(PREMIUM_PRICE * (1 - discount))
    price = max(1, price)

    try:
        cursor.execute("BEGIN IMMEDIATE")
        st = _get_state(uid)
        if st["premium"]:
            cursor.execute("ROLLBACK")
            return await call.message.answer("Премиум уже активен.")
        cursor.execute(
            "UPDATE users SET balance = balance - ? WHERE id = ? AND balance >= ?",
            (price, uid, price),
        )
        if cursor.rowcount == 0:
            cursor.execute("ROLLBACK")
            return await call.message.answer(f"❌ Нужно {price:,} 💎.")
        cursor.execute("UPDATE battlepass SET premium = 1 WHERE user_id = ?", (uid,))
        conn.commit()
    except Exception:
        cursor.execute("ROLLBACK")
        logger.exception("bp:buy")
        return await call.message.answer("❌ Ошибка покупки.")
    await call.message.answer(f"💎 Премиум активирован за {price:,} 💎!")


def _apply_reward(user_id: int, reward: Dict) -> str:
    kind = reward["kind"]
    if kind == "coin":
        amount = int(reward.get("amount") or 0)
        cursor.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (amount, user_id))
        return f"+{amount:,} 💎"
    if kind == "item":
        item = reward["item"]
        qty = int(reward.get("qty") or 1)
        # whitelist колонок, которые безопасно прибавлять
        allowed = {
            "mine_shield", "mine_scan", "rerolls", "bet_insure", "safe_box",
            "gold_ticket", "energy_drink", "scratch_pack", "wheel_token",
        }
        if item not in allowed:
            return "(неизвестный предмет)"
        cursor.execute(
            f"UPDATE users SET {item} = COALESCE({item}, 0) + ? WHERE id = ?",
            (qty, user_id),
        )
        return reward.get("label") or f"+{qty} {item}"
    if kind == "privilege":
        level = int(reward.get("amount") or 1)
        name = {1: "bronze", 2: "silver", 3: "gold"}.get(level, "bronze")
        ends = int(time.time()) + 24 * 3600
        cursor.execute(
            "UPDATE users SET privilege = ?, priv_end = ? WHERE id = ?",
            (name, ends, user_id),
        )
        return reward.get("label") or f"{name} 24ч"
    return "?"


@router.callback_query(F.data.startswith("bp:claim:"))
async def bp_claim(call: types.CallbackQuery):
    await call.answer()
    track = call.data.split(":")[2]
    uid = call.from_user.id
    st = _get_state(uid)
    if track == "prem" and not st["premium"]:
        return await call.message.answer("Сначала купи премиум.")
    claimed_key = "free" if track == "free" else "prem"
    claimed: set = st[claimed_key]

    collected: List[str] = []
    try:
        cursor.execute("BEGIN IMMEDIATE")
        for tier in TIERS:
            lvl = tier["level"]
            if lvl > st["level"]:
                break
            if lvl in claimed:
                continue
            reward = tier["free"] if track == "free" else tier["premium"]
            res = _apply_reward(uid, reward)
            claimed.add(lvl)
            collected.append(f"L{lvl}: {res}")
        st[claimed_key] = claimed
        _save_state(uid, st)
        conn.commit()
    except Exception:
        cursor.execute("ROLLBACK")
        logger.exception("bp:claim")
        return await call.message.answer("❌ Ошибка получения наград.")

    if not collected:
        return await call.message.answer("Пока нечего забирать.")
    text = "🎁 <b>Получено:</b>\n" + "\n".join(collected)
    await call.message.answer(text, parse_mode="HTML")


@router.callback_query(F.data.startswith("bp:rewards:"))
async def bp_rewards_list(call: types.CallbackQuery):
    await call.answer()
    page = int(call.data.split(":")[2])
    per = 10
    pages = (LEVELS + per - 1) // per
    page = max(0, min(page, pages - 1))
    chunk = TIERS[page * per : page * per + per]
    lines = [f"📜 <b>Награды ({page + 1}/{pages})</b>"]
    for tier in chunk:
        free_lbl = tier["free"].get("label") or tier["free"]["kind"]
        prem_lbl = tier["premium"].get("label") or tier["premium"]["kind"]
        lines.append(f"L{tier['level']}: 🎁 {free_lbl} | 💎 {prem_lbl}")
    kb = InlineKeyboardBuilder()
    if page > 0:
        kb.button(text="⬅️", callback_data=f"bp:rewards:{page - 1}")
    if page + 1 < pages:
        kb.button(text="➡️", callback_data=f"bp:rewards:{page + 1}")
    kb.button(text="🔙 Назад", callback_data="bp:back")
    kb.adjust(2, 1)
    await call.message.edit_text("\n".join(lines), reply_markup=kb.as_markup(), parse_mode="HTML")


@router.callback_query(F.data == "bp:back")
async def bp_back(call: types.CallbackQuery):
    await call.answer()
    st = _get_state(call.from_user.id)
    await call.message.edit_text(
        _render_bp(call.from_user.id),
        reply_markup=_bp_menu_kb(bool(st["premium"])),
        parse_mode="HTML",
    )
