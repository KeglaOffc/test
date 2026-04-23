import time
import random
import asyncio
from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter

# Импортируем базу и функции из твоего файла database.py
from database import cursor, conn, db_get_user 

router = Router()

SLOT_UPGRADE_PRICE = 10000

# --- КОНФИГУРАЦИЯ ОБОРУДОВАНИЯ ---
SHOP_ITEMS = {
    # --- CPU (Процессоры) ---
    "cpu_old": {"name": "🖥️ Старый ПК", "price": 1000, "hs": 2, "watt": 1, "type": "cpu"},
    "cpu_office": {"name": "🖥️ Офисный Core i3", "price": 2500, "hs": 5, "watt": 3, "type": "cpu"},
    "cpu_server": {"name": "🖥️ Intel Xeon Gold", "price": 7000, "hs": 18, "watt": 8, "type": "cpu"},
    "cpu_threadripper": {"name": "🖥️ AMD Threadripper", "price": 15000, "hs": 45, "watt": 15, "type": "cpu"},
    "cpu_quantum_mini": {"name": "🧪 Квантовый чип v1", "price": 50000, "hs": 150, "watt": 30, "type": "cpu"},

    # --- GPU (Видеокарты) ---
    "gpu_1050": {"name": "💻 GTX 1050 Ti", "price": 15000, "hs": 40, "watt": 10, "type": "gpu"},
    "gpu_2060": {"name": "💻 RTX 2060 Super", "price": 35000, "hs": 110, "watt": 25, "type": "gpu"},
    "gpu_3080": {"name": "💻 RTX 3080 Ti", "price": 90000, "hs": 320, "watt": 50, "type": "gpu"},
    "gpu_4090": {"name": "💻 RTX 4090 Liquid", "price": 250000, "hs": 850, "watt": 120, "type": "gpu"},
    "gpu_tesla": {"name": "💻 NVIDIA H100 (AI)", "price": 750000, "hs": 2800, "watt": 300, "type": "gpu"},
    "gpu_mining_rig": {"name": "🚜 Риг из 8x GPU", "price": 1200000, "hs": 5500, "watt": 800, "type": "gpu"},

    # --- ASIC (Спец. оборудование) ---
    "asic_s9": {"name": "📱 Antminer S9", "price": 150000, "hs": 650, "watt": 130, "type": "asic"},
    "asic_t17": {"name": "📱 Antminer T17+", "price": 300000, "hs": 1400, "watt": 250, "type": "asic"},
    "asic_s19": {"name": "📱 Antminer S19 Pro", "price": 600000, "hs": 3200, "watt": 450, "type": "asic"},
    "asic_e9": {"name": "📱 Antminer E9 Pro", "price": 1500000, "hs": 8500, "watt": 900, "type": "asic"},
    "asic_ks3": {"name": "📱 IceRiver KS3", "price": 4000000, "hs": 25000, "watt": 2000, "type": "asic"},
    "asic_dragon": {"name": "🐲 Dragon King v2", "price": 10000000, "hs": 75000, "watt": 5000, "type": "asic"},

    # --- NODE (Узлы сети) ---
    "node_light": {"name": "🔗 Light Node", "price": 500000, "hs": 2000, "watt": 100, "type": "node"},
    "node_eth": {"name": "🔗 Ethereum Node", "price": 2000000, "hs": 10000, "watt": 300, "type": "node"},
    "node_full": {"name": "🔗 Full Archive Node", "price": 8000000, "hs": 45000, "watt": 1200, "type": "node"},
    "node_cluster": {"name": "🔗 Node Cluster 24/7", "price": 25000000, "hs": 150000, "watt": 3500, "type": "node"},

    # --- CLOUD (Облачный майнинг) ---
    "cloud_trial": {"name": "☁️ Cloud Start", "price": 100000, "hs": 350, "watt": 0, "type": "cloud"},
    "cloud_basic": {"name": "☁️ Cloud Basic", "price": 500000, "hs": 1800, "watt": 0, "type": "cloud"},
    "cloud_premium": {"name": "☁️ Cloud Premium", "price": 2500000, "hs": 10000, "watt": 0, "type": "cloud"},
    "cloud_datacenter": {"name": "☁️ DataCenter Rent", "price": 50000000, "hs": 250000, "watt": 0, "type": "cloud"}
}
AUTO_ITEMS = {
    "auto_repair": {"name": "🤖 Авто-ремонт", "price": 100000, "desc": "Чинит железо при износе >80%"},
    "auto_opt": {"name": "📊 Авто-оптимизация", "price": 150000, "desc": "Держит доходность на макс. уровне"},
    "auto_collect": {"name": "💰 Авто-вывод", "price": 250000, "desc": "Сам собирает монеты каждые 4 часа"},
    
    # Мои 3 идеи:
    "overclock_shield": {"name": "🛡 Защита разгона", "price": 120000, "desc": "Убирает риск сгорания при разгоне"},
    "silent_mode": {"name": "🔇 Бесшумный режим", "price": 80000, "desc": "Снижает потребление энергии на 15%"},
    "antihack": {"name": "🔐 Анти-хакер", "price": 200000, "desc": "Защита от кражи накопленных монет (события)"}
}

