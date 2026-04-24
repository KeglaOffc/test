import logging
import time

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import conn, cursor, db_get_user
from utils import safe_reply_message

logger = logging.getLogger(__name__)
router = Router()


async def check_user(message: types.Message):
    """Возвращает профиль игрока, или ``None``, если он забанен."""
    data = db_get_user(message.from_user.id)
    if data and data[2] == 1:
        await message.reply("🚫 Вы заблокированы администрацией.")
        return None
    return data

@router.message(Command("help", "qhelp"))
async def cmd_help(message: types.Message):
    if not await check_user(message): return
    
    help_text = (
        "📚 **СПРАВОЧНИК КОМАНД**\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "👤 **ОСНОВНОЕ:**\n"
        "• `/start` — Мой профиль и статистика\n"
        "• `/shop` — Магазин улучшений и бонусов\n"
        "• `/bonus` — Ежедневная награда\n"
        "• `/top` — Рейтинг богачей и везунчиков\n"
        "• `/newid [имя]` — Установить уникальный ник (100к)\n"
        "• `/games` — Меню выбора игр\n\n"

        "🎰 **АЗАРТНЫЕ ИГРЫ:**\n"
        "• `/slot [сумма]` — Слоты (до x30 на 777)\n"
        "• `/roulette [сумма]` — Европейская рулетка\n"
        "• `/mines [сумма] [бомбы]` — Сапёр\n"
        "• `/flip [сумма]` — Орёл или решка (x1.9 / x5)\n"
        "• `/chests [сумма]` — Сундуки удачи\n"
        "• `/crash` — Краш-игра\n"
        "• `/wheel` — Колесо фортуны (раз в сутки бесплатно)\n"
        "• `/lottery` — Лотерейный центр\n"
        "• `/scratch` — Мгновенная лотерея\n\n"

        "⚔️ **DUELS & SPORT (PVP):**\n"
        "• `/pvp` — Меню дуэлей с игроками\n"
        "• `/dice [сумма]` — Кости против бота\n"
        "• `/darts [сумма]` — Дартс против бота\n"
        "• `/football [сумма]` — Серия пенальти\n"
        "• `/basket [сумма]` — Броски в кольцо\n\n"
        
        "💡 *Пример: /mines 1000 3 (ставка 1000, 3 бомбы)*"
    )
    await message.answer(help_text, parse_mode="Markdown")

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id

    db_get_user(user_id)

    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        return await message.answer(
            "❌ Не удалось создать профиль. Попробуй ещё раз через минуту."
        )

    columns = [description[0] for description in cursor.description]
    u = dict(zip(columns, row))

    profit = u['total_wins'] - u['total_bets']
    now = int(time.time())
    
    aura = "✨" if u.get('aura_active') == 1 else ""
    vip = "👑" if u['rigged_mode'] == 'vip' else ""

    if u['boost_end'] > now:
        boost_time = (u['boost_end'] - now) // 3600
        boost_status = f"🔥 x2 ({boost_time}ч)"
    else:
        boost_status = "💤"

    limit_text = "♾ Безлимит" if u['luck_end'] == 777 else "Standard (1M)"
    incognito_status = (
        "👁‍🗨 Скрыт" if u.get('incognito_mode') == 1 else "🌍 Публичный"
    )

    safe_lvl = u.get('safe_box_level', 0)
    safe_info = f"{safe_lvl} ур." if safe_lvl > 0 else "❌"

    lvl = u['games_played'] // 50
    progress = min(10, (u['games_played'] % 50) // 5)
    bar = "▰" * progress + "▱" * (10 - progress)

    inv_items = []
    if u.get('gold_ticket'): inv_items.append("🎟")
    if u.get('mine_shield'): inv_items.append(f"🛡x{u['mine_shield']}")
    if u.get('mine_scan'): inv_items.append(f"🔍x{u['mine_scan']}")
    if u.get('energy_drink'): inv_items.append(f"⚡x{u['energy_drink']}")
    if u.get('rerolls'): inv_items.append(f"🔄x{u['rerolls']}")
    
    inv_str = " | ".join(inv_items) if inv_items else "Пусто"

    pvp_wins = u.get('pvp_wins', 0)
    free_games_status = "🏆" if u.get('free_games_unlocked', 0) == 1 else "📊"
    pvp_status = f"{free_games_status} {pvp_wins}/50 побед" if pvp_wins < 50 else f"🏆 {pvp_wins} побед - ВИП!"

    text = (
        f"{aura} **ЛИЧНЫЙ КАБИНЕТ** {vip}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 **Игрок:** `{u['custom_id'] or u['id']}`\n"
        f"🔢 **ID:** `{user_id}`\n"
        f"💳 **Баланс:** `{u['balance']:,}` 💎\n"
        f"🏆 **Уровень {lvl}:**\n"
        f"`[{bar}]` ({u['games_played']} игр)\n\n"
        
        f"📊 **СТАТИСТИКА:**\n"
        f"• Выигрыши: `{u['total_wins']:,}`\n"
        f"• Ставки: `{u['total_bets']:,}`\n"
        f"• Профит: `{profit:+,}`\n"
        f"• Буст: {boost_status}\n"
        f"• Лимит: `{limit_text}`\n"
        f"• Статус: `{incognito_status}`\n"
        f"• Сейф: `{safe_info}`\n"
        f"• PVP: `{pvp_status}`\n\n"
        
        f"🎒 **ИНВЕНТАРЬ:**\n"
        f"{inv_str}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎮 **Меню:** /games  |  🛒 **Магазин:** /shop"
    )
    
    await safe_reply_message(message, text, parse_mode="Markdown")

SHOP_CATALOG = {
    "boost_x2":     {"price": 100_000,   "title": "🔥 X2 Буст 24ч",       "desc": "Все выигрыши удваиваются на 24 часа."},
    "clover":       {"price": 500_000,   "title": "🍀 Клевер удачи",       "desc": "+5% к базовому шансу выигрыша (стакается)."},
    "vip":          {"price": 1_000_000, "title": "💎 VIP-статус",          "desc": "Пожизненный VIP-бейдж. Один раз."},
    "no_limit":     {"price": 500_000,   "title": "📈 Безлимит ставок",    "desc": "Снимает потолок ставки в 1 млн."},
    "mine_shield":  {"price": 50_000,    "title": "🛡 Саперный щит",       "desc": "Спасает один взрыв в /mines. До 10 шт."},
    "mine_scan":    {"price": 80_000,    "title": "🔍 Сканер мин",         "desc": "Подсвечивает одну мину в /mines. Пачка из 3. До 15 шт."},
    "dice_reroll":  {"price": 40_000,    "title": "🔄 Переброс кубика",    "desc": "Перекинуть результат в /dice и /darts. До 10 шт."},
    "bet_insure":   {"price": 150_000,   "title": "🃏 Страховка ставки",   "desc": "При проигрыше возвращает 50% ставки. До 10 шт."},
    "safe_box":     {"price": 400_000,   "title": "🏦 Сейф (уровень +1)",  "desc": "Защищает 20% баланса за уровень. До 5 уровней."},
    "gold_ticket":  {"price": 120_000,   "title": "🎟 Золотой билет",      "desc": "Утраивает джекпот, если выпал в лотерее. До 5 шт."},
    "energy_drink": {"price": 60_000,    "title": "⚡️ Энергетик",          "desc": "Сбрасывает КД на /bonus. До 10 шт."},
    "incognito":    {"price": 180_000,   "title": "🕵️ Режим невидимки",    "desc": "Прячет тебя в /top. Включается один раз."},
}

STACK_LIMITS = {
    "mine_shield": 10,
    "mine_scan": 15,
    "dice_reroll": 10,
    "bet_insure": 10,
    "safe_box": 5,
    "gold_ticket": 5,
    "energy_drink": 10,
}


def _render_shop(balance: int) -> tuple[str, types.InlineKeyboardMarkup]:
    builder = InlineKeyboardBuilder()
    for key, meta in SHOP_CATALOG.items():
        builder.button(
            text=f"{meta['title']} · {meta['price']:,} 💎",
            callback_data=f"buy:{key}",
        )
    builder.adjust(1)
    text = (
        "🛒 <b>МАГАЗИН</b>\n"
        f"💳 Баланс: <b>{balance:,}</b> 💎\n\n"
        "Нажми на предмет — покажу описание и предложу купить."
    )
    return text, builder.as_markup()


@router.message(Command("shop"))
@router.callback_query(F.data == "shop:back")
async def shop_cmd(event: types.Message | types.CallbackQuery):
    uid = event.from_user.id
    u = db_get_user(uid)
    if not u:
        if isinstance(event, types.CallbackQuery):
            return await event.answer("Не удалось загрузить профиль.", show_alert=True)
        return await event.answer("❌ Не удалось загрузить профиль.")
    text, markup = _render_shop(u[0])

    if isinstance(event, types.CallbackQuery):
        await event.answer()
        try:
            await event.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
        except Exception:
            await event.message.answer(text, reply_markup=markup, parse_mode="HTML")
    else:
        await event.answer(text, reply_markup=markup, parse_mode="HTML")


@router.callback_query(F.data.startswith("buy:"))
async def buy_preview(call: types.CallbackQuery):
    await call.answer()
    item = call.data.split(":", 1)[1]
    meta = SHOP_CATALOG.get(item)
    if not meta:
        return await call.answer("❌ Такого предмета нет.", show_alert=True)

    uid = call.from_user.id
    u = db_get_user(uid)
    if not u:
        return await call.answer("Ошибка загрузки профиля.", show_alert=True)

    status_hint = _check_already_owns(item, uid)
    text = (
        f"<b>{meta['title']}</b>\n"
        f"Цена: <b>{meta['price']:,}</b> 💎\n\n"
        f"{meta['desc']}\n"
    )
    if status_hint:
        text += f"\n⚠️ {status_hint}"
    text += f"\n💳 Твой баланс: {u[0]:,} 💎"

    kb = InlineKeyboardBuilder()
    if not status_hint or status_hint.startswith("У тебя уже"):
        kb.button(text="💸 Купить", callback_data=f"confirm_buy:{item}")
    kb.button(text="⬅️ Назад", callback_data="shop:back")
    kb.adjust(1)
    try:
        await call.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    except Exception:
        await call.message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")


def _check_already_owns(item: str, uid: int) -> str | None:
    """Вернёт предупреждение, если предмет уже нельзя покупать (или достигнут предел стэка)."""
    cursor.execute("SELECT * FROM users WHERE id = ?", (uid,))
    row = cursor.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cursor.description]
    u = dict(zip(cols, row))

    if item == "vip" and u.get("rigged_mode") == "vip":
        return "У тебя уже VIP-статус — покупка заблокирована."
    if item == "no_limit" and u.get("luck_end") == 777:
        return "Безлимит уже активирован — покупка заблокирована."
    if item == "incognito" and u.get("incognito_mode") == 1:
        return "Режим невидимки уже включён — покупка заблокирована."
    if item == "boost_x2":
        now = int(time.time())
        boost_end = u.get("boost_end", 0) or 0
        if boost_end > now:
            left = (boost_end - now) // 3600
            return f"Буст ещё активен (~{left} ч). Можно купить ещё — таймер сбросится на 24 ч."

    limit = STACK_LIMITS.get(item)
    if limit is not None:
        have = u.get(item if item != "safe_box" else "safe_box_level", 0) or 0
        if have >= limit:
            return f"Достигнут лимит ({limit} шт.) — покупка недоступна."
    return None


