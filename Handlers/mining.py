"""Майнинг-симулятор.

Игрок собирает ферму из устройств (CPU / GPU / ASIC / облака), каждое приносит
доход в секунду, пропорциональный его хэшрейту. Износ (wear) со временем
падает → падает доходность. Есть ремонт, продажа, расширение слотов.

Весь модуль рассчитан на то, чтобы быть простым и предсказуемым: никаких
«авто-оптимизаций» и скрытых событий. Доход считается от последнего сбора.
"""
import logging
import time
from typing import Dict, Optional, Tuple

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import conn, cursor, db_get_user

logger = logging.getLogger(__name__)
router = Router()


HS_TO_COINS_PER_HOUR = 1.0
INCOME_CAP_HOURS = 8
SELL_REFUND = 0.5
START_SLOTS = 3
MAX_SLOTS = 12
SLOT_BASE_PRICE = 50_000

CATALOG: Dict[str, Dict] = {
    # CPU
    "cpu_old":     {"name": "🖥 Старый ПК",           "price": 1_000,     "hs": 2,      "watt": 1,    "cat": "cpu"},
    "cpu_i3":      {"name": "🖥 Core i3 офисный",      "price": 2_500,     "hs": 5,      "watt": 3,    "cat": "cpu"},
    "cpu_xeon":    {"name": "🖥 Xeon Gold",            "price": 7_000,     "hs": 18,     "watt": 8,    "cat": "cpu"},
    "cpu_ripper":  {"name": "🖥 AMD Threadripper",     "price": 15_000,    "hs": 45,     "watt": 15,   "cat": "cpu"},

    # GPU
    "gpu_1050":    {"name": "🎮 GTX 1050 Ti",          "price": 15_000,    "hs": 40,     "watt": 10,   "cat": "gpu"},
    "gpu_2060":    {"name": "🎮 RTX 2060 Super",       "price": 35_000,    "hs": 110,    "watt": 25,   "cat": "gpu"},
    "gpu_3080":    {"name": "🎮 RTX 3080 Ti",          "price": 90_000,    "hs": 320,    "watt": 50,   "cat": "gpu"},
    "gpu_4090":    {"name": "🎮 RTX 4090",              "price": 250_000,   "hs": 850,    "watt": 120,  "cat": "gpu"},

    # ASIC
    "asic_s9":     {"name": "⚙️ Antminer S9",          "price": 150_000,   "hs": 650,    "watt": 130,  "cat": "asic"},
    "asic_s19":    {"name": "⚙️ Antminer S19 Pro",     "price": 600_000,   "hs": 3_200,  "watt": 450,  "cat": "asic"},
    "asic_ks3":    {"name": "⚙️ IceRiver KS3",         "price": 4_000_000, "hs": 25_000, "watt": 2_000,"cat": "asic"},

    # Cloud (no wear, no wattage)
    "cloud_start": {"name": "☁️ Cloud Start",          "price": 100_000,   "hs": 350,    "watt": 0,    "cat": "cloud", "no_wear": True},
    "cloud_basic": {"name": "☁️ Cloud Basic",          "price": 500_000,   "hs": 1_800,  "watt": 0,    "cat": "cloud", "no_wear": True},
    "cloud_pro":   {"name": "☁️ Cloud Pro",            "price": 2_500_000, "hs": 10_000, "watt": 0,    "cat": "cloud", "no_wear": True},
}

CAT_LABELS = {
    "cpu": "🖥 CPU",
    "gpu": "🎮 GPU",
    "asic": "⚙️ ASIC",
    "cloud": "☁️ Облако",
}


def _now() -> int:
    return int(time.time())


def _get_farm(user_id: int) -> Tuple[float, int, int, int]:
    """Возвращает (total_hs, total_watt, last_collect, slots). Создаёт запись, если нет."""
    cursor.execute(
        "SELECT total_hs, total_watt, last_collect, slots FROM mining_farms WHERE user_id = ?",
        (user_id,),
    )
    row = cursor.fetchone()
    if row:
        return float(row[0] or 0), int(row[1] or 0), int(row[2] or 0), int(row[3] or START_SLOTS)
    cursor.execute(
        "INSERT INTO mining_farms (user_id, total_hs, total_watt, last_collect, slots) VALUES (?, 0, 0, ?, ?)",
        (user_id, _now(), START_SLOTS),
    )
    conn.commit()
    return 0.0, 0, _now(), START_SLOTS