# --- КОНФИГУРАЦИЯ АПГРЕЙДОВ (ТЗ 3.1) ---
UPGRADES_DATA = {
    # 🔧 МОДУЛИ ОХЛАЖДЕНИЯ
    "cooler_1": {"name": "🔧 Базовый кулер", "lvl": 1, "price": 5000, "wear_red": 0.10, "pwr_boost": 0},
    "liquid_5": {"name": "💧 Жидкостное охл.", "lvl": 5, "price": 25000, "wear_red": 0.25, "pwr_boost": 0.05},
    "freon_12": {"name": "❄️ Фреоновое охл.", "lvl": 12, "price": 100000, "wear_red": 0.40, "pwr_boost": 0.10},
    "cryo_20": {"name": "🧊 Криогенная система", "lvl": 20, "price": 500000, "wear_red": 0.60, "pwr_boost": 0.15, "watt_red": 0.10},
    "nano_28": {"name": "⚛️ Нано-радиатор", "lvl": 28, "price": 1500000, "wear_red": 0.75, "pwr_boost": 0.20},

    # ⚡ ЭНЕРГЕТИЧЕСКИЕ СИСТЕМЫ
    "bp_3": {"name": "⚡ Энергоэфф. БП", "lvl": 3, "price": 15000, "watt_red": 0.15},
    "impulse_8": {"name": "🔌 Импульсный ИБП", "lvl": 8, "price": 60000, "watt_red": 0.25, "pwr_boost": 0.05},
    "super_15": {"name": "🔋 Суперконденсаторы", "lvl": 15, "price": 200000, "watt_red": 0.35, "pwr_boost": 0.10},
    "quantum_22": {"name": "🌌 Квант. стабилизатор", "lvl": 22, "price": 800000, "watt_red": 0.45, "pwr_boost": 0.15},
    "plasma_30": {"name": "🔥 Плазм. генератор", "lvl": 30, "price": 3000000, "watt_red": 0.60, "pwr_boost": 0.25},

    # 🧠 ПРОЦЕССИНГ И ПАМЯТЬ
    "oc_chip_4": {"name": "🧠 Разогнанный чип", "lvl": 4, "price": 20000, "pwr_boost": 0.15, "wear_plus": 0.10},
    "gpu_7": {"name": "🖥 Доп. видеокарта", "lvl": 7, "price": 50000, "pwr_boost": 0.30, "watt_plus": 0.20},
    "q_proc_14": {"name": "🔮 Квантовый сопроц.", "lvl": 14, "price": 150000, "pwr_boost": 0.40, "watt_plus": 0.05},
    "ai_acc_18": {"name": "🤖 Нейро-ускоритель", "lvl": 18, "price": 400000, "pwr_boost": 0.55},
    "photon_25": {"name": "💡 Фотонный проц.", "lvl": 25, "price": 1200000, "pwr_boost": 0.80, "wear_red": 0.20},

    # 🛡️ ЗАЩИТА И СТАБИЛЬНОСТЬ
    "surge_6": {"name": "🛡 Защита от скачков", "lvl": 6, "price": 30000, "break_red": 0.40},
    "auto_10": {"name": "🕹 Авто-регулятор", "lvl": 10, "price": 80000},
    "vibro_16": {"name": "🔕 Антивибрация", "lvl": 16, "price": 250000, "wear_red": 0.20},
    "nano_coat_21": {"name": "🧪 Нано-покрытие", "lvl": 21, "price": 600000, "wear_red": 0.35},
    "field_27": {"name": "🌀 Полевой стаб.", "lvl": 27, "price": 2000000, "break_red": 1.0},

    # 🌟 ЭКСКЛЮЗИВНЫЕ МОДУЛИ
    "ai_opt_9": {"name": "🧠 ИИ-оптимизатор", "lvl": 9, "price": 75000, "pwr_boost": 0.10},
    "tele_cool_13": {"name": "🌌 Телепорт. охл.", "lvl": 13, "price": 180000, "pwr_boost": 0.30},
    "grav_23": {"name": "🪐 Грав. стабилизатор", "lvl": 23, "price": 900000, "wear_red": 0.30, "pwr_boost": 0.10},
    "portal_29": {"name": "🌀 Портал. конд.", "lvl": 29, "price": 2500000, "pwr_boost": 0.70}
}



# --- КОНФИГУРАЦИЯ СОБЫТИЙ (6.1 и 6.2) ---
NEG_EVENTS = {
    "voltage": {"name": "⚡ Скачок напряжения", "desc": "Одно устройство полностью вышло из строя!"},
    "overheat": {"name": "🌡️ Перегрев", "desc": "Мощность упала на 50% на 3 часа!"},
    "crash": {"name": "📉 Падение курса", "desc": "Доход уменьшен на 30%!"},
    "hack": {"name": "🔒 Хакерская атака", "desc": "Украдено 20% накопленных монет!"},
    "cable": {"name": "🔌 Обрыв кабеля", "desc": "Сеть пропала! Нужно чинить (простой 1 час)."},
    "police": {"name": "👮 Проверка инспекции", "desc": "Штраф за шум: -15,000 coins."},
    "rats": {"name": "🐭 Крысы", "desc": "Погрызли провода! Износ всех устройств +15%."}
}

