import time

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import conn, cursor, db_get_user
from utils import safe_reply_message

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
    
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        return await message.answer("❌ Профиль не найден. Начните с /start")

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

@router.message(Command("shop"))
@router.callback_query(F.data == "shop:back")
async def shop_cmd(event: types.Message | types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    # Премиум / статус
    builder.button(text="🔥 X2 Буст 24ч (100к)", callback_data="buy:boost_x2")
    builder.button(text="👑 Смена ID (100к)", callback_data="buy:id_change")
    builder.button(text="🍀 Клевер (500к)", callback_data="buy:clover")
    builder.button(text="💎 VIP-статус (1М)", callback_data="buy:vip")
    builder.button(text="📈 Безлимит (500к)", callback_data="buy:no_limit")
    # Mines
    builder.button(text="🛡 Саперный щит (50к)", callback_data="buy:mine_shield")
    builder.button(text="🔍 Сканер мин (80к)", callback_data="buy:mine_scan")
    # Казино
    builder.button(text="🔄 Переброс кубика (40к)", callback_data="buy:dice_reroll")
    builder.button(text="🃏 Страховка ставки (150к)", callback_data="buy:bet_insure")
    # Экономика
    builder.button(text="🏦 Сейф (400к)", callback_data="buy:safe_box")
    # Лотерея
    builder.button(text="🎟 Золотой билет (120к)", callback_data="buy:gold_ticket")
    # Перезарядка
    builder.button(text="⚡️ Энергетик (60к)", callback_data="buy:energy_drink")
    # Социальные
    builder.button(text="🕵️ Невидимка (180к)", callback_data="buy:incognito")

    builder.adjust(1)

    text = (
        "🛒 <b>МАГАЗИН БОНУСОВ</b>\n\nВыберите товар для покупки:"
    )

    if isinstance(event, types.CallbackQuery):
        await event.message.edit_text(
            text, reply_markup=builder.as_markup(), parse_mode="HTML"
        )
    else:
        await event.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")

@router.callback_query(F.data.startswith("buy:"))
async def process_buy(call: types.CallbackQuery):
    user_id = call.from_user.id
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        return await call.answer("Ошибка: профиль не найден")

    columns = [description[0] for description in cursor.description]
    u = dict(zip(columns, row))
    item = call.data.split(":")[1]

    prices = {
        "boost_x2": 100_000,
        "id_change": 100_000,
        "clover": 500_000,
        "vip": 1_000_000,
        "no_limit": 500_000,
        "mine_shield": 50_000,
        "mine_scan": 80_000,
        "dice_reroll": 40_000,
        "bet_insure": 150_000,
        "safe_box": 400_000,
        "gold_ticket": 120_000,
        "energy_drink": 60_000,
        "incognito": 180_000,
    }

    if item not in prices:
        return await call.answer("❌ Неизвестный предмет!", show_alert=True)

    price = prices[item]
    if u.get('balance', 0) < price:
        return await call.answer(
            f"❌ Недостаточно средств! Нужно {price:,} 💸", show_alert=True
        )

    success_text = "✅ Покупка совершена!"

    if item == "boost_x2":
        now = int(time.time())
        boost_until = now + (24 * 3600)
        cursor.execute("UPDATE users SET balance = balance - ?, boost_end = ? WHERE id = ?", 
                      (price, boost_until, user_id))
        success_text = "✅ Активирован <b>X2 Буст на 24 часа</b>! Все выигрыши удвоены."
    
    elif item == "id_change":
        success_text = (
            "📝 <b>Как сменить ID:</b>\n\n"
            "Используйте команду: <code>/newid [Имя]</code>\n"
            "Стоимость: <b>100,000 💎</b> (списывается при вводе команды)."
        )
    
    elif item == "clover":
        cursor.execute("UPDATE users SET balance = balance - ?, rig_prob = rig_prob + 5 WHERE id = ?", 
                      (price, user_id))
        success_text = "✅ Куплен <b>Клевер</b>! Ваша удача +5% 🍀"
    
    elif item == "vip":
        cursor.execute("UPDATE users SET balance = balance - ?, rigged_mode = 'vip' WHERE id = ?", 
                      (price, user_id))
        success_text = "✅ Вы получили <b>VIP Статус</b>! 👑 Теперь вы выглядите круче."
    
    elif item == "no_limit":
        cursor.execute("UPDATE users SET balance = balance - ?, luck_end = 777 WHERE id = ?", 
                      (price, user_id))
        success_text = "✅ Активирован <b>Безлимит</b>! Ставьте сколько хотите."
    
    elif item == "mine_shield":
        cursor.execute("UPDATE users SET balance = balance - ?, mine_shield = COALESCE(mine_shield, 0) + 1 WHERE id = ?", 
                      (price, user_id))
        success_text = "✅ Куплен <b>Саперный щит</b>! Он защитит вас при взрыве на мине."
        
    elif item == "mine_scan":
        cursor.execute("UPDATE users SET balance = balance - ?, mine_scan = COALESCE(mine_scan, 0) + 3 WHERE id = ?", 
                      (price, user_id))
        success_text = "✅ Куплено 3 <b>Сканера мин</b>! Используйте их в игре Mines для просмотра мин."

    elif item == "dice_reroll":
        cursor.execute("UPDATE users SET balance = balance - ?, rerolls = COALESCE(rerolls, 0) + 1 WHERE id = ?", 
                      (price, user_id))
        success_text = "✅ Куплен <b>Переброс кубика</b>! Один раз перекидайте результат игры."

    elif item == "bet_insure":
        cursor.execute("UPDATE users SET balance = balance - ?, bet_insure = COALESCE(bet_insure, 0) + 1 WHERE id = ?", 
                      (price, user_id))
        success_text = "✅ Куплена <b>Страховка ставки</b>! При проигрыше вернется 50%."

    elif item == "safe_box":
        cursor.execute("UPDATE users SET balance = balance - ?, safe_box_level = COALESCE(safe_box_level, 0) + 1 WHERE id = ?", 
                      (price, user_id))
        success_text = "✅ Куплен <b>Сейф</b>! Защитите часть своего баланса от обнуления."

    elif item == "gold_ticket":
        cursor.execute("UPDATE users SET balance = balance - ?, gold_ticket = COALESCE(gold_ticket, 0) + 1 WHERE id = ?", 
                      (price, user_id))
        success_text = "✅ Куплен <b>Золотой билет</b>! Шанс выиграть джекпот x3 в лотерее."

    elif item == "energy_drink":
        cursor.execute("UPDATE users SET balance = balance - ?, energy_drink = COALESCE(energy_drink, 0) + 1 WHERE id = ?", 
                      (price, user_id))
        success_text = "✅ Куплен <b>Энергетик</b>! Используйте для сброса КД на ежедневный бонус."

    elif item == "incognito":
        cursor.execute("UPDATE users SET balance = balance - ?, incognito_mode = 1 WHERE id = ?", 
                      (price, user_id))
        success_text = "✅ Активирован <b>Режим невидимки</b>! Вы скрыты в топе богачей 🕵️"

    conn.commit()

    back_kb = InlineKeyboardBuilder()
    back_kb.button(text="⬅️ В магазин", callback_data="shop:back")

    await call.message.edit_text(
        success_text, reply_markup=back_kb.as_markup(), parse_mode="HTML"
    )
    await call.answer("✅ Спасибо за покупку!")


@router.message(Command("bonus"))
async def get_bonus(message: types.Message):
    user_id = message.from_user.id
    now = int(time.time())
    
    cursor.execute("SELECT last_bonus, energy_drink FROM users WHERE id = ?", (user_id,))
    u = cursor.fetchone()
    last_bonus, drinks = u[0], u[1]
    
    if now - last_bonus < 86400:
        kb = InlineKeyboardBuilder()
        if drinks > 0:
            kb.button(text=f"⚡️ Выпить энергетик ({drinks} шт.)", callback_data="use:energy")
        
        remains = (86400 - (now - last_bonus)) // 3600
        return await message.answer(f"⏳ Бонус будет доступен через {remains} ч.", 
                                    reply_markup=kb.as_markup())

    reward = 5000
    cursor.execute(
        "UPDATE users SET balance = balance + ?, last_bonus = ? WHERE id = ?",
        (reward, now, user_id),
    )
    conn.commit()
    await message.answer(
        f"🎁 Вы получили ежедневный бонус: <b>{reward:,}</b> 💸"
    )

@router.callback_query(F.data == "use:energy")
async def use_energy_logic(call: types.CallbackQuery):
    user_id = call.from_user.id
    cursor.execute("SELECT energy_drink FROM users WHERE id = ?", (user_id,))
    drinks = cursor.fetchone()[0]
    
    if drinks <= 0:
        return await call.answer("❌ Энергетики закончились!", show_alert=True)

    cursor.execute(
        "UPDATE users SET energy_drink = energy_drink - 1, last_bonus = 0 WHERE id = ?",
        (user_id,),
    )
    conn.commit()

    await call.message.edit_text(
        "⚡️ Вы выпили энергетик! Теперь введите /bonus, чтобы получить бонус."
    )


@router.message(Command("newid"))
async def change_custom_id(message: types.Message):
    user_data = await check_user(message)
    if not user_data: return
    
    if user_data[0] < 100000:
        return await message.reply("❌ Недостаточно средств (100,000 💎).")
    
    args = message.text.split()
    if len(args) < 2:
        return await message.reply("📝 Напишите имя: `/newid [Слово]`")
    
    new_name = args[1][:30]
    if new_name.isdigit():
        return await message.reply("❌ Имя не может состоять только из цифр.")

    cursor.execute("SELECT id FROM users WHERE custom_id = ?", (new_name,))
    if cursor.fetchone():
        return await message.reply("❌ Этот ID уже занят!")

    try:
        cursor.execute(
            "UPDATE users SET custom_id = ?, balance = balance - 100000 WHERE id = ?",
            (new_name, message.from_user.id),
        )
        conn.commit()
        await message.reply(f"✅ Успех! Твой новый публичный ID: `{new_name}`")
    except Exception:
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

