"""Каталог ивентов казино и их активация.

Ивенты — это временные модификаторы экономики, которые включает админ из панели.
Каталог содержит 110 шаблонов: множители выигрыша, повышенный бонус, двойной XP,
пониженный кулдаун и т.п. Активные ивенты хранятся в таблице ``events_state``
и подхватываются играми через :func:`active_multiplier` и родственные хелперы.

Таблица создаётся отложенно при первом обращении, чтобы не ломать старые базы.
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import conn, cursor, is_admin_or_higher

router = Router()


def _ensure_tables() -> None:
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS events_state (
            event_key TEXT PRIMARY KEY,
            active INTEGER DEFAULT 0,
            ends_at INTEGER DEFAULT 0,
            activated_by INTEGER DEFAULT 0,
            activated_at INTEGER DEFAULT 0
        )"""
    )
    conn.commit()


_ensure_tables()


def _event(
    key: str,
    title: str,
    description: str,
    kind: str,
    value: float = 0.0,
    default_hours: int = 2,
    targets: Tuple[str, ...] = ("all",),
) -> Dict:
    return {
        "key": key,
        "title": title,
        "description": description,
        "kind": kind,
        "value": value,
        "default_hours": default_hours,
        "targets": targets,
    }


def _build_catalog() -> Dict[str, Dict]:
    cat: List[Dict] = []

    def add(ev: Dict) -> None:
        cat.append(ev)

    # 1..20 — множители выигрыша для конкретных игр и общий
    add(_event("win_x2_all",      "🎉 Удвоитель",           "Все выигрыши умножаются на 2.",              "win_mult", 2.0, 2, ("all",)))
    add(_event("win_x3_all",      "🎆 Тройной куш",          "Все выигрыши умножаются на 3.",              "win_mult", 3.0, 1, ("all",)))
    add(_event("win_x15_all",     "✨ Полуторный",           "Все выигрыши x1.5.",                         "win_mult", 1.5, 3, ("all",)))
    add(_event("win_x2_slots",    "🎰 Слот-фестиваль",       "Слоты выдают в 2 раза больше.",              "win_mult", 2.0, 2, ("slots",)))
    add(_event("win_x2_roulette", "🎡 Рулетка-бонус",        "Рулетка удваивает все выплаты.",             "win_mult", 2.0, 2, ("roulette",)))
    add(_event("win_x2_mines",    "💣 Опасный день",         "Выигрыши в минах удваиваются.",              "win_mult", 2.0, 2, ("mines",)))
    add(_event("win_x2_chests",   "🎁 Щедрые сундуки",       "Сундуки вдвое щедрее.",                      "win_mult", 2.0, 2, ("chests",)))
    add(_event("win_x2_flip",     "🪙 Двойная монетка",      "Флип x2 к выплатам.",                        "win_mult", 2.0, 2, ("flip",)))
    add(_event("win_x2_crash",    "🚀 Гравитация выключена","Краш множится на 2.",                          "win_mult", 2.0, 2, ("crash",)))
    add(_event("win_x15_dice",    "🎲 Кости с плюсом",       "Кости +50% к выигрышу.",                     "win_mult", 1.5, 2, ("dice",)))
    add(_event("win_x15_darts",   "🎯 Меткий час",           "Дартс +50% к выигрышу.",                     "win_mult", 1.5, 2, ("darts",)))
    add(_event("win_x15_basket",  "🏀 В корзину x1.5",       "Баскетбол +50% к выигрышу.",                 "win_mult", 1.5, 2, ("basket",)))
    add(_event("win_x15_football","⚽ Серия пенальти",        "Футбол +50% к выигрышу.",                    "win_mult", 1.5, 2, ("football",)))
    add(_event("win_x25_jackpot", "💎 День джекпотов",       "Джекпоты и топ-призы x2.5.",                 "win_mult", 2.5, 1, ("all",)))
    add(_event("win_online_x2",   "🌐 Онлайн-битва",         "Выигрыши в дуэлях x2.",                      "win_mult", 2.0, 2, ("online",)))
    add(_event("win_lottery_x2",  "🎟 Лото-взрыв",           "Призы лотереи x2.",                          "win_mult", 2.0, 24, ("lottery",)))
    add(_event("win_mining_x2",   "⛏ Золотая жила",          "Доход с фермы x2.",                          "win_mult", 2.0, 12, ("mining",)))
    add(_event("win_wheel_x2",    "🎡 Колесо фортуны+",      "Приз с колеса x2.",                          "win_mult", 2.0, 6, ("wheel",)))
    add(_event("win_mega_x2",     "🐳 Мега-тираж+",          "Мега лотерея x2.",                           "win_mult", 2.0, 48, ("mega",)))
    add(_event("win_scratch_x2",  "🎟 Двойной скретч",       "Скретчи удваиваются.",                       "win_mult", 2.0, 4, ("scratch",)))

    # 21..40 — скидки и дешевые ставки
    add(_event("bet_discount_10", "💸 Скидка 10% на ставки",  "Ставки во всех играх дешевле на 10%.",       "bet_discount", 0.10, 3, ("all",)))
    add(_event("bet_discount_20", "💸 Скидка 20% на ставки",  "Ставки на 20% дешевле.",                     "bet_discount", 0.20, 2, ("all",)))
    add(_event("bet_discount_30", "💸 Мега-скидка 30%",       "Ставки на 30% дешевле.",                     "bet_discount", 0.30, 1, ("all",)))
    add(_event("shop_sale_10",    "🛒 Распродажа 10%",        "Все покупки в магазине -10%.",               "shop_sale", 0.10, 6, ("shop",)))
    add(_event("shop_sale_25",    "🛒 Распродажа 25%",        "Все покупки в магазине -25%.",               "shop_sale", 0.25, 4, ("shop",)))
    add(_event("shop_sale_50",    "🛒 Чёрная пятница",         "Все покупки в магазине вдвое дешевле.",      "shop_sale", 0.50, 2, ("shop",)))
    add(_event("market_fee_off",  "🏪 Ноль комиссии",         "Рынок майнинга без комиссии.",               "market_fee", 0.0, 6, ("market",)))
    add(_event("market_fee_half", "🏪 Полкомиссии",           "Комиссия рынка сокращена до 2.5%.",         "market_fee", 0.025, 6, ("market",)))
    add(_event("lottery_sale",    "🎟 Билеты за полцены",     "Все лотерейные билеты -50%.",                "lottery_sale", 0.5, 4, ("lottery",)))
    add(_event("vip_cashback_x2", "💼 Двойной VIP-кэшбэк",    "VIP-кэшбэк удваивается.",                    "vip_cashback_mult", 2.0, 6, ("vip",)))
    add(_event("insure_free",     "🃏 Бесплатная страховка",  "Страховка применяется без списания зарядов.","insure_free", 1.0, 3, ("all",)))
    add(_event("shield_free",     "🛡 Щит щедрый",            "В минах щит не тратится при подрыве.",       "shield_free", 1.0, 3, ("mines",)))
    add(_event("reroll_free",     "🔄 Бесплатные рероллы",    "Рероллы не тратятся.",                       "reroll_free", 1.0, 3, ("dice",)))
    add(_event("scan_free",       "🔍 Бесплатные сканеры",    "Сканеры мин не расходуются.",                "scan_free", 1.0, 3, ("mines",)))
    add(_event("wheel_token_x2",  "🎡 Двойной жетон",         "Каждый спин колеса считается как 2.",        "wheel_count_mult", 2.0, 6, ("wheel",)))
    add(_event("energy_free",     "⚡️ Батарейка",            "Энергетики не тратятся.",                    "energy_free", 1.0, 4, ("bonus",)))
    add(_event("ticket_refund",   "🎟 Возврат билетов",       "Проигравшие билеты возвращают 10% цены.",    "ticket_refund", 0.10, 24, ("lottery",)))
    add(_event("pvp_fee_off",     "🌐 Арена без комиссии",    "Онлайн-комиссия 0%.",                        "pvp_fee", 0.0, 6, ("online",)))
    add(_event("crash_min_15",    "🚀 Безопасный старт",     "Краш-точка не ниже 1.5x.",                   "crash_min", 1.5, 2, ("crash",)))
    add(_event("crash_min_2",     "🚀 Бронестарт",            "Краш-точка не ниже 2x.",                     "crash_min", 2.0, 1, ("crash",)))

    # 41..60 — бонусы и ежедневка
    add(_event("bonus_x2",        "🎁 Двойной ежедневный",     "Кнопка /bonus даёт x2 к монетам.",           "bonus_mult", 2.0, 24, ("bonus",)))
    add(_event("bonus_x3",        "🎁 Тройной бонус",          "Ежедневный бонус x3.",                       "bonus_mult", 3.0, 12, ("bonus",)))
    add(_event("bonus_no_cd",     "🎁 Без кулдауна",           "Бонус можно брать без ожидания.",            "bonus_no_cd", 1.0, 6, ("bonus",)))
    add(_event("bonus_extra_roll","🎁 Дополнительный ролл",   "Все игроки получают +1 ролл в /bonus.",      "bonus_rolls", 1.0, 24, ("bonus",)))
    add(_event("gift_10k",        "💝 Подарок всем 10k",       "Всем игрокам при входе — 10 000 💎.",        "gift", 10_000, 6, ("gift",)))
    add(_event("gift_50k",        "💝 Подарок всем 50k",       "Всем игрокам — 50 000 💎.",                  "gift", 50_000, 6, ("gift",)))
    add(_event("gift_shield",     "🛡 Подарок: щит",           "Каждому игроку выдаётся щит мин.",           "gift_item", 1.0, 24, ("mine_shield",)))
    add(_event("gift_scan",       "🔍 Подарок: сканер",         "Каждому игроку выдаётся сканер мин.",        "gift_item", 1.0, 24, ("mine_scan",)))
    add(_event("gift_scratch",    "🎟 Подарок: скретч",         "Каждому игроку выдаётся скретч-билет.",      "gift_item", 1.0, 24, ("scratch_pack",)))
    add(_event("gift_energy",     "⚡️ Подарок: энергетик",     "Каждому — энергетик.",                       "gift_item", 1.0, 24, ("energy_drink",)))
    add(_event("gift_gold_ticket","🎟 Подарок: зол.билет",     "Каждому — золотой билет.",                   "gift_item", 1.0, 24, ("gold_ticket",)))
    add(_event("gift_wheel_token","🎡 Подарок: жетон колеса",  "Каждому — жетон колеса.",                    "gift_item", 1.0, 24, ("wheel_token",)))
    add(_event("aura_free",       "✨ Аура всем",              "Временно подсвечивает ауру всем игрокам.",   "aura_all", 1.0, 6, ("cosmetic",)))
    add(_event("rich_day",        "💰 День богача",            "Баланс игроков +5% на момент входа.",        "gift_pct", 0.05, 1, ("gift",)))
    add(_event("poor_day",        "🥲 День бедняка",           "Все начинают с фиксированными 10k на сутки.","gift", 10_000, 24, ("gift",)))
    add(_event("xp_x2",           "📈 Двойной XP",             "Очки боевого пропуска x2.",                  "xp_mult", 2.0, 24, ("bp",)))
    add(_event("xp_x3",           "📈 Тройной XP",             "Очки боевого пропуска x3.",                  "xp_mult", 3.0, 12, ("bp",)))
    add(_event("xp_x5",           "📈 Пятерной XP",            "Очки боевого пропуска x5.",                  "xp_mult", 5.0, 4, ("bp",)))
    add(_event("bp_free_unlock",  "🎫 Премиум за полцены",     "Premium-пропуск на 50% дешевле.",             "bp_sale", 0.5, 12, ("bp",)))
    add(_event("bp_free_gift",    "🎫 Бесплатный бустер",       "Все получают +1000 XP.",                     "xp_gift", 1000, 1, ("bp",)))

    # 61..80 — майнинг, крафт и рынок
    add(_event("mining_watt_off", "⚡️ Бесплатное электричество","Майнинг не тратит электричество.",          "watt_off", 1.0, 6, ("mining",)))
    add(_event("mining_heat_off", "❄️ Ледяной режим",           "Перегрев отключён.",                         "heat_off", 1.0, 6, ("mining",)))
    add(_event("mining_auto",     "🤖 Автосбор всем",           "Автосбор включается всем игрокам.",          "auto_collect", 1.0, 6, ("mining",)))
    add(_event("mining_drop",     "🎁 Дроп с майнинга",         "5% шанс получать предметы со сбора.",        "mining_drop", 0.05, 6, ("mining",)))
    add(_event("mining_rare",     "💎 Редкие находки",          "Шанс редкого дропа повышен.",                "mining_drop", 0.15, 3, ("mining",)))
    add(_event("craft_discount",  "🔨 Скидка на крафт",         "Плата за крафт уменьшена вдвое.",             "craft_discount", 0.5, 6, ("craft",)))
    add(_event("craft_free",      "🔨 Бесплатный крафт",         "Крафт без оплаты монет.",                     "craft_discount", 0.0, 3, ("craft",)))
    add(_event("market_boost",    "🏪 Рынок активен",           "На рынке майнинга удвоена видимость.",        "market_bonus", 2.0, 6, ("market",)))
    add(_event("slot_price_cut",  "📦 Слоты дешевле",            "Слоты фермы -50%.",                           "slot_sale", 0.5, 6, ("mining",)))
    add(_event("mining_x5",       "⛏ Золотая неделя",           "Доход фермы x5 на короткое время.",           "win_mult", 5.0, 1, ("mining",)))
    add(_event("mining_x3",       "⛏ Золотой день",             "Доход фермы x3.",                             "win_mult", 3.0, 6, ("mining",)))
    add(_event("repair_free",     "🔧 Бесплатный ремонт",        "Ремонт устройств фермы бесплатный.",          "repair_free", 1.0, 6, ("mining",)))
    add(_event("overclock_safe",  "⚙️ Безопасный разгон",        "Разгон не ломает устройства.",                "overclock_safe", 1.0, 4, ("mining",)))
    add(_event("rig_gift",        "🖥 Подарок: GPU",             "Каждому игроку выдаётся GTX 1050 Ti.",        "gift_rig", 1.0, 24, ("mining",)))
    add(_event("rig_gift_pro",    "🖥 Подарок: GPU-про",         "Каждому игроку выдаётся GPU 2060.",           "gift_rig", 1.0, 24, ("mining_pro",)))
    add(_event("cloud_discount",  "☁️ Облако дешевле",            "Cloud-устройства -30%.",                      "cloud_sale", 0.30, 6, ("mining",)))
    add(_event("asic_discount",   "⚙️ ASIC распродажа",          "ASIC устройства -30%.",                       "asic_sale", 0.30, 6, ("mining",)))
    add(_event("fpga_discount",   "🧩 FPGA распродажа",           "FPGA устройства -30%.",                       "fpga_sale", 0.30, 6, ("mining",)))
    add(_event("electricity_half","⚡️ Скидка на электричество",  "Траты электричества -50%.",                   "watt_mult", 0.5, 6, ("mining",)))
    add(_event("rig_fast_collect","🤖 Ускоренный автосбор",      "Автосбор работает в 2× чаще.",                "auto_interval", 0.5, 6, ("mining",)))

    # 81..95 — клановые и социальные
    add(_event("clan_bank_x2",    "🛡 Клан-банк x2",             "Взносы в клан-банк удваиваются.",             "clan_deposit_mult", 2.0, 24, ("clans",)))
    add(_event("clan_xp_x2",      "🛡 Клановый XP x2",           "XP кланам начисляется x2.",                   "clan_xp_mult", 2.0, 24, ("clans",)))
    add(_event("clan_free_create","🛡 Создать клан даром",       "Бесплатное создание клана.",                  "clan_create_free", 1.0, 24, ("clans",)))
    add(_event("clan_join_bonus", "🛡 Бонус за вступление",      "При вступлении в клан — 10 000 💎.",          "clan_join_gift", 10_000, 48, ("clans",)))
    add(_event("clan_weekly_x2",  "🛡 Двойной клан-топ",          "Наградa недельного топа кланов x2.",          "clan_top_mult", 2.0, 168, ("clans",)))
    add(_event("ref_bonus",       "🤝 Рефералка x2",             "Бонусы за рефералов удвоены.",                "ref_mult", 2.0, 24, ("ref",)))
    add(_event("welcome_back",    "👋 Возвращайся",              "Игроки, не заходившие 7 дней, получат 25k.",  "welcome_back", 25_000, 24, ("gift",)))
    add(_event("night_hours",     "🌙 Ночной тариф",             "С 00:00 до 06:00 все выигрыши x1.5.",         "win_mult", 1.5, 24, ("all",)))
    add(_event("morning_bonus",   "☀️ Утро с плюсом",            "С 06:00 до 12:00 бонус x2.",                 "bonus_mult", 2.0, 24, ("bonus",)))
    add(_event("happy_hour",      "🥂 Счастливый час",           "Один час x3 ко всем выигрышам.",              "win_mult", 3.0, 1, ("all",)))
    add(_event("weekend_boost",   "🎉 Уикенд-бонус",             "Выходные — выигрыши x2.",                     "win_mult", 2.0, 48, ("all",)))
    add(_event("boss_battle",     "🐉 Босс-рейд",                "Клан получает общий приз за суммарные ставки.","boss", 1.0, 12, ("clans",)))
    add(_event("trade_week",      "🏪 Торговая неделя",          "Комиссия рынка 0% + x2 к сделкам.",           "market_fee", 0.0, 168, ("market",)))
    add(_event("fortune_lottery", "🎟 Особый тираж",             "Часовая лотерея даёт +1 число в выбор.",      "lottery_extra", 1.0, 6, ("lottery",)))
    add(_event("mystery_prize",   "🎁 Загадочный приз",           "Каждый час случайному игроку — 100k.",        "mystery", 100_000, 24, ("gift",)))

    # 96..110 — редкие и эффектные
    add(_event("free_vip_bronze", "🥉 Бесплатный Bronze",         "Все игроки получают Bronze на 24 часа.",      "vip_grant", 1.0, 24, ("vip",)))
    add(_event("free_vip_silver", "🥈 Бесплатный Silver",         "Все игроки получают Silver на 12 часов.",     "vip_grant", 2.0, 12, ("vip",)))
    add(_event("free_vip_gold",   "🥇 Бесплатный Gold",           "Все получают Gold на 3 часа.",                "vip_grant", 3.0, 3, ("vip",)))
    add(_event("no_cooldowns",    "⏱ Без кулдаунов",             "Все КД игры временно отключены.",             "no_cd", 1.0, 3, ("all",)))
    add(_event("no_taxes",        "💸 Налоговые каникулы",        "Любые комиссии отключены.",                   "no_fees", 1.0, 3, ("all",)))
    add(_event("balance_insure",  "🛡 Страховка баланса",         "Нельзя проиграть больше 50% баланса за игру.","balance_cap", 0.5, 6, ("all",)))
    add(_event("double_or_half",  "🎲 Удвоение или половина",     "Каждый выигрыш x2 или уменьшается вдвое (50/50).","lucky_coin", 1.0, 2, ("all",)))
    add(_event("shop_free_loot",  "🎁 Лут-бокс в подарок",        "Каждому — один лут-бокс.",                    "gift_lootbox", 1.0, 24, ("gift",)))
    add(_event("triple_chance",   "🍀 Тройная удача",             "Клевер +15%.",                                "clover_boost", 0.15, 6, ("all",)))
    add(_event("anti_rig",        "🛡 Отключение подкрута",       "Подкрутка игроков временно выключена.",       "rig_off", 1.0, 6, ("all",)))
    add(_event("pvp_mirror",      "🪞 Зеркало",                   "В онлайне оба игрока получают по 25% приза.", "pvp_mirror", 0.25, 6, ("online",)))
    add(_event("lottery_free",    "🎟 Часовая бесплатно",         "Одно место в часовой лотерее бесплатно.",     "lottery_free_slot", 1.0, 12, ("lottery",)))
    add(_event("golden_touch",    "👑 Золотое касание",           "5% шанс удвоить любой выигрыш.",              "golden_touch", 0.05, 24, ("all",)))
    add(_event("lucky_streak",    "🔥 Серия побед",               "Три победы подряд дают +100% бонус.",         "lucky_streak", 1.0, 12, ("all",)))
    add(_event("end_of_season",   "🏁 Конец сезона",              "Удвоение XP и наград боевого пропуска.",      "bp_final", 2.0, 48, ("bp",)))

    return {ev["key"]: ev for ev in cat}