POS_EVENTS = {
    "algo": {"name": "🎁 Обновление алгоритма", "desc": "+25% к мощности на 24 часа!"},
    "block": {"name": "💎 Находка блока", "desc": "Бонус: +10,000 coins!"},
    "boost": {"name": "🚀 Разгон от завода", "desc": "Износ временно остановлен!"},
    "service": {"name": "🛠 Бесплатный сервис", "desc": "Все устройства починены до 100%!"},
    "pump": {"name": "🐳 Памп монеты", "desc": "Курс X2! Доход удвоен!"},
    "subsidy": {"name": "⚡ Энерго-субсидия", "desc": "Бесплатное электричество на 6 часов!"}
}

# --- ФУНКЦИИ ЛОГИКИ ---
def get_farm(user_id):
    cursor.execute("SELECT * FROM mining_farms WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    if not res:
        now = int(time.time())
        cursor.execute("INSERT INTO mining_farms (user_id, last_collect) VALUES (?, ?)", (user_id, now))
        conn.commit()
        return (user_id, 0, 0, now, 3)
    return res

def get_pending(user_id):
    farm = get_farm(user_id)
    rate_per_hour = 0.5 
    passed_seconds = int(time.time()) - farm[3]
    income = (passed_seconds / 3600) * (farm[1] * rate_per_hour)
    return round(income, 2)

def recalculate_farm(user_id):
    """Пересчитывает суммарные показатели HS и WATT для фермы."""
    cursor.execute("SELECT SUM(hs), SUM(watt) FROM mining_items WHERE user_id = ?", (user_id,))
    stats = cursor.fetchone()
    total_hs = stats[0] if stats[0] else 0
    total_watt = stats[1] if stats[1] else 0
    cursor.execute("UPDATE mining_farms SET total_hs = ?, total_watt = ? WHERE user_id = ?", 
                   (total_hs, total_watt, user_id))
    conn.commit()

# --- ОБРАБОТЧИКИ ---

@router.message(Command("mining"))
@router.callback_query(F.data == "min:back") # Добавляем отлов кнопки "Назад" прямо сюда
async def mining_menu(event: types.Message | types.CallbackQuery):
    # Определяем user_id и объект сообщения в зависимости от типа события
    if isinstance(event, types.CallbackQuery):
        user_id = event.from_user.id
        message = event.message
    else:
        user_id = event.from_user.id
        message = event

    farm = get_farm(user_id)
    pending = get_pending(user_id)
    
    cursor.execute("SELECT COUNT(*) FROM mining_items WHERE user_id = ?", (user_id,))
    item_count = cursor.fetchone()[0]

    text = (
        f"⚡️ <b>МАЙНИНГ-ФЕРМА</b>\n\n"
        f"🚀 Мощность: <code>{farm[1]:.2f} H/s</code>\n"
        f"🔌 Потребление: <code>{farm[2]} W/h</code>\n"
        f"📦 Слоты: <code>{item_count}/{farm[4]}</code>\n\n"
        f"💰 Накоплено: <b>{pending:,} coins</b>"
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="💰 Собрать прибыль", callback_data="min:collect")
    kb.button(text="🛒 Магазин", callback_data="min:shop")
    kb.button(text="🔧 Мое железо", callback_data="min:manage")
    kb.button(text="⚙️ Автоматизация", callback_data="min_cat:auto")
    kb.button(text="🎮 Мини-игры", callback_data="min:minigame")
    kb.button(text="📊 Аналитика", callback_data="min:analytics")
    kb.button(text="🏆 Достижения", callback_data="min:achievements")
    kb.button(text="🤝 Пулинг", callback_data="min:pool")
    kb.button(text="🏪 Рынок", callback_data="min:market")
    kb.adjust(1, 2, 2, 2)
    
    # Если это колбэк (нажали "Назад"), редактируем текст
    if isinstance(event, types.CallbackQuery):
        try:
            await event.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
        except TelegramBadRequest:
            await event.answer()
    else:
        # Если это команда /mining, шлем новое сообщение
        await message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")

# --- СИСТЕМА УПРАВЛЕНИЯ ЖЕЛЕЗОМ (АПГРЕЙДЫ) ---

@router.callback_query(F.data == "min:manage")
async def manage_hardware(call: types.CallbackQuery):
    user_id = call.from_user.id
    if not call.message or call.message.chat.id != user_id:
        return await call.answer("❌ Это сообщение не вам!", show_alert=True)
    cursor.execute("SELECT id, name, lvl FROM mining_items WHERE user_id = ?", (user_id,))
    items = cursor.fetchall()
    
    if not items:
        return await call.answer("📭 У вас нет оборудования!", show_alert=True)
        
    kb = InlineKeyboardBuilder()
    for item in items:
        kb.button(text=f"{item[1]} [Lvl {item[2]}]", callback_data=f"min_item:{item[0]}")
    kb.button(text="⬅️ Назад", callback_data="min:back")
    kb.adjust(1)
    
    try:
        await call.message.edit_text("🔧 <b>Выберите устройство для улучшения:</b>", reply_markup=kb.as_markup(), parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
        await call.answer()

@router.callback_query(F.data.startswith("min_item:"))
async def item_details(call: types.CallbackQuery):
    item_id = int(call.data.split(":")[1])
    user_id = call.from_user.id
    if not call.message or call.message.chat.id != user_id:
        return await call.answer("❌ Это сообщение не вам!", show_alert=True)

    # ПРОВЕРКА ВЛАДЕЛЬЦА
    cursor.execute("SELECT * FROM mining_items WHERE id = ?", (item_id,))
    item = cursor.fetchone()
    
    if not item or item[1] != user_id:
        return await call.answer("❌ Это не ваше оборудование!", show_alert=True)
    
    upgrades_list = item[7] if item[7] else "Нет"
    
    text = (
        f"🛠 <b>Устройство: {item[2]}</b>\n\n"
        f"📊 Уровень: <code>{item[6]}</code>\n"
        f"⚡️ Мощность: <code>{item[3]:.2f} H/s</code>\n"
        f"🔌 Потребление: <code>{item[4]} W/h</code>\n"
        f"🛠 Состояние: <code>{item[5]}%</code>\n"
        f"📦 Улучшения: <code>{upgrades_list}</code>"
    )
    
    kb = InlineKeyboardBuilder()
    kb.button(text="🛠 Установить модули", callback_data=f"upg_list:{item_id}")
    kb.button(text=f"🆙 Поднять уровень (5000 💸)", callback_data=f"lvlup_new:{item_id}")
    kb.button(text="⬅️ Назад", callback_data="min:manage")
    kb.adjust(1)
    
    try:
        await call.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
        await call.answer()
    
@router.callback_query(F.data.startswith("min_buy_auto:"))
async def buy_auto_module(call: types.CallbackQuery):
    module_key = call.data.split(":")[1]
    user_id = call.from_user.id
    
    # ЗАЩИТА ОТ SQL INJECTION: Whitelist проверка
    valid_modules = set(AUTO_ITEMS.keys())
    if module_key not in valid_modules:
        return await call.answer("❌ Некорректный модуль!", show_alert=True)
    
    item = AUTO_ITEMS[module_key]
    u = db_get_user(user_id)
    
    # Используем параметризованный запрос
    cursor.execute("SELECT auto_repair, auto_opt, auto_collect, overclock_shield, silent_mode, antihack FROM mining_farms WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    
    if not res:
        return await call.answer("❌ Ошибка профиля!", show_alert=True)
    
    # Проверяем по индексу (зависит от порядка полей в таблице)
    module_map = {
        "auto_repair": 0,
        "auto_opt": 1,
        "auto_collect": 2,
        "overclock_shield": 3,
        "silent_mode": 4,
        "antihack": 5
    }
    
    if module_key in module_map:
        already_has = res[module_map[module_key]]
    else:
        return await call.answer("❌ Неизвестный модуль!", show_alert=True)
    
    if already_has:
        return await call.answer("✅ Этот модуль уже установлен!", show_alert=True)
    if u[0] < item['price']:
        return await call.answer("❌ Недостаточно средств!", show_alert=True)

    # Покупка (используем параметризованный запрос)
    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (item['price'], user_id))
        cursor.execute(f"UPDATE mining_farms SET {module_key} = 1 WHERE user_id = ?", (user_id,))
        conn.commit()
        
        await call.answer(f"🚀 Установлено: {item['name']}!", show_alert=True)
        await mining_shop_categories(call)
        
    except Exception as e:
        cursor.execute("ROLLBACK")
        logger.error(f"Error in buy_auto_module: {e}")
        await call.answer("❌ Ошибка при покупке!", show_alert=True)

@router.callback_query(F.data.startswith("upg_list:"))
async def show_all_upgrades(call: types.CallbackQuery):
    item_id = int(call.data.split(":")[1])
    cursor.execute("SELECT name, lvl, upgrades FROM mining_items WHERE id = ?", (item_id,))
    item = cursor.fetchone()
    installed = item[2].split(",") if item[2] else []
    
    text = f"🛠 <b>Апгрейды для {item[0]}</b>\n<i>Выберите модуль для установки:</i>"
    kb = InlineKeyboardBuilder()
    
    for key, data in UPGRADES_DATA.items():
        if key in installed:
            kb.button(text=f"✅ {data['name']}", callback_data="none")
        else:
            if item[1] >= data['lvl']:
                kb.button(text=f"🛒 {data['name']} ({data['price']:,} 💸)", callback_data=f"upg_buy_new:{item_id}:{key}")
            else:
                kb.button(text=f"🔒 Нужен {data['lvl']} ур.", callback_data="none")
    
    kb.button(text="⬅️ Назад", callback_data=f"min_item:{item_id}")
    kb.adjust(1)
    try:
        await call.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
        await call.answer()

@router.callback_query(F.data.startswith("upg_buy_new:"))
async def buy_upgrade_final(call: types.CallbackQuery):
    data = call.data.split(":")
    item_id = int(data[1])
    upg_key = data[2]
    user_id = call.from_user.id
    
    # 1. ПРОВЕРКА ВЛАДЕЛЬЦА (Безопасность)
    cursor.execute("SELECT user_id, upgrades FROM mining_items WHERE id = ?", (item_id,))
    res = cursor.fetchone()
    if not res or res[0] != user_id:
        return await call.answer("❌ Это не ваше оборудование!", show_alert=True)
    
    current_upgrades = res[1] if res[1] else ""

    # 2. ПОЛУЧАЕМ ДАННЫЕ АПГРЕЙДА (Сначала объявляем, потом используем)
    upg = UPGRADES_DATA.get(upg_key)
    if not upg:
        return await call.answer("❌ Апгрейд не найден!")

    # 3. ПРОВЕРКА БАЛАНСА
    u = db_get_user(user_id) # Получаем баланс из БД
    if u[0] < upg['price']:
        return await call.answer(f"❌ Нужно {upg['price']:,} 💸", show_alert=True)
    
    # 4. ПРОВЕРКА: Не куплен ли уже этот модуль?
    if upg_key in current_upgrades.split(','):
        return await call.answer("✅ Этот модуль уже установлен!", show_alert=True)

    # 5. РАСЧЕТ ЭФФЕКТОВ
    new_upgrades = f"{current_upgrades},{upg_key}" if current_upgrades else upg_key
    pwr_mul = 1 + upg.get("pwr_boost", 0)
    # Считаем изменение потребления (снижение или увеличение)
    watt_mul = 1 - upg.get("watt_red", 0) + upg.get("watt_plus", 0)
    
    # 6. ОБНОВЛЕНИЕ БАЗЫ ДАННЫХ
    try:
        # Списываем деньги
        cursor.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (upg['price'], user_id))
        
        # Улучшаем предмет
        cursor.execute("""
            UPDATE mining_items 
            SET hs = hs * ?, watt = watt * ?, upgrades = ? 
            WHERE id = ?
        """, (pwr_mul, watt_mul, new_upgrades, item_id))
        
        conn.commit()
        recalculate_farm(user_id) # Пересчитываем общую мощь фермы
        
        await call.answer(f"✅ Установлено: {upg['name']}")
        
        # 7. ОБНОВЛЯЕМ МЕНЮ (чтобы сразу появилась галочка ✅)
        await show_all_upgrades(call) 
        
    except Exception as e:
        conn.rollback()
        await call.answer("❌ Ошибка при покупке")
        print(f"Error in buy_upgrade: {e}")

@router.callback_query(F.data.startswith("lvlup_"))
async def process_lvlup(call: types.CallbackQuery):
    item_id = int(call.data.split(":")[1])
    user_id = call.from_user.id
    cost = 5000
    
    u = db_get_user(user_id)
    if u[0] < cost:
        return await call.answer("❌ Нужно 5000 coins!", show_alert=True)
        
    cursor.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (cost, user_id))
    # Уровень дает +10% к базовому хешрейту
    cursor.execute("UPDATE mining_items SET lvl = lvl + 1, hs = hs * 1.1 WHERE id = ?", (item_id,))
    conn.commit()
    
    try:
        # Сначала отвечаем на запрос, чтобы у пользователя не крутились "часики"
        await call.answer("✅ Уровень повышен!")
        # А потом уже пробуем обновить меню
        await item_details(call)
    except TelegramRetryAfter as e:
        # Если словили флуд-лимит, просто уведомляем пользователя
        await call.answer(f"⚠️ Слишком часто! Подождите {e.retry_after} сек.", show_alert=True)
    except TelegramBadRequest as e:
        if "query is too old" in str(e):
            # Если кнопка старая, просто отправляем новое сообщение вместо редактирования
            await call.message.answer("Меню устарело. Откройте его заново через ферму.")
    

    