def _apply_purchase(item: str, uid: int) -> tuple[bool, str]:
    """Атомарное списание баланса + эффект. Возвращает (успех, сообщение)."""
    meta = SHOP_CATALOG[item]
    price = meta["price"]

    blocker = _check_already_owns(item, uid)
    if blocker and not blocker.startswith("Буст ещё активен"):
        return False, f"⚠️ {blocker}"

    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            "UPDATE users SET balance = balance - ? WHERE id = ? AND balance >= ?",
            (price, uid, price),
        )
        if cursor.rowcount == 0:
            cursor.execute("ROLLBACK")
            return False, f"❌ Недостаточно средств. Нужно {price:,} 💎."

        if item == "boost_x2":
            boost_until = int(time.time()) + 24 * 3600
            cursor.execute("UPDATE users SET boost_end = ? WHERE id = ?", (boost_until, uid))
            msg = "🔥 Буст x2 активирован на 24 часа."
        elif item == "clover":
            cursor.execute("UPDATE users SET rig_prob = MIN(rig_prob + 5, 95) WHERE id = ?", (uid,))
            msg = "🍀 Клевер применён. Удача +5% (макс 95%)."
        elif item == "vip":
            cursor.execute("UPDATE users SET rigged_mode = 'vip' WHERE id = ?", (uid,))
            msg = "💎 Тебе выдан VIP-статус."
        elif item == "no_limit":
            cursor.execute("UPDATE users SET luck_end = 777 WHERE id = ?", (uid,))
            msg = "📈 Безлимит ставок активирован."
        elif item == "mine_shield":
            cursor.execute("UPDATE users SET mine_shield = COALESCE(mine_shield, 0) + 1 WHERE id = ?", (uid,))
            msg = "🛡 Саперный щит добавлен в инвентарь."
        elif item == "mine_scan":
            cursor.execute("UPDATE users SET mine_scan = COALESCE(mine_scan, 0) + 3 WHERE id = ?", (uid,))
            msg = "🔍 В инвентарь добавлено 3 сканера мин."
        elif item == "dice_reroll":
            cursor.execute("UPDATE users SET rerolls = COALESCE(rerolls, 0) + 1 WHERE id = ?", (uid,))
            msg = "🔄 Переброс кубика добавлен."
        elif item == "bet_insure":
            cursor.execute("UPDATE users SET bet_insure = COALESCE(bet_insure, 0) + 1 WHERE id = ?", (uid,))
            msg = "🃏 Страховка ставки добавлена."
        elif item == "safe_box":
            cursor.execute(
                "UPDATE users SET safe_box_level = COALESCE(safe_box_level, 0) + 1 WHERE id = ?",
                (uid,),
            )
            msg = "🏦 Уровень сейфа повышен."
        elif item == "gold_ticket":
            cursor.execute("UPDATE users SET gold_ticket = COALESCE(gold_ticket, 0) + 1 WHERE id = ?", (uid,))
            msg = "🎟 Золотой билет добавлен."
        elif item == "energy_drink":
            cursor.execute("UPDATE users SET energy_drink = COALESCE(energy_drink, 0) + 1 WHERE id = ?", (uid,))
            msg = "⚡️ Энергетик добавлен."
        elif item == "incognito":
            cursor.execute("UPDATE users SET incognito_mode = 1 WHERE id = ?", (uid,))
            msg = "🕵️ Режим невидимки включён."
        else:
            cursor.execute("ROLLBACK")
            return False, "❌ Неизвестный предмет."

        conn.commit()
        return True, f"✅ {msg}"
    except Exception:
        cursor.execute("ROLLBACK")
        logger.exception("shop: ошибка покупки %s", item)
        return False, "❌ Ошибка при покупке, попробуй ещё раз."


