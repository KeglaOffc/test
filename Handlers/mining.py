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
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
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
    "cpu_i7":      {"name": "🖥 Core i7 домашний",     "price": 5_000,     "hs": 12,     "watt": 6,    "cat": "cpu"},
    "cpu_xeon":    {"name": "🖥 Xeon Gold",            "price": 7_000,     "hs": 18,     "watt": 8,    "cat": "cpu"},
    "cpu_ripper":  {"name": "🖥 AMD Threadripper",     "price": 15_000,    "hs": 45,     "watt": 15,   "cat": "cpu"},
    "cpu_epyc":    {"name": "🖥 AMD EPYC 9004",        "price": 30_000,    "hs": 100,    "watt": 28,   "cat": "cpu"},

    # GPU
    "gpu_750":     {"name": "🎮 GTX 750 Ti",           "price": 8_000,     "hs": 20,     "watt": 6,    "cat": "gpu"},
    "gpu_1050":    {"name": "🎮 GTX 1050 Ti",          "price": 15_000,    "hs": 40,     "watt": 10,   "cat": "gpu"},
    "gpu_1660":    {"name": "🎮 GTX 1660 Super",       "price": 22_000,    "hs": 65,     "watt": 16,   "cat": "gpu"},
    "gpu_2060":    {"name": "🎮 RTX 2060 Super",       "price": 35_000,    "hs": 110,    "watt": 25,   "cat": "gpu"},
    "gpu_3060":    {"name": "🎮 RTX 3060 Ti",          "price": 55_000,    "hs": 190,    "watt": 34,   "cat": "gpu"},
    "gpu_3080":    {"name": "🎮 RTX 3080 Ti",          "price": 90_000,    "hs": 320,    "watt": 50,   "cat": "gpu"},
    "gpu_4070":    {"name": "🎮 RTX 4070 Ti",          "price": 140_000,   "hs": 500,    "watt": 70,   "cat": "gpu"},
    "gpu_4090":    {"name": "🎮 RTX 4090",              "price": 250_000,   "hs": 850,    "watt": 120,  "cat": "gpu"},

    # ASIC
    "asic_e9":     {"name": "⚙️ iBeLink E9",           "price": 70_000,    "hs": 280,    "watt": 80,   "cat": "asic"},
    "asic_s9":     {"name": "⚙️ Antminer S9",          "price": 150_000,   "hs": 650,    "watt": 130,  "cat": "asic"},
    "asic_l7":     {"name": "⚙️ Antminer L7",          "price": 350_000,   "hs": 1_800,  "watt": 300,  "cat": "asic"},
    "asic_s19":    {"name": "⚙️ Antminer S19 Pro",     "price": 600_000,   "hs": 3_200,  "watt": 450,  "cat": "asic"},
    "asic_ks3":    {"name": "⚙️ IceRiver KS3",         "price": 4_000_000, "hs": 25_000, "watt": 2_000,"cat": "asic"},
    "asic_ks5":    {"name": "⚙️ IceRiver KS5L",        "price": 12_000_000,"hs": 70_000, "watt": 3_200,"cat": "asic"},

    # FPGA (новое)
    "fpga_kintex": {"name": "🧩 Kintex FPGA",          "price": 50_000,    "hs": 210,    "watt": 55,   "cat": "fpga"},
    "fpga_virtex": {"name": "🧩 Virtex UltraScale",    "price": 220_000,   "hs": 900,    "watt": 150,  "cat": "fpga"},

    # Cloud (no wear, no wattage)
    "cloud_start": {"name": "☁️ Cloud Start",          "price": 100_000,   "hs": 350,    "watt": 0,    "cat": "cloud", "no_wear": True},
    "cloud_basic": {"name": "☁️ Cloud Basic",          "price": 500_000,   "hs": 1_800,  "watt": 0,    "cat": "cloud", "no_wear": True},
    "cloud_pro":   {"name": "☁️ Cloud Pro",            "price": 2_500_000, "hs": 10_000, "watt": 0,    "cat": "cloud", "no_wear": True},
    "cloud_ultra": {"name": "☁️ Cloud Ultra",          "price": 8_000_000, "hs": 35_000, "watt": 0,    "cat": "cloud", "no_wear": True},
}