def _recalc_farm(user_id: int) -> Tuple[float, int]:
    """Пересчитывает total_hs / total_watt фермы по текущему списку устройств с учётом износа."""
    cursor.execute(
        "SELECT hs, watt, wear FROM mining_items WHERE user_id = ?",
        (user_id,),
    )
    rows = cursor.fetchall()
    total_hs = 0.0
    total_watt = 0
    for hs, watt, wear in rows:
        mult = max(0.0, (wear or 0) / 100.0)
        total_hs += float(hs) * mult
        total_watt += int(watt)
    cursor.execute(
        "UPDATE mining_farms SET total_hs = ?, total_watt = ? WHERE user_id = ?",
        (total_hs, total_watt, user_id),
    )
    conn.commit()
    return total_hs, total_watt


def _pending_income(total_hs: float, last_collect: int) -> int:
    if total_hs <= 0:
        return 0
    elapsed = max(0, _now() - last_collect)
    hours = min(INCOME_CAP_HOURS, elapsed / 3600.0)
    return int(total_hs * hours * HS_TO_COINS_PER_HOUR)


def _apply_wear_decay(user_id: int, last_collect: int) -> None:
    """Плавно снижает износ «железных» устройств со временем (~1% в час)."""
    elapsed = max(0, _now() - last_collect)
    if elapsed <= 0:
        return
    hours = elapsed / 3600.0
    loss = min(100.0, hours * 1.0)
    cursor.execute(
        "UPDATE mining_items SET wear = MAX(0, wear - ?) "
        "WHERE user_id = ? AND name NOT LIKE '☁️%'",
        (loss, user_id),
    )
    conn.commit()


def _slot_price(slots: int) -> int:
    return SLOT_BASE_PRICE * (2 ** (slots - START_SLOTS))


# ─────────────── меню и экраны ───────────────

def _menu_text(user_id: int) -> str:
    total_hs, total_watt, last_collect, slots = _get_farm(user_id)
    _apply_wear_decay(user_id, last_collect)
    total_hs, total_watt = _recalc_farm(user_id)
    pending = _pending_income(total_hs, last_collect)

    cursor.execute("SELECT COUNT(*) FROM mining_items WHERE user_id = ?", (user_id,))
    used = cursor.fetchone()[0]

    balance = db_get_user(user_id)[0]
    return (
        "⛏ <b>Майнинг-ферма</b>\n\n"
        f"💳 Баланс: <b>{balance:,}</b> 💎\n"
        f"⚡ Хэшрейт (с учётом износа): <b>{total_hs:,.0f}</b> H/s\n"
        f"🔌 Потребление: <b>{total_watt:,}</b> Вт\n"
        f"📦 Слоты: <b>{used}/{slots}</b>\n\n"
        f"💰 Накоплено к сбору: <b>{pending:,}</b> 💎\n"
        f"<i>Копится не дольше {INCOME_CAP_HOURS} ч. после последнего сбора.</i>"
    )


def _menu_kb() -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="💰 Собрать",        callback_data="mn:collect")
    kb.button(text="🛒 Купить железо",  callback_data="mn:shop")
    kb.button(text="🧰 Мои устройства",  callback_data="mn:list")
    kb.button(text="📦 Купить слот",    callback_data="mn:slot")
    kb.button(text="ℹ️ Как это работает", callback_data="mn:help")
    kb.button(text="❌ Закрыть",         callback_data="mn:close")
    kb.adjust(2, 2, 2)
    return kb.as_markup()


@router.message(Command("mining"))
async def mining_cmd(message: types.Message):
    db_get_user(message.from_user.id)
    await message.answer(_menu_text(message.from_user.id), reply_markup=_menu_kb(), parse_mode="HTML")


@router.callback_query(F.data == "mn:main")
async def mn_main(call: types.CallbackQuery):
    await call.answer()
    try:
        await call.message.edit_text(_menu_text(call.from_user.id), reply_markup=_menu_kb(), parse_mode="HTML")
    except Exception:
        await call.message.answer(_menu_text(call.from_user.id), reply_markup=_menu_kb(), parse_mode="HTML")


@router.callback_query(F.data == "mn:close")
async def mn_close(call: types.CallbackQuery):
    await call.answer()
    try:
        await call.message.delete()
    except Exception:
        pass