# --- ФУНКЦИЯ ГЕНЕРАЦИИ СОБЫТИЯ ---
async def apply_random_event(user_id, current_pending):
    # Шанс 20% для теста (потом можешь поставить 10-15%)
    if random.randint(1, 100) > 30:
        return None, current_pending

    # Выбираем тип: Плохое (60%) или Хорошее (40%)
    is_bad = random.randint(1, 100) <= 60
    
    if is_bad:
        event_key = random.choice(list(NEG_EVENTS.keys()))
        event = NEG_EVENTS[event_key]
    else:
        event_key = random.choice(list(POS_EVENTS.keys()))
        event = POS_EVENTS[event_key]
    
    new_pending = current_pending

    # --- ЛОГИКА КАЖДОГО СОБЫТИЯ ---
    if event_key == "voltage":
        # Ломаем одну случайную вещь
        cursor.execute("UPDATE mining_items SET wear = 0 WHERE user_id = ? ORDER BY RANDOM() LIMIT 1", (user_id,))
    elif event_key == "crash":
        new_pending *= 0.7 # -30%
    elif event_key == "hack":
        # Проверка защиты Анти-хакер
        cursor.execute("SELECT antihack FROM mining_farms WHERE user_id = ?", (user_id,))
        res = cursor.fetchone()
        if res and res[0] == 1:
            return "🛡 <b>Анти-хакер</b> отразил атаку хакеров!", current_pending
        new_pending *= 0.8 # -20%
    elif event_key == "police":
        cursor.execute("UPDATE users SET balance = balance - 15000 WHERE id = ?", (user_id,))
    elif event_key == "rats":
        cursor.execute("UPDATE mining_items SET wear = wear - 15 WHERE user_id = ?", (user_id,))
    elif event_key == "block":
        new_pending += 10000
    elif event_key == "service":
        cursor.execute("UPDATE mining_items SET wear = 100 WHERE user_id = ?", (user_id,))
    elif event_key == "pump":
        new_pending *= 2

    conn.commit()
    return f"🎲 <b>СОБЫТИЕ: {event['name']}</b>\n<i>{event['desc']}</i>", new_pending