CAT_LABELS = {
    "cpu": "🖥 CPU",
    "gpu": "🎮 GPU",
    "asic": "⚙️ ASIC",
    "fpga": "🧩 FPGA",
    "cloud": "☁️ Облако",
}

# Простые рецепты крафта: 2 одинаковых устройства + монетки → улучшенное
CRAFT_RECIPES: Dict[str, Dict] = {
    "cpu_i3":    {"into": "cpu_i7",    "fee": 1_500},
    "cpu_i7":    {"into": "cpu_xeon",  "fee": 3_000},
    "cpu_xeon":  {"into": "cpu_ripper","fee": 8_000},
    "gpu_750":   {"into": "gpu_1050",  "fee": 3_000},
    "gpu_1050":  {"into": "gpu_1660",  "fee": 7_000},
    "gpu_1660":  {"into": "gpu_2060",  "fee": 12_000},
    "gpu_2060":  {"into": "gpu_3060",  "fee": 20_000},
    "gpu_3060":  {"into": "gpu_3080",  "fee": 40_000},
    "gpu_3080":  {"into": "gpu_4070",  "fee": 70_000},
    "gpu_4070":  {"into": "gpu_4090",  "fee": 120_000},
    "asic_e9":   {"into": "asic_s9",   "fee": 60_000},
    "asic_s9":   {"into": "asic_l7",   "fee": 120_000},
    "asic_l7":   {"into": "asic_s19",  "fee": 250_000},
    "fpga_kintex": {"into": "fpga_virtex", "fee": 80_000},
}

MARKET_COMMISSION = 0.05
MARKET_PAGE_SIZE = 8


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
    kb.button(text="💰 Собрать",         callback_data="mn:collect")
    kb.button(text="🛒 Купить железо",   callback_data="mn:shop")
    kb.button(text="🧰 Мои устройства",  callback_data="mn:list")
    kb.button(text="📦 Купить слот",     callback_data="mn:slot")
    kb.button(text="🏪 Рынок",           callback_data="mn:market")
    kb.button(text="🔨 Верстак",         callback_data="mn:craft")
    kb.button(text="ℹ️ Как это работает", callback_data="mn:help")
    kb.button(text="🏠 В меню",          callback_data="go:start")
    kb.adjust(2, 2, 2, 2)
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
    kb.button(text="🔧 Ремонт +100%",   callback_data=f"mn:fix:{item_id}")
    kb.button(text="💸 Продать (50%)",   callback_data=f"mn:sell:{item_id}")
    kb.button(text="🏪 На рынок",        callback_data=f"mn:mk_list:{item_id}")
    kb.button(text="⬅️ К списку",        callback_data="mn:list")
    kb.adjust(2, 1, 1)
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


# ─────────────── рынок игроков ───────────────


class MarketState(StatesGroup):
    awaiting_price = State()


def _catalog_key_by_name(name: str) -> Optional[str]:
    for k, v in CATALOG.items():
        if v["name"] == name:
            return k
    return None


@router.callback_query(F.data == "mn:market")
async def mn_market(call: types.CallbackQuery):
    await call.answer()
    await _render_market(call, page=0)