CATALOG: Dict[str, Dict] = _build_catalog()
assert len(CATALOG) == 110, f"ожидалось 110 ивентов, получили {len(CATALOG)}"


# ─────────── публичные хелперы ───────────


def active_events(now: Optional[int] = None) -> List[Dict]:
    """Возвращает сведения об активных ивентах на текущий момент."""
    _ensure_tables()
    ts = int(now if now is not None else time.time())
    cursor.execute(
        "SELECT event_key, ends_at FROM events_state WHERE active = 1 AND (ends_at = 0 OR ends_at > ?)",
        (ts,),
    )
    rows = cursor.fetchall() or []
    out: List[Dict] = []
    for key, ends in rows:
        meta = CATALOG.get(key)
        if not meta:
            continue
        entry = dict(meta)
        entry["ends_at"] = ends
        out.append(entry)
    return out


def is_event_active(key: str) -> bool:
    for ev in active_events():
        if ev["key"] == key:
            return True
    return False


def active_win_multiplier(scope: str) -> float:
    """Произведение активных множителей выигрыша, применимых к данному скоупу."""
    mult = 1.0
    for ev in active_events():
        if ev["kind"] != "win_mult":
            continue
        targets = ev.get("targets") or ("all",)
        if "all" in targets or scope in targets:
            mult *= float(ev.get("value") or 1.0)
    return mult