# --- МАГАЗИН (КАТЕГОРИИ) ---

@router.callback_query(F.data == "min:shop")
async def mining_shop_categories(call: types.CallbackQuery):
    user_id = call.from_user.id
    if not call.message or call.message.chat.id != user_id:
        return await call.answer("❌ Это сообщение не вам!", show_alert=True)
    farm = get_farm(user_id)
    kb = InlineKeyboardBuilder()
    kb.button(text="🖥️ CPU", callback_data="min_cat:cpu")
    kb.button(text="💻 GPU", callback_data="min_cat:gpu")
    kb.button(text="📱 ASIC", callback_data="min_cat:asic")
    kb.button(text="🔗 Ноды", callback_data="min_cat:node")
    kb.button(text="☁️ Облако", callback_data="min_cat:cloud")
    kb.button(text=f"📦 Купить слот ({SLOT_UPGRADE_PRICE:,} 💸)", callback_data="min:upgrade_slots")
    kb.button(text="⬅️ Назад", callback_data="min:back")
    kb.adjust(2, 2, 1, 1, 1)
    
    try:
        await call.message.edit_text(
            f"🛒 <b>МАГАЗИН</b>\nЗанято слотов: <code>{farm[4]}</code>\nВыберите категорию:", 
            reply_markup=kb.as_markup(), parse_mode="HTML"
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
        await call.answer()

@router.callback_query(F.data.startswith("min_cat:"))
async def show_category_items(call: types.CallbackQuery):
    user_id = call.from_user.id
    if not call.message or call.message.chat.id != user_id:
        return await call.answer("❌ Это сообщение не вам!", show_alert=True)
    category = call.data.split(":")[1]
    kb = InlineKeyboardBuilder()
    
    # ЛОГИКА ДЛЯ АВТОМАТИЗАЦИИ
    if category == "auto":
        for key, item in AUTO_ITEMS.items():
            kb.button(text=f"{item['name']} | {item['price']:,} 💸", callback_data=f"min_buy_auto:{key}")
        text = "⚙️ <b>КАТЕГОРИЯ: АВТОМАТИЗАЦИЯ</b>\n<i>Улучшения для всей фермы:</i>"
    
    # ЛОГИКА ДЛЯ ОБЫЧНОГО ЖЕЛЕЗА
    else:
        for key, item in SHOP_ITEMS.items():
            if item['type'] == category:
                kb.button(text=f"{item['name']} | {item['price']:,} 💸", callback_data=f"min_buy:{key}")
        
        desc = {
            "cpu": "Бюджетные решения для старта.",
            "gpu": "Оптимальный баланс цены и мощности.",
            "asic": "Максимальный хешрейт для профи.",
            "node": "Высокая цена, высокая доходность.",
            "cloud": "Нулевое потребление энергии!"
        }
        text = f"🛠 <b>КАТЕГОРИЯ: {category.upper()}</b>\n{desc.get(category, '')}"
    
    kb.button(text="⬅️ К категориям", callback_data="min:shop")
    kb.adjust(1)
    try:
        await call.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
        await call.answer()

@router.callback_query(F.data == "min:upgrade_slots")
async def process_upgrade_slots(call: types.CallbackQuery):
    user_id = call.from_user.id
    if not call.message or call.message.chat.id != user_id:
        return await call.answer("❌ Это сообщение не вам!", show_alert=True)
    u = db_get_user(user_id)
    farm = get_farm(user_id)
    max_slots = 100 if u[6] == 'vip' else 50
    
    if farm[4] >= max_slots:
        return await call.answer(f"🚫 Максимум {max_slots} слотов!", show_alert=True)
    if u[0] < SLOT_UPGRADE_PRICE:
        return await call.answer(f"❌ Нужно {SLOT_UPGRADE_PRICE:,} coins!", show_alert=True)
        
    cursor.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (SLOT_UPGRADE_PRICE, user_id))
    cursor.execute("UPDATE mining_farms SET slots = slots + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    await call.answer("✅ Слот куплен!", show_alert=True)
    await mining_shop_categories(call)

@router.callback_query(F.data.startswith("min_buy:"))
async def process_mining_buy(call: types.CallbackQuery):
    item_key = call.data.split(":")[1]
    item = SHOP_ITEMS[item_key]
    user_id = call.from_user.id
    u = db_get_user(user_id)
    farm = get_farm(user_id)
    
    cursor.execute("SELECT COUNT(*) FROM mining_items WHERE user_id = ?", (user_id,))
    if cursor.fetchone()[0] >= farm[4]:
        return await call.answer("📦 Нет свободных слотов!", show_alert=True)
    if u[0] < item['price']:
        return await call.answer("❌ Недостаточно средств!", show_alert=True)

    cursor.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (item['price'], user_id))
    cursor.execute("INSERT INTO mining_items (user_id, name, hs, watt, wear, lvl) VALUES (?, ?, ?, ?, 100.0, 1)", 
                   (user_id, item['name'], item['hs'], item['watt']))
    conn.commit()
    recalculate_farm(user_id)