@router.callback_query(F.data.startswith("confirm_buy:"))
async def buy_confirm(call: types.CallbackQuery):
    await call.answer()
    item = call.data.split(":", 1)[1]
    if item not in SHOP_CATALOG:
        return await call.answer("❌ Неизвестный предмет.", show_alert=True)

    ok, msg = _apply_purchase(item, call.from_user.id)

    u = db_get_user(call.from_user.id)
    balance_line = f"\n💳 Баланс: {u[0]:,} 💎" if u else ""

    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ В магазин", callback_data="shop:back")
    kb.adjust(1)

    try:
        await call.message.edit_text(
            msg + balance_line, reply_markup=kb.as_markup(), parse_mode="HTML"
        )
    except Exception:
        await call.message.answer(msg + balance_line, reply_markup=kb.as_markup(), parse_mode="HTML")


@router.message(Command("bonus"))
async def get_bonus(message: types.Message):
    user_id = message.from_user.id
    now = int(time.time())
    reward = 5000
    cooldown = 86400

    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            "UPDATE users SET balance = balance + ?, last_bonus = ? "
            "WHERE id = ? AND (? - COALESCE(last_bonus, 0)) >= ?",
            (reward, now, user_id, now, cooldown),
        )
        if cursor.rowcount == 0:
            cursor.execute("ROLLBACK")
            cursor.execute(
                "SELECT last_bonus, energy_drink FROM users WHERE id = ?", (user_id,)
            )
            row = cursor.fetchone() or (0, 0)
            last_bonus, drinks = row[0] or 0, row[1] or 0
            kb = InlineKeyboardBuilder()
            if drinks > 0:
                kb.button(text=f"⚡️ Выпить энергетик ({drinks})", callback_data="use:energy")
            remains = max(0, cooldown - (now - last_bonus)) // 3600
            return await message.answer(
                f"⏳ Бонус будет доступен через {remains} ч.",
                reply_markup=kb.as_markup(),
            )
        conn.commit()
    except Exception:
        cursor.execute("ROLLBACK")
        logger.exception("bonus: failed")
        return await message.answer("❌ Ошибка, попробуй ещё раз.")

    await message.answer(
        f"🎁 Ежедневный бонус зачислен: <b>{reward:,}</b> 💎",
        parse_mode="HTML",
    )