def active_bet_discount(scope: str = "all") -> float:
    """Суммарная скидка на ставки для указанного скоупа (0..0.9)."""
    discount = 0.0
    for ev in active_events():
        if ev["kind"] != "bet_discount":
            continue
        targets = ev.get("targets") or ("all",)
        if "all" in targets or scope in targets:
            discount = max(discount, float(ev.get("value") or 0))
    return min(0.9, discount)


# ─────────── админ-команды ───────────


def _format_event_card(ev: Dict, active: bool, ends_at: int) -> str:
    badge = "🟢 АКТИВЕН" if active else "⚪️ не активен"
    endline = ""
    if active and ends_at:
        left = max(0, ends_at - int(time.time()))
        h = left // 3600
        m = (left % 3600) // 60
        endline = f"\nОстаток: <b>{h}ч {m}м</b>"
    elif active:
        endline = "\nДлительность: без срока (пока не выключишь)."
    return (
        f"<b>{ev['title']}</b>\n"
        f"{badge}{endline}\n"
        f"Тип: <code>{ev['kind']}</code>\n"
        f"Значение: <code>{ev.get('value')}</code>\n"
        f"Таргеты: <code>{', '.join(ev.get('targets') or ('all',))}</code>\n\n"
        f"{ev['description']}"
    )