@router.callback_query(F.data == "min:collect")
async def process_collect(call: types.CallbackQuery):
    user_id = call.from_user.id
    if not call.message or call.message.chat.id != user_id:
        return await call.answer("❌ Это сообщение не вам!", show_alert=True)
    pending = get_pending(user_id)
    
    if pending < 0.1:
        return await call.answer("💰 Копить еще рано!", show_alert=True)

    # ВАЖНО: Вызываем функцию ивентов
    event_msg, final_pending = await apply_random_event(user_id, pending)

    # Проверка на авто-ремонт (если куплен)
    cursor.execute("SELECT auto_repair FROM mining_farms WHERE user_id = ?", (user_id,))
    has_auto = cursor.fetchone()
    repair_note = ""
    if has_auto and has_auto[0] == 1:
        cursor.execute("UPDATE mining_items SET wear = 100 WHERE user_id = ?", (user_id,))
        repair_note = "\n🤖 <i>Авто-ремонт применен!</i>"

    # Начисляем деньги на баланс
    cursor.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (final_pending, user_id))
    cursor.execute("UPDATE mining_farms SET last_collect = ? WHERE user_id = ?", (int(time.time()), user_id))
    conn.commit()
    
    result_text = (
        f"✅ <b>Прибыль собрана!</b>\n"
        f"💰 Получено: <code>{final_pending:,.2f}</code> coins.{repair_note}"
    )
    
    if event_msg:
        result_text += f"\n\n{event_msg}"
    
    try:
        await call.message.edit_text(result_text, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
        await call.answer()
    
    # Возврат в меню через 5 секунд
    await asyncio.sleep(5)
    await mining_menu(call.message)



# ============================================================================
# КРУТЫЕ ФУНКЦИИ #1-5: МИНИ-ИГРЫ, АНАЛИТИКА, ДОСТИЖЕНИЯ, ПУЛИНГ, РЫНОК
# ============================================================================

MINI_GAMES = {
    "ore_dig": {"name": "⛏️ Копание руды", "chance": 0.6, "reward": 5000},
    "ore_sell": {"name": "💎 Продажа руды", "chance": 0.7, "reward": 3000},
    "ore_craft": {"name": "🔨 Переплавка", "chance": 0.5, "reward": 8000},
}

@router.callback_query(F.data == "min:minigame")
async def minigame_menu(call: types.CallbackQuery):
    kb = InlineKeyboardBuilder()
    for key, game in MINI_GAMES.items():
        kb.button(text=f"{game['name']} | +{game['reward']:,}", callback_data=f"play:{key}")
    kb.button(text="⬅️ Назад", callback_data="min:back")
    kb.adjust(1)
    try:
        await call.message.edit_text("🎮 <b>МИНИ-ИГРЫ ШАХТЫ</b>", reply_markup=kb.as_markup(), parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
        await call.answer()

@router.callback_query(F.data.startswith("play:"))
async def play_minigame(call: types.CallbackQuery):
    game_key = call.data.split(":")[1]
    user_id = call.from_user.id
    if game_key not in MINI_GAMES: return
    game = MINI_GAMES[game_key]
    if random.random() < game["chance"]:
        cursor.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (game["reward"], user_id))
        conn.commit()
        text = f"✅ ВЫИГРЫШ! +{game['reward']:,}"
    else:
        text = "❌ ПРОИГРЫШ!"
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 Ещё", callback_data=f"play:{game_key}")
    kb.button(text="⬅️ К играм", callback_data="min:minigame")
    kb.adjust(1)
    try:
        await call.message.edit_text(f"{game['name']}\n{text}", reply_markup=kb.as_markup())
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
        await call.answer()

@router.callback_query(F.data == "min:analytics")
async def show_analytics(call: types.CallbackQuery):
    user_id = call.from_user.id
    farm = get_farm(user_id)
    pending = get_pending(user_id)
    cursor.execute("SELECT COUNT(*), AVG(lvl), AVG(wear) FROM mining_items WHERE user_id = ?", (user_id,))
    count, avg_lvl, avg_wear = cursor.fetchone()
    count, avg_lvl, avg_wear = count or 0, avg_lvl or 0, avg_wear or 0
    rate_h = 0.5
    income_h = farm[1] * rate_h
    income_d = income_h * 24
    income_w = income_d * 7
    eff = (income_h / max(farm[2], 1) * 100) if farm[2] > 0 else 0
    text = f"📊 АНАЛИТИКА\n\nУстройств: {int(count)} | Уровень: {avg_lvl:.1f}\nИзнос: {avg_wear:.1f}%\n\n⚡ Мощность: {farm[1]:.2f} H/s | Потребление: {farm[2]} W\nКПД: {eff:.1f}%\n\n💰 Час {income_h:,.0f} | День {income_d:,.0f} | Неделя {income_w:,.0f}"
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data="min:back")
    kb.adjust(1)
    try:
        await call.message.edit_text(text, reply_markup=kb.as_markup())
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
        await call.answer()

