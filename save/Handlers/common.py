import asyncio
import time
import random  # Обязательно добавляем этот импорт
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database import db_get_user, db_update_stats, get_real_id, cursor, conn

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
        "📖 **ИНФОРМАЦИЯ И ПРАВИЛА**\n\n"
        "🎰 **СЛОТЫ:** 777 = x100 | 3 в ряд = x15 | 2 в ряд = x2\n"
        "💣 **МИНЫ:** Чем больше 🍀 открыто, тем выше множитель\n"
        "📦 **СУНДУКИ:** Один из трех дает x3, второй x0.5, третий 0\n\n"
        
        "📜 **ВСЕ КОМАНДЫ БОТА:**\n"
        "🔹 `/start` — Показать профиль и баланс\n"
        "🔹 `/shop` — Магазин бустов и улучшений\n"
        "🔹 `/bonus` — Получить ежедневный бонус\n"
        "🔹 `/top` — Посмотреть таблицу лидеров\n"
        "🔹 `/qhelp` — Вызвать это меню\n\n"

        "🎮 **ИГРОВЫЕ КОМАНДЫ:**\n"
        "🔹 `/slot [ставка]` — Игровой автомат\n"
        "🔹 `/mines [ставка] [бомбы]` — Игра в мины\n"
        "🔹 `/flip [ставка]` — Орел или решка\n"
        "🔹 `/chests [ставка]` — Открыть сундуки\n"
        "🔹 `/dice [ставка]` — Кости с ботом\n"
        "🔹 `/darts [ставка]` — Игра в дартс\n\n"
        "🔹 `/football [ставка]` — Пробить пенальти (x2)\n"
        "🔹 `/basket [ставка]` — Бросок в кольцо (x2)\n"
        "🔹 `/lottery` — Мгновенная лотерея\n"
        
        "⚙️ **ДОПОЛНИТЕЛЬНО:**\n"
        "🔹 `/newid [имя]` — Сменить ID на слово (100k)\n"
        "🔹 `/admin` — Панель управления (только админам)"
    )
    await message.answer(help_text, parse_mode="Markdown")

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    
    # 1. Получаем данные пользователя в виде словаря для удобства
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        # Если пользователя нет, можно вызвать функцию регистрации или check_user
        return await message.answer("❌ Профиль не найден. Начните с /start")

    columns = [description[0] for description in cursor.description]
    u = dict(zip(columns, row))

    # 2. Расчеты и логика предметов
    profit = u['total_wins'] - u['total_bets']
    now = int(time.time())
    
    # Аура (Префикс перед именем)
    aura_prefix = "✨ " if u.get('aura_active') == 1 else ""
    
    # VIP Статус
    vip_status = "👑 *VIP Пользователь*" if u['rigged_mode'] == 'vip' else "👤 *Игрок*"
    vip_icon = "👑 " if u['rigged_mode'] == 'vip' else ""

    # Буст X2
    if u['boost_end'] > now:
        boost_time = (u['boost_end'] - now) // 3600
        boost_text = f"🚀 Активен (еще {boost_time} ч.)"
    else:
        boost_text = "❌ Не активен"

    # Лимиты и Невидимка
    limit_text = "♾ Безлимит" if u['luck_end'] == 777 else "Standard (1M)"
    incognito_status = "👁‍🗨 Скрыт" if u.get('incognito_mode') == 1 else "🌍 Публичный"

    # Сейф
    safe_lvl = u.get('safe_box_level', 0)
    safe_info = f" {safe_lvl} ур." if safe_lvl > 0 else " ❌"

    # 3. Формирование текста профиля
    text = (
        f"———————————————————\n"
        f"🏛 **ЛИЧНЫЙ КАБИНЕТ QCASINO**\n"
        f"———————————————————\n"
        f"┃ {vip_status}\n"
        f"┃ 🎫 Ник: {aura_prefix}{vip_icon}`{u['custom_id'] or u['id']}`\n"
        f"┃ 🔢 ID: `{user_id}`\n"
        f"┃ 🕵️ Статус: `{incognito_status}`\n"
        f"┃\n"
        f"┃ 💰 **ФИНАНСЫ:**\n"
        f"┃ 💳 Баланс: `{u['balance']:,}` 💎\n"
        f"┃ 📈 Прибыль: `{profit:,}` 💎\n"
        f"┃ ⚖️ Лимит: `{limit_text}`\n"
        f"┃ 🛡 Сейф: `{safe_info}`\n"
        f"┃\n"
        f"┃ 📊 **СТАТИСТИКА:**\n"
        f"┃ 🎮 Всего игр: `{u['games_played']}`\n"
        f"┃ 🍀 Удача: `{u['rig_prob']}%`\n"
        f"┃ ⚡️ X2 Буст: `{boost_text}`\n"
        f"┃\n"
        f"┃ 🎒 **ИНВЕНТАРЬ:**\n"
        f"┃ 🛡 Щиты: `{u.get('mine_shield', 0)}` | 🔍 Сканеры: `{u.get('mine_scan', 0)}`\n"
        f"┃ 🔄 Рэроллы: `{u.get('rerolls', 0)}` | ⚡️ Энергетики: `{u.get('energy_drink', 0)}`\n"
        f"┃ 🎟 Золотой билет: `{'✅ Есть' if u.get('gold_ticket') else '❌ Нет'}`\n"
        f"———————————————————\n"
        f"🆘 *Помощь по командам:* `/help`"
    )
    
    await message.reply(text, parse_mode="Markdown")