def _page_kb(page: int, pages: int, active_keys: set) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    keys = list(CATALOG.keys())
    per = 10
    start = page * per
    chunk = keys[start : start + per]
    for key in chunk:
        meta = CATALOG[key]
        prefix = "🟢" if key in active_keys else "⚪️"
        kb.button(text=f"{prefix} {meta['title']}", callback_data=f"ev:open:{key}")
    if page > 0:
        kb.button(text="⬅️", callback_data=f"ev:page:{page - 1}")
    if page + 1 < pages:
        kb.button(text="➡️", callback_data=f"ev:page:{page + 1}")
    kb.button(text="❌ Выключить всё", callback_data="ev:stopall")
    kb.button(text="🛠 Закрыть", callback_data="ev:close")
    kb.adjust(1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 2)
    return kb.as_markup()


def _active_keys() -> set:
    _ensure_tables()
    cursor.execute(
        "SELECT event_key FROM events_state WHERE active = 1 AND (ends_at = 0 OR ends_at > ?)",
        (int(time.time()),),
    )
    return {row[0] for row in (cursor.fetchall() or [])}


def _pages_total() -> int:
    return (len(CATALOG) + 9) // 10


@router.message(Command("events"))
async def events_menu_cmd(message: types.Message):
    if not is_admin_or_higher(message.from_user.id):
        return
    await _send_events_page(message, 0)