@router.callback_query(F.data == "min:achievements")
async def show_achievements(call: types.CallbackQuery):
    user_id = call.from_user.id
    u = db_get_user(user_id)
    cursor.execute("SELECT COALESCE(SUM(hs), 0) FROM mining_items WHERE user_id = ?", (user_id,))
    total_hs = cursor.fetchone()[0] or 0
    text = "🏆 ДОСТИЖЕНИЯ\n\n"
    if total_hs >= 100000:
        text += "✅ Мега-энергия (100k H/s)\n"
    else:
        text += f"🔒 Мега-энергия ({int(total_hs)}/100k)\n"
    if u[0] >= 1000000:
        text += "✅ Миллиардер (1М coins)"
    else:
        text += f"🔒 Миллиардер ({u[0]:,}/1М)"
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data="min:back")
    kb.adjust(1)
    try:
        await call.message.edit_text(text, reply_markup=kb.as_markup())
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
        await call.answer()

@router.callback_query(F.data == "min:pool")
async def show_pool(call: types.CallbackQuery):
    user_id = call.from_user.id
    farm = get_farm(user_id)
    cursor.execute("SELECT COUNT(DISTINCT user_id) FROM mining_farms WHERE total_hs > 0")
    farmers = cursor.fetchone()[0] or 1
    pool_hs = farm[1] * 1.15
    text = f"🤝 ПУЛИНГ\n\nФермеров: {farmers}\nТвоя мощность: {farm[1]:.2f} H/s\nС бонусом: {pool_hs:.2f} H/s (+15%)\n\nКомиссия: 5%"
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data="min:back")
    kb.adjust(1)
    try:
        await call.message.edit_text(text, reply_markup=kb.as_markup())
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
        await call.answer()

