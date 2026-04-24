"""Колесо фортуны — раз в сутки бесплатно + платные докруты."""
import logging
import random
import time

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import conn, cursor, db_get_user

logger = logging.getLogger(__name__)
router = Router()


SECTORS = [
    {"emoji": "💎", "label": "Мини-джекпот",  "amount": 100_000, "weight": 1},
    {"emoji": "💰", "label": "Большой куш",    "amount": 25_000,  "weight": 4},
    {"emoji": "💵", "label": "Хорошо",         "amount": 10_000,  "weight": 8},
    {"emoji": "🪙", "label": "Мелочь",         "amount": 2_500,   "weight": 18},
    {"emoji": "✨", "label": "Утешительный",   "amount": 500,     "weight": 25},
    {"emoji": "❌", "label": "Пусто",          "amount": 0,       "weight": 44},
]

DAY = 24 * 60 * 60
EXTRA_SPIN_PRICE = 5_000

VIP_WHEEL_CD = {"bronze": 20 * 3600, "silver": 12 * 3600, "gold": 6 * 3600}


def _wheel_cooldown(privilege: str) -> int:
    return VIP_WHEEL_CD.get(privilege or "none", DAY)


def _ensure_column():
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN last_wheel INTEGER DEFAULT 0")
        conn.commit()
    except Exception:
        pass


_ensure_column()


def spin_once() -> dict:
    weights = [s["weight"] for s in SECTORS]
    return random.choices(SECTORS, weights=weights, k=1)[0]


def wheel_menu_text(free_available: bool, seconds_left: int, privilege: str = "none") -> str:
    if free_available:
        status = "🎁 Бесплатный спин доступен прямо сейчас."
    else:
        h = seconds_left // 3600
        m = (seconds_left % 3600) // 60
        status = f"⌛️ Следующий бесплатный спин через <b>{h} ч {m} мин</b>."
    if privilege in ("bronze", "silver", "gold"):
        status += f"\n👑 VIP {privilege} — ускоренный КД."
    sectors = "\n".join(
        f"• {s['emoji']} {s['label']} — {s['amount']:,} 💎 (шанс {s['weight']}%)"
        for s in SECTORS
    )
    return (
        f"🎡 <b>Колесо фортуны</b>\n{status}\n\n"
        f"Сектора:\n{sectors}\n\n"
        f"Доп. прокрут — {EXTRA_SPIN_PRICE:,} 💎."
    )


def wheel_menu_kb(free_available: bool, tokens: int = 0) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    if free_available:
        kb.button(text="🎁 Крутить бесплатно", callback_data="wheel:spin:free")
    if tokens > 0:
        kb.button(text=f"🎡 Жетон ({tokens})", callback_data="wheel:spin:token")
    kb.button(text=f"💸 Крутить за {EXTRA_SPIN_PRICE:,}", callback_data="wheel:spin:paid")
    kb.adjust(1)
    return kb


@router.message(Command("wheel"))
async def wheel_entry(message: types.Message):
    u = db_get_user(message.from_user.id)
    if u[2] == 1:
        return await message.reply("🚫 Вы заблокированы.")

    cursor.execute(
        "SELECT COALESCE(last_wheel, 0), COALESCE(privilege, 'none'), COALESCE(wheel_token, 0) "
        "FROM users WHERE id = ?",
        (message.from_user.id,),
    )
    row = cursor.fetchone() or (0, "none", 0)
    last, privilege, tokens = row[0], row[1], row[2]
    cd = _wheel_cooldown(privilege)
    now = int(time.time())
    free_available = now - last >= cd
    seconds_left = max(0, cd - (now - last))

    await message.answer(
        wheel_menu_text(free_available, seconds_left, privilege),
        reply_markup=wheel_menu_kb(free_available, tokens).as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("wheel:spin:"))
async def wheel_spin(call: types.CallbackQuery):
    await call.answer()
    kind = call.data.split(":")[2]
    user_id = call.from_user.id

    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            "SELECT balance, COALESCE(last_wheel, 0), COALESCE(privilege, 'none') FROM users WHERE id = ?",
            (user_id,),
        )
        row = cursor.fetchone()
        if not row:
            cursor.execute("ROLLBACK")
            return await call.message.answer("❌ Пользователь не найден.")
        balance, last, privilege = row
        cd = _wheel_cooldown(privilege)
        now = int(time.time())

        if kind == "free":
            if now - last < cd:
                cursor.execute("ROLLBACK")
                return await call.message.answer("❌ Бесплатный спин пока недоступен.")
            cursor.execute("UPDATE users SET last_wheel = ? WHERE id = ?", (now, user_id))
        elif kind == "token":
            cursor.execute(
                "UPDATE users SET wheel_token = wheel_token - 1 "
                "WHERE id = ? AND COALESCE(wheel_token, 0) > 0",
                (user_id,),
            )
            if cursor.rowcount == 0:
                cursor.execute("ROLLBACK")
                return await call.message.answer("❌ Жетонов нет.")
        elif kind == "paid":
            if balance < EXTRA_SPIN_PRICE:
                cursor.execute("ROLLBACK")
                return await call.message.answer(
                    f"❌ Нужно {EXTRA_SPIN_PRICE:,} 💎 для платного спина."
                )
            cursor.execute(
                "UPDATE users SET balance = balance - ? WHERE id = ?",
                (EXTRA_SPIN_PRICE, user_id),
            )
        else:
            cursor.execute("ROLLBACK")
            return

        sector = spin_once()
        if sector["amount"] > 0:
            cursor.execute(
                "UPDATE users SET balance = balance + ? WHERE id = ?",
                (sector["amount"], user_id),
            )
        conn.commit()
    except Exception:
        cursor.execute("ROLLBACK")
        logger.exception("wheel: spin failed")
        return await call.message.answer("❌ Ошибка, попробуй ещё раз.")

    new_balance = db_get_user(user_id)[0]
    text = (
        f"🎡 Колесо остановилось на <b>{sector['emoji']} {sector['label']}</b>\n"
        f"Приз: <b>{sector['amount']:,}</b> 💎\n\n"
        f"💳 Баланс: {new_balance:,} 💎"
    )
    await call.message.answer(text, parse_mode="HTML")