async def _send_events_page(event: types.Message | types.CallbackQuery, page: int) -> None:
    pages = _pages_total()
    page = max(0, min(page, pages - 1))
    keys = _active_keys()
    text = (
        "<b>🎉 ИВЕНТЫ</b>\n"
        f"Страница {page + 1} / {pages} · всего в каталоге: {len(CATALOG)}\n"
        f"Активных сейчас: <b>{len(keys)}</b>\n\n"
        "Нажми на ивент — увидишь описание и кнопку запуска."
    )
    markup = _page_kb(page, pages, keys)
    target = event.message if isinstance(event, types.CallbackQuery) else event
    if isinstance(event, types.CallbackQuery):
        await event.answer()
        try:
            await target.edit_text(text, reply_markup=markup, parse_mode="HTML")
            return
        except Exception:
            pass
    await target.answer(text, reply_markup=markup, parse_mode="HTML")


@router.callback_query(F.data.startswith("ev:page:"))
async def events_page_cb(call: types.CallbackQuery):
    if not is_admin_or_higher(call.from_user.id):
        return await call.answer()
    page = int(call.data.split(":")[2])
    await _send_events_page(call, page)


@router.callback_query(F.data == "ev:close")
async def events_close(call: types.CallbackQuery):
    if not is_admin_or_higher(call.from_user.id):
        return await call.answer()
    await call.answer()
    try:
        await call.message.delete()
    except Exception:
        pass