@router.callback_query(F.data == "min:market")
async def equipment_market(call: types.CallbackQuery):
    kb = InlineKeyboardBuilder()
    kb.button(text="💳 Продать", callback_data="min:sell_equip")
    kb.button(text="📈 Курсы", callback_data="min:market_rates")
    kb.button(text="⬅️ Назад", callback_data="min:back")
    kb.adjust(1)
    text = "🏪 РЫНОК ОБОРУДОВАНИЯ\nПокупай (x1.2) и продавай (x0.7)"
    try:
        await call.message.edit_text(text, reply_markup=kb.as_markup())
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
        await call.answer()

@router.callback_query(F.data == "min:sell_equip")
async def sell_equipment(call: types.CallbackQuery):
    user_id = call.from_user.id
    cursor.execute("SELECT id, name, hs FROM mining_items WHERE user_id = ? ORDER BY hs DESC", (user_id,))
    items = cursor.fetchall()
    if not items:
        return await call.answer("❌ Нет оборудования!", show_alert=True)
    kb = InlineKeyboardBuilder()
    for item_id, name, hs in items:
        price = int(hs * 50 * 0.7)
        kb.button(text=f"{name} ({price:,})", callback_data=f"sell:{item_id}:{price}")
    kb.button(text="⬅️ Назад", callback_data="min:market")
    kb.adjust(1)
    try:
        await call.message.edit_text("ВЫБЕРИ ОБОРУДОВАНИЕ:", reply_markup=kb.as_markup())
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
        await call.answer()

@router.callback_query(F.data.startswith("sell:"))
async def confirm_sell(call: types.CallbackQuery):
    data = call.data.split(":")
    item_id, price = int(data[1]), int(data[2])
    user_id = call.from_user.id
    cursor.execute("DELETE FROM mining_items WHERE id = ? AND user_id = ?", (item_id, user_id))
    cursor.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (price, user_id))
    conn.commit()
    recalculate_farm(user_id)
    await call.answer(f"✅ Продано за {price:,}!", show_alert=True)
    await equipment_market(call)

@router.callback_query(F.data == "min:market_rates")
async def show_rates(call: types.CallbackQuery):
    text = "📈 КУРСЫ\n\n"
    for key, item in list(SHOP_ITEMS.items())[:5]:
        text += f"{item['name']}: {int(item['price']*1.2):,} | {int(item['price']*0.7):,}\n"
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ К рынку", callback_data="min:market")
    kb.adjust(1)
    try:
        await call.message.edit_text(text, reply_markup=kb.as_markup())
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
        await call.answer()