async def _render_market(call: types.CallbackQuery, page: int):
    cursor.execute(
        "SELECT COUNT(*) FROM mining_market WHERE status = 'open'"
    )
    total = cursor.fetchone()[0] or 0
    offset = page * MARKET_PAGE_SIZE
    cursor.execute(
        "SELECT id, seller_id, name, hs, watt, wear, price FROM mining_market "
        "WHERE status = 'open' ORDER BY price ASC LIMIT ? OFFSET ?",
        (MARKET_PAGE_SIZE, offset),
    )
    rows = cursor.fetchall()

    kb = InlineKeyboardBuilder()
    if not rows:
        text = "🏪 <b>Рынок устройств</b>\n\nСейчас нет активных лотов."
    else:
        lines = ["🏪 <b>Рынок устройств</b>\n"]
        for mid, seller, name, hs, watt, wear, price in rows:
            lines.append(
                f"• <b>{name}</b> — {price:,} 💎\n"
                f"   ⚡ {hs} H/s · 🔌 {watt} Вт · 🛠 {int(wear)}% · продавец <code>{seller}</code>"
            )
            kb.button(text=f"💳 Купить #{mid} ({price:,})", callback_data=f"mn:mk_buy:{mid}")
        text = "\n".join(lines)

    nav = []
    if page > 0:
        kb.button(text="⬅️ Назад", callback_data=f"mn:mk_page:{page-1}")
        nav.append("back")
    if (page + 1) * MARKET_PAGE_SIZE < total:
        kb.button(text="Вперёд ➡️", callback_data=f"mn:mk_page:{page+1}")
        nav.append("fwd")
    kb.button(text="📋 Мои лоты", callback_data="mn:mk_mine")
    kb.button(text="🏠 В меню", callback_data="mn:main")

    btn_rows = [1] * len(rows) if rows else []
    if nav:
        btn_rows.append(len(nav))
    btn_rows.append(2)
    kb.adjust(*btn_rows)

    try:
        await call.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    except Exception:
        await call.message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")


@router.callback_query(F.data.startswith("mn:mk_page:"))
async def mn_market_page(call: types.CallbackQuery):
    await call.answer()
    page = int(call.data.split(":")[2])
    await _render_market(call, page)


@router.callback_query(F.data.startswith("mn:mk_list:"))
async def mn_market_list_prompt(call: types.CallbackQuery, state: FSMContext):
    """Выставить устройство на рынок — запрашиваем цену."""
    await call.answer()
    item_id = int(call.data.split(":")[2])
    item = _find_item(call.from_user.id, item_id)
    if not item:
        return await call.answer("❌ Нет такого устройства.", show_alert=True)
    await state.set_state(MarketState.awaiting_price)
    await state.update_data(item_id=item_id)
    try:
        await call.message.edit_text(
            f"🏪 Выставление лота: <b>{item[1]}</b>\n\n"
            "Напиши цену в 💎 одним сообщением. Комиссия рынка — 5%.",
            parse_mode="HTML",
        )
    except Exception:
        pass


@router.message(MarketState.awaiting_price)
async def mn_market_list_set_price(message: types.Message, state: FSMContext):
    txt = (message.text or "").strip().replace(" ", "")
    if not txt.isdigit():
        return await message.reply("Введи число, например <code>50000</code>.", parse_mode="HTML")
    price = int(txt)
    if price < 100:
        return await message.reply("Минимальная цена — 100 💎.")
    data = await state.get_data()
    item_id = data.get("item_id")
    user_id = message.from_user.id
    item = _find_item(user_id, item_id)
    if not item:
        await state.clear()
        return await message.reply("❌ Устройство не найдено.")

    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            "DELETE FROM mining_items WHERE id = ? AND user_id = ?",
            (item_id, user_id),
        )
        if cursor.rowcount == 0:
            cursor.execute("ROLLBACK")
            await state.clear()
            return await message.reply("❌ Устройство уже недоступно.")
        cursor.execute(
            "INSERT INTO mining_market (seller_id, item_id, name, hs, watt, wear, price, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?)",
            (user_id, item_id, item[1], item[2], item[3], item[4], price, _now()),
        )
        conn.commit()
    except Exception:
        cursor.execute("ROLLBACK")
        logger.exception("mining:market_list")
        await state.clear()
        return await message.reply("❌ Не удалось выставить лот.")

    _recalc_farm(user_id)
    await state.clear()
    await message.answer(
        f"🏪 Лот <b>{item[1]}</b> выставлен за {price:,} 💎.",
        parse_mode="HTML",
    )


@router.callback_query(F.data == "mn:mk_mine")
async def mn_market_mine(call: types.CallbackQuery):
    await call.answer()
    cursor.execute(
        "SELECT id, name, price FROM mining_market WHERE seller_id = ? AND status = 'open' ORDER BY id DESC",
        (call.from_user.id,),
    )
    rows = cursor.fetchall()
    kb = InlineKeyboardBuilder()
    if rows:
        lines = ["📋 <b>Мои активные лоты</b>\n"]
        for mid, name, price in rows:
            lines.append(f"• <b>{name}</b> — {price:,} 💎 (id {mid})")
            kb.button(text=f"❌ Снять #{mid}", callback_data=f"mn:mk_cancel:{mid}")
        text = "\n".join(lines)
    else:
        text = "📋 У тебя нет активных лотов."
    kb.button(text="⬅️ Назад", callback_data="mn:market")
    kb.adjust(1)
    try:
        await call.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    except Exception:
        pass