@router.callback_query(F.data == "ev:stopall")
async def events_stop_all(call: types.CallbackQuery):
    if not is_admin_or_higher(call.from_user.id):
        return await call.answer()
    _ensure_tables()
    cursor.execute("UPDATE events_state SET active = 0, ends_at = 0")
    conn.commit()
    await call.answer("Все ивенты выключены.", show_alert=True)
    await _send_events_page(call, 0)


@router.callback_query(F.data.startswith("ev:open:"))
async def events_open_cb(call: types.CallbackQuery):
    if not is_admin_or_higher(call.from_user.id):
        return await call.answer()
    key = call.data.split(":", 2)[2]
    meta = CATALOG.get(key)
    if not meta:
        return await call.answer("Нет такого ивента", show_alert=True)
    await call.answer()
    _ensure_tables()
    cursor.execute("SELECT active, ends_at FROM events_state WHERE event_key = ?", (key,))
    row = cursor.fetchone()
    active = bool(row and row[0])
    ends_at = row[1] if row else 0
    if active and ends_at and ends_at <= int(time.time()):
        active = False

    kb = InlineKeyboardBuilder()
    if active:
        kb.button(text="⛔️ Выключить", callback_data=f"ev:stop:{key}")
    else:
        for hours, label in ((1, "1ч"), (meta["default_hours"], f"{meta['default_hours']}ч"), (24, "24ч")):
            kb.button(text=f"▶️ {label}", callback_data=f"ev:start:{key}:{hours}")
        kb.button(text="▶️ Без срока", callback_data=f"ev:start:{key}:0")
    kb.button(text="⬅️ К списку", callback_data="ev:page:0")
    kb.adjust(2, 2, 1)

    await call.message.edit_text(
        _format_event_card(meta, active, ends_at),
        reply_markup=kb.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("ev:start:"))