@router.callback_query(F.data == "mn:help")
async def mn_help(call: types.CallbackQuery):
    await call.answer()
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data="mn:main")
    try:
        await call.message.edit_text(
            "ℹ️ <b>Как устроен майнинг</b>\n\n"
            "1. Покупаешь устройство в «🛒 Купить железо» — оно встаёт в свободный слот.\n"
            "2. Суммарный H/s всех устройств приносит 💎 в час (1 H/s = 1 💎/ч).\n"
            "3. Износ «железных» устройств (не облачных) падает примерно на 1% в час.\n"
            "   Износ 50% — доход урезан наполовину; износ 0 — устройство не работает.\n"
            "4. «🔧 Ремонт» восстанавливает износ, цена = 10% от цены устройства за 100 пунктов.\n"
            "5. «💰 Собрать» переводит накопленное на баланс. Потолок — 8 часов простоя.\n"
            "6. Новые слоты покупаются по нарастающей (каждый дороже предыдущего).",
            reply_markup=kb.as_markup(),
            parse_mode="HTML",
        )
    except Exception:
        pass


@router.callback_query(F.data == "mn:collect")
async def mn_collect(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    total_hs, _, last_collect, _ = _get_farm(user_id)
    _apply_wear_decay(user_id, last_collect)
    total_hs, _ = _recalc_farm(user_id)
    pending = _pending_income(total_hs, last_collect)

    if pending <= 0:
        return await call.answer("Пока копить нечего.", show_alert=True)

    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            "UPDATE users SET balance = balance + ? WHERE id = ?",
            (pending, user_id),
        )
        cursor.execute(
            "UPDATE mining_farms SET last_collect = ? WHERE user_id = ?",
            (_now(), user_id),
        )
        conn.commit()
    except Exception:
        cursor.execute("ROLLBACK")
        logger.exception("mining:collect")
        return await call.answer("❌ Ошибка сбора.", show_alert=True)

    await call.answer(f"✅ Зачислено {pending:,} 💎", show_alert=True)
    try:
        await call.message.edit_text(_menu_text(user_id), reply_markup=_menu_kb(), parse_mode="HTML")
    except Exception:
        pass


# ─────────────── магазин ───────────────

def _shop_cats_kb() -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for cat, label in CAT_LABELS.items():
        kb.button(text=label, callback_data=f"mn:shop:{cat}")
    kb.button(text="⬅️ Назад", callback_data="mn:main")
    kb.adjust(2, 2, 1)
    return kb.as_markup()


@router.callback_query(F.data == "mn:shop")
async def mn_shop(call: types.CallbackQuery):
    await call.answer()
    try:
        await call.message.edit_text(
            "🛒 <b>Магазин оборудования</b>\n\nВыбери категорию:",
            reply_markup=_shop_cats_kb(),
            parse_mode="HTML",
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("mn:shop:"))
async def mn_shop_cat(call: types.CallbackQuery):
    await call.answer()
    cat = call.data.split(":")[2]
    items = [(key, data) for key, data in CATALOG.items() if data["cat"] == cat]
    if not items:
        return

    lines = [f"{CAT_LABELS.get(cat, cat)} <b>— прайс</b>\n"]
    kb = InlineKeyboardBuilder()
    for key, data in items:
        lines.append(
            f"{data['name']} — <b>{data['price']:,}</b> 💎 · "
            f"{data['hs']} H/s · {data['watt']} Вт"
        )
        kb.button(text=f"Купить: {data['name']}", callback_data=f"mn:buy:{key}")
    kb.button(text="⬅️ К категориям", callback_data="mn:shop")
    kb.adjust(1)

    try:
        await call.message.edit_text("\n".join(lines), reply_markup=kb.as_markup(), parse_mode="HTML")
    except Exception:
        pass