@router.callback_query(F.data.startswith("mn:mk_cancel:"))
async def mn_market_cancel(call: types.CallbackQuery):
    mid = int(call.data.split(":")[2])
    user_id = call.from_user.id
    cursor.execute(
        "SELECT name, hs, watt, wear FROM mining_market "
        "WHERE id = ? AND seller_id = ? AND status = 'open'",
        (mid, user_id),
    )
    row = cursor.fetchone()
    if not row:
        return await call.answer("❌ Лот не найден.", show_alert=True)
    _, _, _, slots = _get_farm(user_id)
    cursor.execute("SELECT COUNT(*) FROM mining_items WHERE user_id = ?", (user_id,))
    used = cursor.fetchone()[0]
    if used >= slots:
        return await call.answer("❌ Нет свободных слотов, чтобы вернуть устройство.", show_alert=True)
    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            "UPDATE mining_market SET status = 'cancelled' WHERE id = ? AND seller_id = ?",
            (mid, user_id),
        )
        cursor.execute(
            "INSERT INTO mining_items (user_id, name, hs, watt, wear, lvl) VALUES (?, ?, ?, ?, ?, 1)",
            (user_id, row[0], row[1], row[2], row[3]),
        )
        conn.commit()
    except Exception:
        cursor.execute("ROLLBACK")
        logger.exception("mining:market_cancel")
        return await call.answer("❌ Не удалось снять лот.", show_alert=True)
    _recalc_farm(user_id)
    await call.answer("Лот снят, устройство возвращено на ферму.", show_alert=True)
    await _render_market(call, page=0)


@router.callback_query(F.data.startswith("mn:mk_buy:"))
async def mn_market_buy(call: types.CallbackQuery):
    mid = int(call.data.split(":")[2])
    buyer = call.from_user.id
    cursor.execute(
        "SELECT seller_id, name, hs, watt, wear, price FROM mining_market "
        "WHERE id = ? AND status = 'open'",
        (mid,),
    )
    row = cursor.fetchone()
    if not row:
        return await call.answer("❌ Лот уже недоступен.", show_alert=True)
    seller, name, hs, watt, wear, price = row
    if seller == buyer:
        return await call.answer("❌ Нельзя покупать свой лот.", show_alert=True)

    _, _, _, slots = _get_farm(buyer)
    cursor.execute("SELECT COUNT(*) FROM mining_items WHERE user_id = ?", (buyer,))
    used = cursor.fetchone()[0]
    if used >= slots:
        return await call.answer("❌ Нет свободных слотов на ферме.", show_alert=True)

    payout = int(price * (1 - MARKET_COMMISSION))
    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            "UPDATE users SET balance = balance - ? WHERE id = ? AND balance >= ?",
            (price, buyer, price),
        )
        if cursor.rowcount == 0:
            cursor.execute("ROLLBACK")
            return await call.answer(f"❌ Нужно {price:,} 💎.", show_alert=True)
        cursor.execute(
            "UPDATE mining_market SET status = 'sold', buyer_id = ? WHERE id = ? AND status = 'open'",
            (buyer, mid),
        )
        if cursor.rowcount == 0:
            cursor.execute("ROLLBACK")
            return await call.answer("❌ Кто-то успел раньше.", show_alert=True)
        cursor.execute(
            "UPDATE users SET balance = balance + ? WHERE id = ?",
            (payout, seller),
        )
        cursor.execute(
            "INSERT INTO mining_items (user_id, name, hs, watt, wear, lvl) VALUES (?, ?, ?, ?, ?, 1)",
            (buyer, name, hs, watt, wear),
        )
        conn.commit()
    except Exception:
        cursor.execute("ROLLBACK")
        logger.exception("mining:market_buy")
        return await call.answer("❌ Ошибка покупки.", show_alert=True)

    _recalc_farm(buyer)
    try:
        await call.message.bot.send_message(
            seller,
            f"💰 Твой лот <b>{name}</b> куплен за {price:,} 💎.\n"
            f"На баланс зачислено {payout:,} 💎 (комиссия 5%).",
            parse_mode="HTML",
        )
    except Exception:
        pass
    await call.answer(f"✅ Куплено за {price:,} 💎", show_alert=True)
    await _render_market(call, page=0)


