import asyncio
import time
import random  # Обязательно добавляем этот импорт
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database import db_get_user, db_update_stats, get_real_id, cursor, conn
from utils import safe_reply_message

router = Router()

# --- ВСПОМОГАТЕЛЬНАЯ ПРОВЕРКА ---
async def check_user(message: types.Message):
    data = db_get_user(message.from_user.id)
    if data and data[2] == 1:
        await message.reply("🚫 Вы заблокированы администрацией.")
        return None
    return data

# --- КОМАНДА ПОМОЩЬ / ИНФОРМАЦИЯ ---
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
        "• `/slot [сумма]` — Крутить слоты (3 в ряд = x15)\n"
        "• `/mines [сумма] [бомбы]` — Сапер (чем дальше, тем больше)\n"
        "• `/flip [сумма]` — Орел или Решка (x1.9 / x5)\n"
        "• `/chests [сумма] [режим]` — Сундуки удачи (x3)\n"
        "• `/lottery` — Лотерейный центр (Джекпоты)\n\n"

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
    
    # 1. Получаем данные пользователя в виде словаря для удобства
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        return await message.answer("❌ Профиль не найден. Начните с /start")

    columns = [description[0] for description in cursor.description]
    u = dict(zip(columns, row))

    # 2. Расчеты и логика
    profit = u['total_wins'] - u['total_bets']
    now = int(time.time())
    
    # Визуальные эффекты
    aura = "✨" if u.get('aura_active') == 1 else ""
    vip = "👑" if u['rigged_mode'] == 'vip' else ""
    
    # Буст
    if u['boost_end'] > now:
        boost_time = (u['boost_end'] - now) // 3600
        boost_status = f"🔥 x2 ({boost_time}ч)"
    else:
        boost_status = "💤"

    # Лимиты и Невидимка (Восстановлено)
    limit_text = "♾ Безлимит" if u['luck_end'] == 777 else "Standard (1M)"
    incognito_status = "👁‍🗨 Скрыт" if u.get('incognito_mode') == 1 else "🌍 Публичный"

    # Сейф (Восстановлено)
    safe_lvl = u.get('safe_box_level', 0)
    safe_info = f"{safe_lvl} ур." if safe_lvl > 0 else "❌"

    # Прогресс бар (примерно, от 100 игр)
    lvl = u['games_played'] // 50
    progress = min(10, (u['games_played'] % 50) // 5)
    bar = "▰" * progress + "▱" * (10 - progress)
    
    # Инвентарь иконки
    inv_items = []
    if u.get('gold_ticket'): inv_items.append("🎟")
    if u.get('mine_shield'): inv_items.append(f"🛡x{u['mine_shield']}")
    if u.get('mine_scan'): inv_items.append(f"🔍x{u['mine_scan']}")
    if u.get('energy_drink'): inv_items.append(f"⚡x{u['energy_drink']}")
    if u.get('rerolls'): inv_items.append(f"🔄x{u['rerolls']}")
    
    inv_str = " | ".join(inv_items) if inv_items else "Пусто"
    
    # PVP статистика
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
    
    # Use safe reply function
    await safe_reply_message(message, text, parse_mode="Markdown")

@router.message(Command("shop"))
@router.callback_query(F.data == "shop:back")
async def shop_cmd(event: types.Message | types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    
    # Старые предметы
    builder.button(text="🔥 X2 Буст 24ч (100к)", callback_data="buy:boost_x2")
    builder.button(text="👑 Смена ID (100к)", callback_data="buy:id_change")
    builder.button(text="🍀 Клевер (500к)", callback_data="buy:clover")
    builder.button(text="💎 VIP Статус (1М)", callback_data="buy:vip")
    builder.button(text="📈 Безлимит (500к)", callback_data="buy:no_limit")
    
    # --- НОВЫЕ 10 ПРЕДМЕТОВ ---
    # Для MINES (Сапер)
    builder.button(text="🛡 Саперный щит (50к)", callback_data="buy:mine_shield") # Защита от 1 мины
    builder.button(text="🔍 Сканер мин (80к)", callback_data="buy:mine_scan") # Показывает 1 мину
    
    # Для казино / азарта
    builder.button(text="🔄 Переброс кубика (40к)", callback_data="buy:dice_reroll")
    builder.button(text="🃏 Страховка ставки (150к)", callback_data="buy:bet_insure") # Возврат 50% при проигрыше
    
    # Накопительные / Экономика
    # Кэшбэк удален по запросу (дизбаланс)
    # builder.button(text="💰 Кэшбэк 5% (300к)", callback_data="buy:cashback") 
    builder.button(text="🏦 Сейф (400к)", callback_data="buy:safe_box") # Защита части баланса от обнуления
    
    # Геймплейные
    builder.button(text="🎟 Золотой билет (120к)", callback_data="buy:gold_ticket") # Шанс в лотерее x3
    builder.button(text="⚡️ Энергетик (60к)", callback_data="buy:energy_drink") # Сброс КД на бонус
    
    # Социальные / Статус
    # Аура удалена по запросу
    builder.button(text="🕵️ Невидимка (180к)", callback_data="buy:incognito") # Скрывает в топе богачей
    
    builder.adjust(1, 1, 1, 1, 1, 2, 2, 1, 2, 1)
    
    text = "🛒 <b>МАГАЗИН БОНУСОВ</b>\n\nВыберите товар для покупки:"
    
    if isinstance(event, types.CallbackQuery):
        await event.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    else:
        await event.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")

@router.callback_query(F.data.startswith("buy:"))
async def process_buy(call: types.CallbackQuery):
    user_id = call.from_user.id
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    if not row: return await call.answer("Ошибка: профиль не найден")

    # реобразуем список в словарь для удобства
    columns = [description[0] for description in cursor.description]
    u = dict(zip(columns, row))
    item = call.data.split(":")[1]
    
    prices = {
        "boost_x2": 100000, "id_change": 100000, "clover": 500000, "vip": 1000000, "no_limit": 500000,
        "mine_shield": 50000, "mine_scan": 80000, "dice_reroll": 40000, "bet_insure": 150000,
        "cashback": 999999999, "safe_box": 400000, "gold_ticket": 120000, "energy_drink": 60000,
        "aura": 999999999, "incognito": 180000
    }
    
    price = prices.get(item, 0)
    if u.get('balance', 0) < price:
        return await call.answer(f"❌ Недостаточно средств! Нужно {price:,} 💸", show_alert=True)

    success_text = "✅ Покупка совершена!"
    
    # === СТАРЫЕ ПРЕДМЕТЫ ===
    if item == "boost_x2":
        now = int(time.time())
        boost_until = now + (24 * 3600)
        cursor.execute("UPDATE users SET balance = balance - ?, boost_end = ? WHERE id = ?", 
                      (price, boost_until, user_id))
        success_text = "✅ Активирован <b>X2 Буст на 24 часа</b>! Все выигрыши удвоены."
    
    elif item == "id_change":
        success_text = "📝 <b>Как сменить ID:</b>\n\nИспользуйте команду: <code>/newid [Имя]</code>\nСтоимость: <b>100,000 💎</b> (списывается при вводе команды)."
        # cursor.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (price, user_id)) # Отключено, т.к. списывает команда
    
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
    
    # === НОВЫЕ ПРЕДМЕТЫ ДЛЯ MINES ===
    elif item == "mine_shield":
        cursor.execute("UPDATE users SET balance = balance - ?, mine_shield = COALESCE(mine_shield, 0) + 1 WHERE id = ?", 
                      (price, user_id))
        success_text = "✅ Куплен <b>Саперный щит</b>! Он защитит вас при взрыве на мине."
        
    elif item == "mine_scan":
        cursor.execute("UPDATE users SET balance = balance - ?, mine_scan = COALESCE(mine_scan, 0) + 3 WHERE id = ?", 
                      (price, user_id))
        success_text = "✅ Куплено 3 <b>Сканера мин</b>! Используйте их в игре Mines для просмотра мин."

    # === КАЗИНО ===
    elif item == "dice_reroll":
        cursor.execute("UPDATE users SET balance = balance - ?, rerolls = COALESCE(rerolls, 0) + 1 WHERE id = ?", 
                      (price, user_id))
        success_text = "✅ Куплен <b>Переброс кубика</b>! Один раз перекидайте результат игры."

    elif item == "bet_insure":
        cursor.execute("UPDATE users SET balance = balance - ?, bet_insure = COALESCE(bet_insure, 0) + 1 WHERE id = ?", 
                      (price, user_id))
        success_text = "✅ Куплена <b>Страховка ставки</b>! При проигрыше вернется 50%."

    # === ЭКОНОМИКА ===
    elif item == "cashback":
        if u.get('has_cashback'):
            return await call.answer("❌ У вас уже активирован кэшбэк!", show_alert=True)
        cursor.execute("UPDATE users SET balance = balance - ?, has_cashback = 1 WHERE id = ?", 
                      (price, user_id))
        success_text = "✅ Активирован <b>Кэшбэк 5%</b>! Получайте возврат с каждой ставки."

    elif item == "safe_box":
        cursor.execute("UPDATE users SET balance = balance - ?, safe_box_level = COALESCE(safe_box_level, 0) + 1 WHERE id = ?", 
                      (price, user_id))
        success_text = "✅ Куплен <b>Сейф</b>! Защитите часть своего баланса от обнуления."

    # === ЛОТЕРЕЯ ===
    elif item == "gold_ticket":
        cursor.execute("UPDATE users SET balance = balance - ?, gold_ticket = COALESCE(gold_ticket, 0) + 1 WHERE id = ?", 
                      (price, user_id))
        success_text = "✅ Куплен <b>Золотой билет</b>! Шанс выиграть джекпот x3 в лотерее."

    # === ПЕРЕЗАРЯДКА ===
    elif item == "energy_drink":
        cursor.execute("UPDATE users SET balance = balance - ?, energy_drink = COALESCE(energy_drink, 0) + 1 WHERE id = ?", 
                      (price, user_id))
        success_text = "✅ Куплен <b>Энергетик</b>! Используйте для сброса КД на ежедневный бонус."

    # === СОЦИАЛЬНЫЕ ===
    elif item == "aura":
        cursor.execute("UPDATE users SET balance = balance - ?, aura_active = 1 WHERE id = ?", 
                      (price, user_id))
        success_text = "✅ Активирована <b>Аура героя</b>! Ваше имя сияет в профиле ✨"

    elif item == "incognito":
        cursor.execute("UPDATE users SET balance = balance - ?, incognito_mode = 1 WHERE id = ?", 
                      (price, user_id))
        success_text = "✅ Активирован <b>Режим невидимки</b>! Вы скрыты в топе богачей 🕵️"

    else:
        return await call.answer("❌ Неизвестный предмет!", show_alert=True)

    conn.commit()
    
    # Кнопка возврата
    back_kb = InlineKeyboardBuilder()
    back_kb.button(text="⬅️ В магазин", callback_data="shop:back")
    
    await call.message.edit_text(success_text, reply_markup=back_kb.as_markup(), parse_mode="HTML")
    await call.answer("✅ Спасибо за покупку!")
    
# --- БОНУС (ИСПРАВЛЕННЫЙ) ---
@router.message(Command("bonus"))
async def get_bonus(message: types.Message):
    user_id = message.from_user.id
    now = int(time.time())
    
    cursor.execute("SELECT last_bonus, energy_drink FROM users WHERE id = ?", (user_id,))
    u = cursor.fetchone()
    last_bonus, drinks = u[0], u[1]
    
    # Если 24 часа еще не прошло (86400 сек)
    if now - last_bonus < 86400:
        kb = InlineKeyboardBuilder()
        if drinks > 0:
            kb.button(text=f"⚡️ Выпить энергетик ({drinks} шт.)", callback_data="use:energy")
        
        remains = (86400 - (now - last_bonus)) // 3600
        return await message.answer(f"⏳ Бонус будет доступен через {remains} ч.", 
                                    reply_markup=kb.as_markup())

    # Выдача бонуса
    reward = 5000
    cursor.execute("UPDATE users SET balance = balance + ?, last_bonus = ? WHERE id = ?", (reward, now, user_id))
    conn.commit()
    await message.answer(f"🎁 Вы получили ежедневный бонус: <b>{reward:,}</b> 💸")

@router.callback_query(F.data == "use:energy")
async def use_energy_logic(call: types.CallbackQuery):
    user_id = call.from_user.id
    cursor.execute("SELECT energy_drink FROM users WHERE id = ?", (user_id,))
    drinks = cursor.fetchone()[0]
    
    if drinks <= 0:
        return await call.answer("❌ Энергетики закончились!", show_alert=True)
    
    # Сбрасываем время бонуса в 0, чтобы можно было взять его сразу
    cursor.execute("UPDATE users SET energy_drink = energy_drink - 1, last_bonus = 0 WHERE id = ?", (user_id,))
    conn.commit()
    
    await call.message.edit_text("⚡️ Вы выпили энергетик! Усталость как рукой сняло. Теперь введите /bonus")
    
# --- СМЕНА ID ---
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
        cursor.execute("UPDATE users SET custom_id = ?, balance = balance - 100000 WHERE id = ?", (new_name, message.from_user.id))
        conn.commit()
        await message.reply(f"✅ Успех! Твой новый публичный ID: `{new_name}`")
    except Exception:
        await message.reply("❌ Ошибка при обновлении базы.")

# --- СПИСОК ИГР ---
@router.message(Command("games"))
async def games_list(message: types.Message):
    text = (
        "🎮 **ДОСТУПНЫЕ ИГРЫ:**\n\n"
        "🎰 `/slot [ставка]` - Игровой автомат\n"
        "💣 `/mines [ставка] [бомбы]` - Мины\n"
        "🪙 `/flip [ставка]` - Монетка\n"
        "📦 `/chests [ставка]` - Сундуки\n"
        "🎯 `/darts [ставка]` - Дартс (Дуэль)\n"
        "🎲 `/dice [ставка]` - Кости (Дуэль)\n"
        "🏀 `/basket [ставка]` - Баскет\n"
        "⚽ `/football [ставка]` - пробить пенальти\n"
        "🎫 `/lottery` - лотерея\n"
        "🚀 `/crash` - Краш (полет множителя)\n"
    )
    await message.answer(text, parse_mode="Markdown")