@router.callback_query(F.data.startswith("mn:buy:"))
async def mn_buy(call: types.CallbackQuery):
    key = call.data.split(":")[2]
    data = CATALOG.get(key)
    if not data:
        return await call.answer("❌ Нет такой модели.", show_alert=True)

    user_id = call.from_user.id
    _, _, _, slots = _get_farm(user_id)
    cursor.execute("SELECT COUNT(*) FROM mining_items WHERE user_id = ?", (user_id,))
    used = cursor.fetchone()[0]
    if used >= slots:
        return await call.answer("❌ Нет свободных слотов, расширь ферму.", show_alert=True)

    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            "UPDATE users SET balance = balance - ? WHERE id = ? AND balance >= ?",
            (data["price"], user_id, data["price"]),
        )
        if cursor.rowcount == 0:
            cursor.execute("ROLLBACK")
            return await call.answer(f"❌ Нужно {data['price']:,} 💎.", show_alert=True)
        cursor.execute(
            "INSERT INTO mining_items (user_id, name, hs, watt, wear, lvl) "
            "VALUES (?, ?, ?, ?, 100, 1)",
            (user_id, data["name"], data["hs"], data["watt"]),
        )
        conn.commit()
    except Exception:
        cursor.execute("ROLLBACK")
        logger.exception("mining:buy")
        return await call.answer("❌ Ошибка покупки.", show_alert=True)

    _recalc_farm(user_id)
    await call.answer(f"✅ Куплено: {data['name']}", show_alert=True)
    try:
        await call.message.edit_text(_menu_text(user_id), reply_markup=_menu_kb(), parse_mode="HTML")
    except Exception:
        pass


# ─────────────── список моих устройств ───────────────

def _device_card(item: tuple) -> str:
    item_id, name, hs, watt, wear = item
    return (
        f"<b>{name}</b>\n"
        f"⚡ {hs} H/s · 🔌 {watt} Вт · 🛠 Износ: {int(wear)}%\n"
        f"ID устройства: <code>{item_id}</code>"
    )


@router.callback_query(F.data == "mn:list")
async def mn_list(call: types.CallbackQuery):
    await call.answer()
    cursor.execute(
        "SELECT id, name, hs, watt, wear FROM mining_items WHERE user_id = ? ORDER BY id",
        (call.from_user.id,),
    )
    rows = cursor.fetchall()
    if not rows:
        kb = InlineKeyboardBuilder()
        kb.button(text="⬅️ Назад", callback_data="mn:main")
        try:
            return await call.message.edit_text(
                "🧰 У тебя пока нет устройств.",
                reply_markup=kb.as_markup(),
                parse_mode="HTML",
            )
        except Exception:
            return

    kb = InlineKeyboardBuilder()
    for row in rows:
        kb.button(text=f"🔧 {row[1]} ({int(row[4])}%)", callback_data=f"mn:item:{row[0]}")
    kb.button(text="⬅️ Назад", callback_data="mn:main")
    kb.adjust(1)

    try:
        await call.message.edit_text(
            "🧰 <b>Мои устройства</b>\n"
            f"Всего: {len(rows)} шт.",
            reply_markup=kb.as_markup(),
            parse_mode="HTML",
        )
    except Exception:
        pass


def _find_item(user_id: int, item_id: int) -> Optional[tuple]:
    cursor.execute(
        "SELECT id, name, hs, watt, wear FROM mining_items WHERE id = ? AND user_id = ?",
        (item_id, user_id),
    )
    return cursor.fetchone()


def _lookup_catalog_by_name(name: str) -> Optional[Dict]:
    for data in CATALOG.values():
        if data["name"] == name:
            return data
    return None