@router.message(Command("shop"))
@router.callback_query(F.data == "shop:back")
async def shop_cmd(event: types.Message | types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    
    # Старые предметы
    builder.button(text="🔥 X2 Буст 24ч (100к)", callback_data="buy:boost_x2")
    builder.button(text="👑 Смена ID (100к)", callback_data="buy:id_change")
    builder.button(text="🍀 Клевер (250к)", callback_data="buy:clover")
    builder.button(text="💎 VIP Статус (500к)", callback_data="buy:vip")
    builder.button(text="📈 Безлимит (200к)", callback_data="buy:no_limit")
    
    # --- НОВЫЕ 10 ПРЕДМЕТОВ ---
    # Для MINES (Сапер)
    builder.button(text="🛡 Саперный щит (50к)", callback_data="buy:mine_shield") # Защита от 1 мины
    builder.button(text="🔍 Сканер мин (80к)", callback_data="buy:mine_scan") # Показывает 1 мину
    
    # Для казино / азарта
    builder.button(text="🔄 Переброс кубика (40к)", callback_data="buy:dice_reroll")
    builder.button(text="🃏 Страховка ставки (150к)", callback_data="buy:bet_insure") # Возврат 50% при проигрыше
    
    # Накопительные / Экономика
    builder.button(text="💰 Кэшбэк 5% (300к)", callback_data="buy:cashback") # Возврат с каждой ставки
    builder.button(text="🏦 Сейф (400к)", callback_data="buy:safe_box") # Защита части баланса от обнуления
    
    # Геймплейные
    builder.button(text="🎟 Золотой билет (120к)", callback_data="buy:gold_ticket") # Шанс в лотерее x3
    builder.button(text="⚡️ Энергетик (60к)", callback_data="buy:energy_drink") # Сброс КД на бонус
    
    # Социальные / Статус
    builder.button(text="✨ Аура героя (200к)", callback_data="buy:aura") # Красивый префикс в профиле
    builder.button(text="🕵️ Невидимка (180к)", callback_data="buy:incognito") # Скрывает в топе богачей
    
    builder.adjust(1, 1, 1, 1, 1, 2, 2, 2, 2, 2)
    
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

    columns = [description[0] for description in cursor.description]
    u = dict(zip(columns, row))
    item = call.data.split(":")[1]
    
    prices = {
        "boost_x2": 100000, "id_change": 100000, "clover": 250000, "vip": 500000, "no_limit": 200000,
        "mine_shield": 50000, "mine_scan": 80000, "dice_reroll": 40000, "bet_insure": 150000,
        "cashback": 300000, "safe_box": 400000, "gold_ticket": 120000, "energy_drink": 60000,
        "aura": 200000, "incognito": 180000
    }
    
    price = prices.get(item, 0)
    if u.get('balance', 0) < price:
        return await call.answer(f"❌ Недостаточно средств! Нужно {price:,} 💸", show_alert=True)

    # Логика покупки новых предметов (обновляем соответствующие колонки)
    # ПРИМЕЧАНИЕ: Тебе нужно добавить эти колонки в БД (через ALTER TABLE)
    
    success_text = "✅ Покупка совершена!"
    
    if item == "mine_shield":
        cursor.execute("UPDATE users SET balance = balance - ?, mine_shield = mine_shield + 1 WHERE id = ?", (price, user_id))
        success_text = "✅ Куплен <b>Саперный щит</b>! Он защитит вас при взрыве на мине."
        
    elif item == "mine_scan":
        cursor.execute("UPDATE users SET balance = balance - ?, mine_scan = mine_scan + 3 WHERE id = ?", (price, user_id))
        success_text = "✅ Куплено 3 <b>Сканера мин</b>! Используйте их в игре Mines."

    elif item == "dice_reroll":
        cursor.execute("UPDATE users SET balance = balance - ?, rerolls = rerolls + 1 WHERE id = ?", (price, user_id))
        success_text = "✅ Куплен <b>Переброс кубика</b>!"

    elif item == "cashback":
        if u.get('has_cashback'): return await call.answer("У вас уже есть кэшбэк!", show_alert=True)
        cursor.execute("UPDATE users SET balance = balance - ?, has_cashback = 1 WHERE id = ?", (price, user_id))
        success_text = "✅ Теперь вы будете получать 5% обратно с каждой ставки!"

    # ... логика для остальных предметов по аналогии ...
    # Для статусных вещей:
    elif item == "aura":
        cursor.execute("UPDATE users SET balance = balance - ?, aura_active = 1 WHERE id = ?", (price, user_id))
        success_text = "✅ Ваша <b>Аура</b> теперь сияет в профиле ✨"

    else:
        # Тут обрабатываются старые предметы (boost_x2, vip и т.д. — оставь свой старый код)
        pass

    conn.commit()
    
    # Кнопка возврата, чтобы не слать новое сообщение
    back_kb = InlineKeyboardBuilder()
    back_kb.button(text="⬅️ В магазин", callback_data="shop:back")
    
    await call.message.edit_text(success_text, reply_markup=back_kb.as_markup(), parse_mode="HTML")
    await call.answer()
    
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
        "⚽ `/football [ставка]` - пробить пенальти"
        "🎫 `/lottery` - лотерея\n"
    )
    await message.answer(text, parse_mode="Markdown")