# ─────────────── верстак (крафт) ───────────────

def _craftable_pairs(user_id: int) -> Dict[str, int]:
    """Возвращает {catalog_key: количество устройств с полным износом} для крафта."""
    cursor.execute(
        "SELECT name, COUNT(*) FROM mining_items WHERE user_id = ? GROUP BY name",
        (user_id,),
    )
    result: Dict[str, int] = {}
    for name, cnt in cursor.fetchall():
        key = _catalog_key_by_name(name)
        if key and key in CRAFT_RECIPES:
            result[key] = cnt
    return result


@router.callback_query(F.data == "mn:craft")
async def mn_craft(call: types.CallbackQuery):
    await call.answer()
    owned = _craftable_pairs(call.from_user.id)
    kb = InlineKeyboardBuilder()
    lines = [
        "🔨 <b>Верстак</b>\n\n"
        "Соединяешь 2 одинаковых устройства + монетки — получаешь улучшенное.",
        "",
    ]
    any_ready = False
    for key, recipe in CRAFT_RECIPES.items():
        src = CATALOG[key]
        dst = CATALOG[recipe["into"]]
        cnt = owned.get(key, 0)
        ready = cnt >= 2
        any_ready = any_ready or ready
        status = "✅" if ready else "⛔"
        lines.append(
            f"{status} <b>2× {src['name']}</b> + {recipe['fee']:,} 💎 → {dst['name']} "
            f"(у тебя {cnt})"
        )
        if ready:
            kb.button(
                text=f"🔨 {src['name']} → {dst['name']}",
                callback_data=f"mn:craft_do:{key}",
            )
    if not any_ready:
        lines.append("\nПока нечего крафтить. Купи 2 одинаковых устройства.")
    kb.button(text="🏠 В меню", callback_data="mn:main")
    kb.adjust(1)
    try:
        await call.message.edit_text(
            "\n".join(lines), reply_markup=kb.as_markup(), parse_mode="HTML"
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("mn:craft_do:"))
async def mn_craft_do(call: types.CallbackQuery):
    key = call.data.split(":")[2]
    recipe = CRAFT_RECIPES.get(key)
    if not recipe:
        return await call.answer("❌ Нет такого рецепта.", show_alert=True)
    src = CATALOG[key]
    dst = CATALOG[recipe["into"]]
    user_id = call.from_user.id

    cursor.execute(
        "SELECT id FROM mining_items WHERE user_id = ? AND name = ? ORDER BY wear DESC LIMIT 2",
        (user_id, src["name"]),
    )
    rows = cursor.fetchall()
    if len(rows) < 2:
        return await call.answer("❌ Нужно 2 одинаковых устройства.", show_alert=True)

    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            "UPDATE users SET balance = balance - ? WHERE id = ? AND balance >= ?",
            (recipe["fee"], user_id, recipe["fee"]),
        )
        if cursor.rowcount == 0:
            cursor.execute("ROLLBACK")
            return await call.answer(f"❌ Нужно {recipe['fee']:,} 💎.", show_alert=True)
        cursor.execute(
            f"DELETE FROM mining_items WHERE id IN ({rows[0][0]}, {rows[1][0]})"
        )
        cursor.execute(
            "INSERT INTO mining_items (user_id, name, hs, watt, wear, lvl) VALUES (?, ?, ?, ?, 100, 1)",
            (user_id, dst["name"], dst["hs"], dst["watt"]),
        )
        conn.commit()
    except Exception:
        cursor.execute("ROLLBACK")
        logger.exception("mining:craft")
        return await call.answer("❌ Ошибка крафта.", show_alert=True)

    _recalc_farm(user_id)
    await call.answer(f"🔨 Готово: {dst['name']}", show_alert=True)
    # re-render craft menu
    await mn_craft(call)