@router.callback_query(F.data.startswith("mn:item:"))
async def mn_item(call: types.CallbackQuery):
    await call.answer()
    item_id = int(call.data.split(":")[2])
    item = _find_item(call.from_user.id, item_id)
    if not item:
        return await call.answer("❌ Нет такого устройства.", show_alert=True)

    kb = InlineKeyboardBuilder()
    kb.button(text="🔧 Ремонт +100%", callback_data=f"mn:fix:{item_id}")
    kb.button(text="💸 Продать (50%)", callback_data=f"mn:sell:{item_id}")
    kb.button(text="⬅️ К списку", callback_data="mn:list")
    kb.adjust(2, 1)
    try:
        await call.message.edit_text(
            _device_card(item),
            reply_markup=kb.as_markup(),
            parse_mode="HTML",
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("mn:fix:"))
async def mn_fix(call: types.CallbackQuery):
    item_id = int(call.data.split(":")[2])
    user_id = call.from_user.id
    item = _find_item(user_id, item_id)
    if not item:
        return await call.answer("❌ Нет такого устройства.", show_alert=True)

    data = _lookup_catalog_by_name(item[1])
    if not data:
        return await call.answer("❌ Неизвестная модель.", show_alert=True)
    if data.get("no_wear"):
        return await call.answer("☁️ Облачные мощности не изнашиваются.", show_alert=True)

    need = int(data["price"] * 0.10)
    if need <= 0:
        return await call.answer("Ремонт не нужен.", show_alert=True)
    if int(item[4]) >= 100:
        return await call.answer("Устройство уже 100%.", show_alert=True)

    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            "UPDATE users SET balance = balance - ? WHERE id = ? AND balance >= ?",
            (need, user_id, need),
        )
        if cursor.rowcount == 0:
            cursor.execute("ROLLBACK")
            return await call.answer(f"❌ Нужно {need:,} 💎.", show_alert=True)
        cursor.execute("UPDATE mining_items SET wear = 100 WHERE id = ?", (item_id,))
        conn.commit()
    except Exception:
        cursor.execute("ROLLBACK")
        logger.exception("mining:fix")
        return await call.answer("❌ Ошибка ремонта.", show_alert=True)

    _recalc_farm(user_id)
    await call.answer(f"✅ {item[1]} отремонтирован за {need:,} 💎", show_alert=True)
    item = _find_item(user_id, item_id)
    try:
        kb = InlineKeyboardBuilder()
        kb.button(text="🔧 Ремонт +100%", callback_data=f"mn:fix:{item_id}")
        kb.button(text="💸 Продать (50%)", callback_data=f"mn:sell:{item_id}")
        kb.button(text="⬅️ К списку", callback_data="mn:list")
        kb.adjust(2, 1)
        await call.message.edit_text(
            _device_card(item),
            reply_markup=kb.as_markup(),
            parse_mode="HTML",
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("mn:sell:"))
async def mn_sell(call: types.CallbackQuery):
    item_id = int(call.data.split(":")[2])
    user_id = call.from_user.id
    item = _find_item(user_id, item_id)
    if not item:
        return await call.answer("❌ Нет такого устройства.", show_alert=True)

    data = _lookup_catalog_by_name(item[1])
    base = data["price"] if data else 0
    refund = int(base * SELL_REFUND)

    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute("DELETE FROM mining_items WHERE id = ?", (item_id,))
        if refund > 0:
            cursor.execute(
                "UPDATE users SET balance = balance + ? WHERE id = ?",
                (refund, user_id),
            )
        conn.commit()
    except Exception:
        cursor.execute("ROLLBACK")
        logger.exception("mining:sell")
        return await call.answer("❌ Ошибка продажи.", show_alert=True)

    _recalc_farm(user_id)
    await call.answer(f"💸 Продано. Возврат {refund:,} 💎.", show_alert=True)
    try:
        await call.message.edit_text(_menu_text(user_id), reply_markup=_menu_kb(), parse_mode="HTML")
    except Exception:
        pass


# ─────────────── расширение слотов ───────────────

@router.callback_query(F.data == "mn:slot")
async def mn_slot(call: types.CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    _, _, _, slots = _get_farm(user_id)
    if slots >= MAX_SLOTS:
        return await call.answer("Уже максимум слотов.", show_alert=True)
    price = _slot_price(slots)

    kb = InlineKeyboardBuilder()
    kb.button(text=f"💳 Купить за {price:,} 💎", callback_data=f"mn:slot_buy:{slots}")
    kb.button(text="⬅️ Назад", callback_data="mn:main")
    kb.adjust(1)
    try:
        await call.message.edit_text(
            f"📦 <b>Расширение фермы</b>\n\n"
            f"Сейчас у тебя <b>{slots}</b> слотов (максимум {MAX_SLOTS}).\n"
            f"Следующий слот стоит <b>{price:,}</b> 💎.",
            reply_markup=kb.as_markup(),
            parse_mode="HTML",
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("mn:slot_buy:"))
async def mn_slot_buy(call: types.CallbackQuery):
    prev_slots = int(call.data.split(":")[2])
    user_id = call.from_user.id
    _, _, _, slots = _get_farm(user_id)
    if slots != prev_slots:
        return await call.answer("Состояние изменилось, попробуй ещё раз.", show_alert=True)
    if slots >= MAX_SLOTS:
        return await call.answer("Уже максимум слотов.", show_alert=True)

    price = _slot_price(slots)
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
            "UPDATE mining_farms SET slots = slots + 1 WHERE user_id = ?",
            (user_id,),
        )
        conn.commit()
    except Exception:
        cursor.execute("ROLLBACK")
        logger.exception("mining:slot_buy")
        return await call.answer("❌ Ошибка покупки.", show_alert=True)

    await call.answer(f"✅ Куплен слот за {price:,} 💎", show_alert=True)
    try:
        await call.message.edit_text(_menu_text(user_id), reply_markup=_menu_kb(), parse_mode="HTML")
    except Exception:
        pass