async def events_start_cb(call: types.CallbackQuery):
    if not is_admin_or_higher(call.from_user.id):
        return await call.answer()
    _, _, key, hours_str = call.data.split(":", 3)
    hours = int(hours_str)
    if key not in CATALOG:
        return await call.answer("Нет такого ивента", show_alert=True)
    ends_at = int(time.time()) + hours * 3600 if hours > 0 else 0
    _ensure_tables()
    cursor.execute(
        "INSERT OR REPLACE INTO events_state "
        "(event_key, active, ends_at, activated_by, activated_at) VALUES (?, 1, ?, ?, ?)",
        (key, ends_at, call.from_user.id, int(time.time())),
    )
    conn.commit()
    await call.answer("Ивент запущен.", show_alert=False)
    await events_open_cb(call)


@router.callback_query(F.data.startswith("ev:stop:"))
async def events_stop_cb(call: types.CallbackQuery):
    if not is_admin_or_higher(call.from_user.id):
        return await call.answer()
    key = call.data.split(":", 2)[2]
    _ensure_tables()
    cursor.execute(
        "UPDATE events_state SET active = 0, ends_at = 0 WHERE event_key = ?",
        (key,),
    )
    conn.commit()
    await call.answer("Ивент выключен.", show_alert=False)
    await events_open_cb(call)


@router.callback_query(F.data == "admin:events")
async def admin_events_jump(call: types.CallbackQuery):
    if not is_admin_or_higher(call.from_user.id):
        return await call.answer()
    await _send_events_page(call, 0)