@router.callback_query(F.data == "use:energy")
async def use_energy_logic(call: types.CallbackQuery):
    user_id = call.from_user.id
    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            "UPDATE users SET energy_drink = energy_drink - 1, last_bonus = 0 "
            "WHERE id = ? AND COALESCE(energy_drink, 0) > 0",
            (user_id,),
        )
        if cursor.rowcount == 0:
            cursor.execute("ROLLBACK")
            return await call.answer("❌ Энергетики закончились!", show_alert=True)
        conn.commit()
    except Exception:
        cursor.execute("ROLLBACK")
        logger.exception("use:energy failed")
        return await call.answer("Ошибка.", show_alert=True)

    await call.message.edit_text(
        "⚡️ Вы выпили энергетик! Теперь введите /bonus, чтобы получить бонус."
    )


@router.message(Command("newid"))
async def change_custom_id(message: types.Message):
    user_data = await check_user(message)
    if not user_data:
        return

    args = message.text.split()
    if len(args) < 2:
        return await message.reply("📝 Напишите имя: `/newid [Слово]`")

    new_name = args[1][:30]
    if new_name.isdigit():
        return await message.reply("❌ Имя не может состоять только из цифр.")

    price = 100_000
    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute("SELECT id FROM users WHERE custom_id = ?", (new_name,))
        if cursor.fetchone():
            cursor.execute("ROLLBACK")
            return await message.reply("❌ Этот ID уже занят!")
        cursor.execute(
            "UPDATE users SET custom_id = ?, balance = balance - ? "
            "WHERE id = ? AND balance >= ?",
            (new_name, price, message.from_user.id, price),
        )
        if cursor.rowcount == 0:
            cursor.execute("ROLLBACK")
            return await message.reply(f"❌ Недостаточно средств ({price:,} 💎).")
        conn.commit()
        await message.reply(f"✅ Твой новый публичный ID: `{new_name}`")
    except Exception:
        cursor.execute("ROLLBACK")
        logger.exception("newid: failed")
        await message.reply("❌ Ошибка при обновлении базы.")


@router.message(Command("games"))
async def games_list(message: types.Message):
    text = (
        "🎮 **ДОСТУПНЫЕ ИГРЫ:**\n\n"
        "🎰 `/slot [ставка]` - Игровой автомат\n"
        "🎡 `/roulette [ставка]` - Рулетка\n"
        "💣 `/mines [ставка] [бомбы]` - Мины\n"
        "🪙 `/flip [ставка]` - Монетка\n"
        "📦 `/chests [ставка]` - Сундуки\n"
        "🎯 `/darts [ставка]` - Дартс (дуэль)\n"
        "🎲 `/dice [ставка]` - Кости (дуэль)\n"
        "🏀 `/basket [ставка]` - Баскетбол\n"
        "⚽ `/football [ставка]` - Пенальти\n"
        "⚔️ `/pvp` - PvP-дуэли с игроками\n"
        "🚀 `/crash` - Краш (полёт множителя)\n"
        "🎫 `/lottery` - Лотерейный центр\n"
        "🎟 `/scratch` - Мгновенная лотерея\n"
        "🎁 `/wheel` - Колесо фортуны\n"
        "⛏️ `/mining` - Майнинг-симулятор"
    )
    await message.answer(text, parse_mode="Markdown")

