import datetime
import time
import random
import logging
import asyncio
import sqlite3
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database import db_get_user, db_update_stats, cursor, conn, DB_FILE
from Handlers.common import check_user
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest



# Настройка логирования для отслеживания действий в лотереях
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- СОСТОЯНИЯ ДЛЯ МАШИНЫ СОСТОЯНИЙ (FSM) ---
class CreateLottery(StatesGroup):
    """Класс состояний для пошагового создания пользовательской лотереи."""
    title = State()          # Название розыгрыша
    prize_pool = State()     # Сумма выигрыша
    ticket_price = State()   # Цена одного билета
    max_tickets = State()    # Общее количество билетов
    confirm = State()        # Подтверждение и оплата

# --- КОНСТАНТЫ И НАСТРОЙКИ СИСТЕМЫ ---
HOURLY_PRICE = 1000         # Цена билета в часовой лотерее (возросла с 500)
HOURLY_LIMIT = 10           # Лимит билетов в час для одного игрока
WEEKLY_PRICE = 7000         # Цена билета в недельной лотерее (возросла с 5000)
WEEKLY_LIMIT = 5            # Лимит билетов в неделю
MEGA_PRICE = 150000         # МЕГА-ЛОТЕРЕЯ высоких ставок (НОВО!)
MEGA_LIMIT = 3              # Лимит мега-билетов в неделю
PRO_PRICE = 150000          # Цена в Про-лотерее (возросла с 100k)
PRO_LIMIT = 2               # Лимит билетов в сутки
COMBO_DISCOUNT = 0.15       # Скидка за комбо (3+ билета = -15%)
SYSTEM_FEE = 0.05           # Комиссия системы (5%)

router = Router()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ИНТЕРФЕЙСА ---

def get_main_kb():
    """Генерация главного меню лотерейного центра (УПРОЩЕНО)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🕐 Часовая (1000)", callback_data="view_hourly")
    builder.button(text="📅 Недельная (7000)", callback_data="view_weekly")
    builder.button(text="🐳 МЕГА (150k)", callback_data="view_mega")
    builder.button(text="🎪 User-лотереи", callback_data="view_user_lotteries")
    builder.button(text="🏠 В профиль", callback_data="back_to_profile")
    builder.adjust(2, 2, 1)
    return builder.as_markup()

# --- ОБРАБОТЧИКИ ОСНОВНЫХ КОМАНД ---

@router.message(Command("lottery"))
async def lottery_menu(message: types.Message):
    """Точка входа в меню лотерей (НОВОЕ: упрощенное)."""
    if not await check_user(message): 
        return
    
    logger.info(f"User {message.from_user.id} opened lottery menu")
    text = (
        "🎰 <b>ГЛАВНОЕ МЕНЮ ЛОТЕРЕЙ</b>\n\n"
        "<b>📢 ТРИ ТИПА ВЫИГЫШЕЙ:</b>\n"
        "🕐 <b>Часовая</b> - джекпот каждый час (1000 💎)\n"
        "📅 <b>Недельная</b> - НГ в воскресенье (7000 💎)\n"
        "🐳 <b>МЕГА</b> - ВСЕ ИДЕТ ОДНОМУ! (150k 💎) ⭐\n\n"
        "💝 <b>КОМБО СКИДКИ:</b>\n"
        "Купи 3+ билета одной лотереи → скидка 15%!\n\n"
        "Твой выбор ниже 👇"
    )
    await message.answer(text, reply_markup=get_main_kb(), parse_mode="HTML")

@router.callback_query(F.data == "lottery_main")
async def lottery_main_callback(call: types.CallbackQuery, state: FSMContext):
    """Возврат в главное меню из любого раздела."""
    await state.clear()
    await call.message.edit_text("🎰 <b>ГЛАВНОЕ МЕНЮ ЛОТЕРЕЙ</b>", reply_markup=get_main_kb(), parse_mode="HTML")

@router.callback_query(F.data == "back_to_profile")
async def back_to_profile(call: types.CallbackQuery):
    """Удаление сообщения меню и возврат в главное меню бота."""
    await call.answer()
    try:
        await call.message.delete()
    except Exception as e:
        logger.error(f"Error deleting message: {e}")

# --- ЛОГИКА ЧАСОВОЙ ЛОТЕРЕИ ---

@router.message(Command("lothourly"))
async def fast_hourly(message: types.Message):
    await show_hourly(message)

@router.callback_query(F.data == "view_hourly")
async def cb_view_hourly(call: types.CallbackQuery):
    await show_hourly(call)

async def show_hourly(event):
    """Отображение состояния часовой лотереи с таймером."""
    now = datetime.datetime.now()
    next_hour = (now + datetime.timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    wait_time = next_hour - now
    minutes, seconds = divmod(wait_time.seconds, 60)

    cursor.execute("SELECT draw_id, prize_pool FROM hourly_state ORDER BY draw_id DESC LIMIT 1")
    res = cursor.fetchone()
    if res:
        draw_id, pool = res
    else:
        draw_id, pool = 1, 100000
        # Создаем первую запись если её нет
        try:
            cursor.execute("INSERT INTO hourly_state (draw_id, prize_pool) VALUES (1, 100000)")
            conn.commit()
        except Exception as e:
            logger.error(f"Error creating hourly_state: {e}")
    
    user_id = event.from_user.id
    start_of_hour = int(time.time()) // 3600 * 3600
    cursor.execute("SELECT COUNT(*) FROM lottery_tickets WHERE user_id = ? AND lottery_type = 'hourly' AND buy_time > ?", (user_id, start_of_hour))
    my_tickets = cursor.fetchone()[0]

    text = (
        f"🕐 <b>ЧАСОВАЯ ЛОТЕРЕЯ #{draw_id}</b>\n\n"
        f"⏳ До розыгрыша: <code>{minutes:02d}:{seconds:02d}</code>\n"
        f"💰 Текущий джекпот: <code>{pool:,}</code> 💎\n"
        f"🎫 Ваших билетов: <code>{my_tickets}/{HOURLY_LIMIT}</code>\n\n"
        f"<b>💝 КОМ БО СКИДКА:</b> Купи 3+ билета → скидка 15%!\n"
        f"Цена: {HOURLY_PRICE:,} 💎 (или {int(HOURLY_PRICE * (1 - COMBO_DISCOUNT)):,} 💎 с комбо)"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text=f"🎫 КУПИТЬ 1 БИЛЕТ ({HOURLY_PRICE})", callback_data="buy_hourly_ticket:1")
    builder.button(text=f"🎫 КУПИТЬ 3 БИЛЕТА (скидка)", callback_data="buy_hourly_ticket:3")
    builder.button(text="🔙 НАЗАД", callback_data="lottery_main")
    
    if isinstance(event, types.Message):
        await event.answer(text, reply_markup=builder.adjust(1).as_markup(), parse_mode="HTML")
    else:
        await event.message.edit_text(text, reply_markup=builder.adjust(1).as_markup(), parse_mode="HTML")

@router.callback_query(F.data.startswith("buy_hourly_ticket:"))
async def buy_hourly_ticket_proc(call: types.CallbackQuery):
    user_id = call.from_user.id
    ticket_count = int(call.data.split(":")[1])
    
    connect = sqlite3.connect(DB_FILE, check_same_thread=False)
    connect.execute("BEGIN IMMEDIATE")
    cur = connect.cursor()
    
    try:
        # Проверка баланса
        cur.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        user_row = cur.fetchone()
        if not user_row:
            connect.execute("ROLLBACK")
            connect.close()
            await call.answer("❌ Пользователь не найден!", show_alert=True)
            return
        
        balance = user_row[0]
        
        # Расчет цены с комбо скидкой
        if ticket_count >= 3:
            final_price = int(HOURLY_PRICE * ticket_count * (1 - COMBO_DISCOUNT))
        else:
            final_price = HOURLY_PRICE * ticket_count
        
        if balance < final_price:
            connect.execute("ROLLBACK")
            connect.close()
            await call.answer(f"❌ Недостаточно средств! Нужно {final_price:,} 💎", show_alert=True)
            return
        
        # Проверка часовых лимитов
        start_of_hour = int(time.time()) // 3600 * 3600
        cur.execute("SELECT COUNT(*) FROM lottery_tickets WHERE user_id = ? AND lottery_type = 'hourly' AND buy_time > ?", (user_id, start_of_hour))
        existing = cur.fetchone()[0]
        if existing + ticket_count > HOURLY_LIMIT:
            connect.execute("ROLLBACK")
            connect.close()
            await call.answer(f"❌ Лимит: не более {HOURLY_LIMIT} в час!", show_alert=True)
            return
        
        # Обновляем баланс
        cur.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (final_price, user_id))
        
        # Добавляем билеты
        now = int(time.time())
        for _ in range(ticket_count):
            cur.execute("INSERT INTO lottery_tickets (user_id, lottery_type, buy_time) VALUES (?, ?, ?)", 
                       (user_id, 'hourly', now))
        
        # Получаем текущий draw_id для обновления джекпота
        cur.execute("SELECT draw_id FROM hourly_state ORDER BY draw_id DESC LIMIT 1")
        draw_info = cur.fetchone()
        draw_id = draw_info[0] if draw_info else 1
        
        # Обновляем джекпот (95% идет в банк)
        cur.execute("UPDATE hourly_state SET prize_pool = prize_pool + ? WHERE draw_id = ?", 
                   (int(final_price * 0.95), draw_id))
        
        connect.commit()
        connect.close()
        
        discount_text = " 💝 СО СКИДКОЙ!" if ticket_count >= 3 else ""
        await call.message.edit_text(
            f"✅ Куплено {ticket_count} билет{'ов' if ticket_count != 1 else ''}{discount_text}\n\n"
            f"💎 Потрачено: {final_price:,} 💎\n"
            f"🍀 Удачи в розыгрыше!"
        )
        
        await asyncio.sleep(2)
        await show_hourly(call)
        
    except TelegramBadRequest as e:
        cur.execute("ROLLBACK")
        connect.close()
        logger.warning(f"Callback timeout: {e}")
        # Игнорируем старые запросы
    except Exception as e:
        cur.execute("ROLLBACK")
        connect.close()
        logger.error(f"Error buying hourly tickets: {e}")
        try:
            await call.answer(f"❌ Ошибка: {str(e)}", show_alert=True)
        except:
            pass

# --- ЛОГИКА НЕДЕЛЬНОЙ ЛОТЕРЕИ ---

@router.callback_query(F.data == "view_weekly")
async def cb_view_weekly(call: types.CallbackQuery):
    await show_weekly(call)

async def show_weekly(event):
    """Отображение состояния недельной лотереи."""
    # Вычисляем время до конца недели (воскресенье 23:59:59)
    now = datetime.datetime.now()
    days_until_sunday = 6 - now.weekday()
    end_of_week = (now + datetime.timedelta(days=days_until_sunday)).replace(hour=23, minute=59, second=59)
    wait_time = end_of_week - now
    days = wait_time.days
    hours, remainder = divmod(wait_time.seconds, 3600)
    minutes, _ = divmod(remainder, 60)

    cursor.execute("SELECT draw_id, prize_pool FROM weekly_state ORDER BY draw_id DESC LIMIT 1")
    res = cursor.fetchone()
    if res:
        draw_id, pool = res
    else:
        # Создаем, если нет
        try:
            now_ts = int(time.time())
            cursor.execute("INSERT INTO weekly_state (draw_id, prize_pool, start_time) VALUES (1, 1000000, ?)", (now_ts,))
            conn.commit()
            draw_id, pool = 1, 1000000
        except Exception as e:
            logger.error(f"Error creating weekly_state: {e}")
            draw_id, pool = 1, 1000000
    
    user_id = event.from_user.id
    # Считаем билеты с начала недели (примерно)
    start_of_week = int((now - datetime.timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0).timestamp())
    cursor.execute("SELECT COUNT(*) FROM lottery_tickets WHERE user_id = ? AND lottery_type = 'weekly' AND buy_time > ?", (user_id, start_of_week))
    my_tickets = cursor.fetchone()[0]

    text = (
        f"📅 <b>НЕДЕЛЬНАЯ ЛОТЕРЕЯ #{draw_id}</b>\n\n"
        f"🔥 <b>СУПЕР ДЖЕКПОТ:</b> <code>{pool:,}</code> 💎\n\n"
        f"⏳ До розыгрыша: <code>{days}д {hours}ч {minutes}м</code>\n"
        f"🎫 Ваших билетов: <code>{my_tickets}/{WEEKLY_LIMIT}</code>\n\n"
        f"<b>💝 КОМ БО СКИДКА:</b> Купи 3+ билета → скидка 15%!\n"
        f"Цена: {WEEKLY_PRICE:,} 💎 (или {int(WEEKLY_PRICE * 3 * (1 - COMBO_DISCOUNT)):,} 💎 за 3 с комбо)"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text=f"🎫 КУПИТЬ 1 БИЛЕТ ({WEEKLY_PRICE})", callback_data="buy_weekly_ticket:1")
    builder.button(text=f"🎫 КУПИТЬ 3 БИЛЕТА (скидка)", callback_data="buy_weekly_ticket:3")
    builder.button(text="🔙 НАЗАД", callback_data="lottery_main")
    
    if isinstance(event, types.Message):
        await event.answer(text, reply_markup=builder.adjust(1).as_markup(), parse_mode="HTML")
    else:
        await event.message.edit_text(text, reply_markup=builder.adjust(1).as_markup(), parse_mode="HTML")

@router.callback_query(F.data.startswith("buy_weekly_ticket:"))
async def buy_weekly_ticket_proc(call: types.CallbackQuery):
    user_id = call.from_user.id
    ticket_count = int(call.data.split(":")[1])
    
    connect = sqlite3.connect(DB_FILE, check_same_thread=False)
    connect.execute("BEGIN IMMEDIATE")
    cur = connect.cursor()
    
    try:
        # Проверка баланса
        cur.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        user_row = cur.fetchone()
        if not user_row:
            connect.execute("ROLLBACK")
            connect.close()
            await call.answer("❌ Пользователь не найден!", show_alert=True)
            return
        
        balance = user_row[0]
        
        # Расчет цены с комбо скидкой
        if ticket_count >= 3:
            final_price = int(WEEKLY_PRICE * ticket_count * (1 - COMBO_DISCOUNT))
        else:
            final_price = WEEKLY_PRICE * ticket_count
        
        if balance < final_price:
            connect.execute("ROLLBACK")
            connect.close()
            await call.answer(f"❌ Недостаточно средств! Нужно {final_price:,} 💎", show_alert=True)
            return
        
        # Проверка недельных лимитов
        now = datetime.datetime.now()
        start_of_week = int((now - datetime.timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0).timestamp())
        cur.execute("SELECT COUNT(*) FROM lottery_tickets WHERE user_id = ? AND lottery_type = 'weekly' AND buy_time > ?", (user_id, start_of_week))
        existing = cur.fetchone()[0]
        if existing + ticket_count > WEEKLY_LIMIT:
            connect.execute("ROLLBACK")
            connect.close()
            await call.answer(f"❌ Лимит: не более {WEEKLY_LIMIT} в неделю!", show_alert=True)
            return
        
        # Обновляем баланс
        cur.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (final_price, user_id))
        
        # Добавляем билеты
        now_ts = int(time.time())
        for _ in range(ticket_count):
            cur.execute("INSERT INTO lottery_tickets (user_id, lottery_type, buy_time) VALUES (?, ?, ?)", 
                       (user_id, 'weekly', now_ts))
        
        # Получаем текущий draw_id для обновления джекпота
        cur.execute("SELECT draw_id FROM weekly_state ORDER BY draw_id DESC LIMIT 1")
        draw_info = cur.fetchone()
        draw_id = draw_info[0] if draw_info else 1
        
        # Обновляем джекпот (80% идет в банк)
        cur.execute("UPDATE weekly_state SET prize_pool = prize_pool + ? WHERE draw_id = ?", 
                   (int(final_price * 0.8), draw_id))
        
        connect.commit()
        connect.close()
        
        discount_text = " 💝 СО СКИДКОЙ!" if ticket_count >= 3 else ""
        await call.message.edit_text(
            f"✅ Куплено {ticket_count} билет{'ов' if ticket_count != 1 else ''}{discount_text}\n\n"
            f"💎 Потрачено: {final_price:,} 💎\n"
            f"🍀 До розыгрыша в воскресенье!"
        )
        
        await asyncio.sleep(2)
        await show_weekly(call)
        
    except TelegramBadRequest as e:
        cur.execute("ROLLBACK")
        connect.close()
        logger.warning(f"Callback timeout: {e}")
    except Exception as e:
        cur.execute("ROLLBACK")
        connect.close()
        logger.error(f"Error buying weekly tickets: {e}")
        try:
            await call.answer(f"❌ Ошибка: {str(e)}", show_alert=True)
        except:
            pass

# --- ЛОГИКА МЕГА-ЛОТЕРЕИ (НОВАЯ) ---

@router.callback_query(F.data == "view_mega")
async def cb_view_mega(call: types.CallbackQuery):
    await show_mega(call)

async def show_mega(event):
    """Отображение состояния мега-лотереи (НОВАЯ: высокие ставки)."""
    now = datetime.datetime.now()
    days_until_sunday = 6 - now.weekday()
    end_of_week = (now + datetime.timedelta(days=days_until_sunday)).replace(hour=23, minute=59, second=59)
    wait_time = end_of_week - now
    days = wait_time.days
    hours, remainder = divmod(wait_time.seconds, 3600)
    minutes, _ = divmod(remainder, 60)

    cursor.execute("SELECT draw_id, prize_pool FROM mega_state ORDER BY draw_id DESC LIMIT 1")
    res = cursor.fetchone()
    if res:
        draw_id, pool = res
    else:
        # Создаем, если нет
        try:
            now_ts = int(time.time())
            cursor.execute("INSERT INTO mega_state (draw_id, prize_pool, start_time) VALUES (1, 5000000, ?)", (now_ts,))
            conn.commit()
            draw_id, pool = 1, 5000000
        except Exception as e:
            logger.error(f"Error creating mega_state: {e}")
            draw_id, pool = 1, 5000000
    
    user_id = event.from_user.id
    start_of_week = int((now - datetime.timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0).timestamp())
    cursor.execute("SELECT COUNT(*) FROM lottery_tickets WHERE user_id = ? AND lottery_type = 'mega' AND buy_time > ?", (user_id, start_of_week))
    my_tickets = cursor.fetchone()[0]

    text = (
        f"🐳 <b>МЕГА-ЛОТЕРЕЯ #{draw_id}</b>\n\n"
        f"💎 <b>ЛЕГЕНДАРНЫЙ ДЖЕКПОТ:</b> <code>{pool:,}</code> 💎\n\n"
        f"⏳ До розыгрыша: <code>{days}д {hours}ч {minutes}м</code>\n"
        f"🎫 Ваших билетов: <code>{my_tickets}/{MEGA_LIMIT}</code>\n\n"
        f"<b>⚡ УСЛОВИЯ:</b>\n"
        f"🔹 Стоимость: <b>{MEGA_PRICE:,} 💎</b> (только для хайроллеров)\n"
        f"🔹 Лимит: {MEGA_LIMIT} билета в неделю\n"
        f"🔹 Приз: ВЕСЬ ДЖЕКПОТ ОДНОМУ ЧЕЛОВЕКУ! 🎉\n\n"
        f"<i>⭐ Чем больше участников - тем больше джекпот!</i>"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text=f"🎫 КУПИТЬ БИЛЕТ ({MEGA_PRICE:,})", callback_data="buy_mega_ticket")
    builder.button(text="🔙 НАЗАД", callback_data="lottery_main")
    
    if isinstance(event, types.Message):
        await event.answer(text, reply_markup=builder.adjust(1).as_markup(), parse_mode="HTML")
    else:
        await event.message.edit_text(text, reply_markup=builder.adjust(1).as_markup(), parse_mode="HTML")

@router.callback_query(F.data == "buy_mega_ticket")
async def buy_mega_ticket_proc(call: types.CallbackQuery):
    user_id = call.from_user.id
    user = db_get_user(user_id)
    if not user:
        return await call.answer("❌ Ошибка при загрузке профиля!", show_alert=True)
    
    # --- ПРОВЕРКА ЛИМИТОВ ---
    now = datetime.datetime.now()
    start_of_week = int((now - datetime.timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0).timestamp())
    
    cursor.execute("SELECT COUNT(*) FROM lottery_tickets WHERE user_id = ? AND lottery_type = 'mega' AND buy_time > ?", (user_id, start_of_week))
    ticket_count_result = cursor.fetchone()
    if ticket_count_result and ticket_count_result[0] >= MEGA_LIMIT:
        return await call.answer(f"❌ Лимит: {MEGA_LIMIT} билета в неделю!", show_alert=True)
    
    if user[0] < MEGA_PRICE:
        return await call.answer(f"❌ Недостаточно 💎! Нужно {MEGA_PRICE:,}", show_alert=True)

    # Стандартная покупка (без комбо для мега)
    db_update_stats(user_id, bet=MEGA_PRICE, win=0)
    
    now_ts = int(time.time())
    cursor.execute("INSERT INTO lottery_tickets (user_id, lottery_type, buy_time) VALUES (?, 'mega', ?)", (user_id, now_ts))
    
    # 100% идет в джекпот
    cursor.execute("UPDATE mega_state SET prize_pool = prize_pool + ? WHERE 1=1", (MEGA_PRICE,))
    conn.commit()
    
    try:
        await call.answer(f"✅ Билет в МЕГА-ЛОТЕРЕЮ куплен! Удачи! 🍀")
    except TelegramBadRequest as e:
        cursor.execute("ROLLBACK")
        logger.warning(f"Callback timeout при покупке МЕГА билета: {e}")
    
    await show_mega(call)

# --- ЛОГИКА ПРО-ЛОТЕРЕИ ---
async def fast_pro(message: types.Message):
    await show_pro(message)

@router.callback_query(F.data == "view_pro")
async def cb_pro(call: types.CallbackQuery):
    await show_pro(call)

async def show_pro(event):
    day_ago = int(time.time()) - 86400
    cursor.execute("SELECT COUNT(*) FROM lottery_tickets WHERE user_id = ? AND lottery_type = 'pro' AND buy_time > ?", (event.from_user.id, day_ago))
    count = cursor.fetchone()[0]

    text = (
        f"💼 <b>ПРОФЕССИОНАЛЬНАЯ ЛОТЕРЕЯ</b>\n\n"
        f"Это место для тех, кто не боится рисковать крупными суммами.\n\n"
        f"🎫 Вход: <code>{PRO_PRICE:,}</code> 💎\n"
        f"🏆 Макс. выигрыш: <code>2,000,000</code> 💎\n"
        f"🚫 Ограничение: <code>{count}/{PRO_LIMIT}</code> билета в сутки."
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="💎 КУПИТЬ БИЛЕТ", callback_data="buy_pro_ticket")
    builder.button(text="🔙 НАЗАД", callback_data="lottery_main")
    
    if isinstance(event, types.Message):
        await event.answer(text, reply_markup=builder.adjust(1).as_markup(), parse_mode="HTML")
    else:
        await event.message.edit_text(text, reply_markup=builder.adjust(1).as_markup(), parse_mode="HTML")

@router.callback_query(F.data == "buy_pro_ticket")
async def buy_pro_ticket_proc(call: types.CallbackQuery):
    user = db_get_user(call.from_user.id)
    if not user:
        return await call.answer("❌ Ошибка при загрузке профиля!", show_alert=True)
        
    day_ago = int(time.time()) - 86400
    cursor.execute("SELECT COUNT(*) FROM lottery_tickets WHERE user_id = ? AND lottery_type = 'pro' AND buy_time > ?", (call.from_user.id, day_ago))
    result = cursor.fetchone()
    ticket_count = result[0] if result else 0
    
    if ticket_count >= PRO_LIMIT:
        return await call.answer("❌ Приходите завтра! Лимит исчерпан.", show_alert=True)
    if user[0] < PRO_PRICE:
        return await call.answer("❌ Баланс слишком мал для Про-игр!", show_alert=True)

    # Логика выигрыша для Про: 3% шанс на супер-приз
    is_jackpot = random.random() < 0.03
    win = 2000000 if is_jackpot else random.randint(40000, 250000)
    
    cursor.execute("INSERT INTO lottery_tickets (user_id, lottery_type, buy_time) VALUES (?, 'pro', ?)", (call.from_user.id, int(time.time())))
    db_update_stats(call.from_user.id, bet=PRO_PRICE, win=win)
    conn.commit()
    
    if is_jackpot:
        header = "🚨 <b>НЕВЕРОЯТНЫЙ ДЖЕКПОТ!!!</b> 🚨"
        emoji = "🎰"
        footer = "Вы сорвали главный куш! Это история!"
    else:
        header = "🎉 <b>ПОЗДРАВЛЯЕМ С ПОБЕДОЙ!</b>"
        emoji = "💰"
        footer = "Средства успешно зачислены на ваш счет."

    try:
        await call.message.edit_text(
            f"{header}\n\n"
            f"{emoji} <b>Ваш выигрыш:</b> <code>{win:,}</code> 💎\n"
            f"💎 <b>Баланс пополнен!</b>\n\n"
            f"<i>{footer}</i>", 
            reply_markup=InlineKeyboardBuilder().button(text="🔙 Назад", callback_data="view_pro").as_markup(),
            parse_mode="HTML"
        )
    except TelegramBadRequest as e:
        logger.warning(f"Callback timeout при показе результата Про-лотереи: {e}")

# --- ПОЛЬЗОВАТЕЛЬСКИЕ ЛОТЕРЕИ (БАЗОВАЯ ЛОГИКА) ---

@router.message(Command("lotuser"))
async def fast_user(message: types.Message):
    await show_user_lots(message)

@router.callback_query(F.data == "view_user_lotteries")
async def cb_user_lots(call: types.CallbackQuery):
    await show_user_lots(call)

async def show_user_lots(event):
    cursor.execute(
        "SELECT id, title, prize_pool, ticket_price, max_tickets, sold_tickets FROM user_lotteries "
        "WHERE sold_tickets < max_tickets AND end_time > ?", (int(time.time()),)
    )
    lots = cursor.fetchall()
    
    builder = InlineKeyboardBuilder()
    text = "🎪 <b>ЛОТЕРЕИ ОТ ПОЛЬЗОВАТЕЛЕЙ</b>\n\n"
    
    if not lots:
        text += "На данный момент активных предложений нет.\nСтаньте первым и создайте свою лотерею!"
    else:
        for lot in lots:
            text += f"▪️ <b>{lot[1]}</b>\n   💰 Приз: <code>{lot[2]:,}</code> | 🎫 Цена: <code>{lot[3]:,}</code>\n   🎟 Остаток: <code>{lot[4]-lot[5]}/{lot[4]}</code>\n\n"
            builder.button(text=f"🎫 {lot[1]}", callback_data=f"buy_ulot:{lot[0]}")
    
    builder.button(text="➕ Создать лотерею", callback_data="create_user_lottery")
    builder.button(text="🔙 Назад в меню", callback_data="lottery_main")
    builder.adjust(1)
    
    if isinstance(event, types.Message):
        await event.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    else:
        await event.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")

# --- СИСТЕМА СОЗДАНИЯ СВОЕЙ ЛОТЕРЕИ (FSM) ---

@router.callback_query(F.data == "create_user_lottery")
async def start_creation(call: types.CallbackQuery, state: FSMContext):
    user = db_get_user(call.from_user.id)
    # Ограничение по опыту (количеству игр)
    if user[5] < 10:
        return await call.answer("❌ Вам нужно сыграть минимум 10 игр в казино!", show_alert=True)
    
    await state.update_data(msg_id=call.message.message_id)
    await state.set_state(CreateLottery.title)
    await call.message.edit_text(
        "🎪 <b>СОЗДАНИЕ ЛОТЕРЕИ (1/4)</b>\n\nВведите яркое название для вашего розыгрыша:", 
        parse_mode="HTML"
    )

@router.message(CreateLottery.title)
async def process_title(message: types.Message, state: FSMContext):
    data = await state.get_data()
    title_fixed = message.text[:30]
    await state.update_data(title=title_fixed)
    await state.set_state(CreateLottery.prize_pool)
    
    try: await message.delete()
    except: pass
    
    await message.bot.edit_message_text(
        chat_id=message.chat.id, 
        message_id=data['msg_id'], 
        text=f"🎪 <b>ШАГ 2/4 (Название: {title_fixed})</b>\n\nКакая сумма будет разыграна? (минимум 10,000 💎):",
        parse_mode="HTML"
    )

@router.message(CreateLottery.prize_pool)
async def process_pool(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if not message.text.isdigit():
        return await message.answer("❌ Введите число!")
    
    val = int(message.text)
    if val < 10000:
        return await message.answer("❌ Минимальный приз 10,000!")
        
    await state.update_data(prize_pool=val)
    await state.set_state(CreateLottery.ticket_price)
    
    try: await message.delete()
    except: pass
    
    await message.bot.edit_message_text(
        chat_id=message.chat.id, 
        message_id=data['msg_id'], 
        text=f"🎪 <b>ШАГ 3/4 (Приз: {val:,})</b>\n\nСколько будет стоить один билет?",
        parse_mode="HTML"
    )

@router.message(CreateLottery.ticket_price)
async def process_price(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if not message.text.isdigit():
        return await message.answer("❌ Введите число!")
    
    price = int(message.text)
    if price <= 0: return
    
    await state.update_data(ticket_price=price)
    await state.set_state(CreateLottery.max_tickets)
    
    try: await message.delete()
    except: pass
    
    await message.bot.edit_message_text(
        chat_id=message.chat.id, 
        message_id=data['msg_id'], 
        text=f"🎪 <b>ШАГ 4/4 (Цена: {price:,})</b>\n\nКакое общее количество билетов выпустить?",
        parse_mode="HTML"
    )

@router.message(CreateLottery.max_tickets)
async def process_max_tickets(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if not message.text.isdigit(): return
    
    count = int(message.text)
    fee = int(data['prize_pool'] * SYSTEM_FEE)
    total = data['prize_pool'] + fee
    
    await state.update_data(max_tickets=count, total_cost=total)
    await state.set_state(CreateLottery.confirm)
    
    summary = (
        f"📝 <b>ПРОВЕРКА ВАШЕЙ ЛОТЕРЕИ</b>\n\n"
        f"🏷 Название: <code>{data['title']}</code>\n"
        f"💰 Выигрыш: <code>{data['prize_pool']:,} 💎</code>\n"
        f"🎫 Цена билета: <code>{data['ticket_price']:,} 💎</code>\n"
        f"🎟 Всего билетов: <code>{count} шт.</code>\n"
        f"━━━━━━━━━━━━━━\n"
        f"💵 Итого к оплате: <b>{total:,} 💎</b>\n"
        f"<i>(Приз + комиссия 5%)</i>"
    )
    
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ ПОДТВЕРДИТЬ И ОПЛАТИТЬ", callback_data="confirm_ulot")
    builder.button(text="❌ ОТМЕНА", callback_data="lottery_main")
    
    try: await message.delete()
    except: pass
    
    await message.bot.edit_message_text(
        chat_id=message.chat.id, 
        message_id=data['msg_id'], 
        text=summary, 
        reply_markup=builder.adjust(1).as_markup(),
        parse_mode="HTML"
    )

@router.callback_query(F.data == "confirm_ulot")
async def finalize_ulot(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user = db_get_user(call.from_user.id)
    
    if user[0] < data['total_cost']:
        return await call.answer("❌ Ошибка оплаты: недостаточно средств!", show_alert=True)
    
    # Списание средств
    db_update_stats(call.from_user.id, bet=data['total_cost'], win=0)
    
    # Запись в БД
    cursor.execute(
        "INSERT INTO user_lotteries (creator_id, title, prize_pool, ticket_price, max_tickets, end_time, sold_tickets) "
        "VALUES (?, ?, ?, ?, ?, ?, 0)",
        (call.from_user.id, data['title'], data['prize_pool'], data['ticket_price'], data['max_tickets'], int(time.time()) + 86400)
    )
    conn.commit()
    
    await state.clear()
    await call.message.edit_text(
        f"🎉 <b>ЛОТЕРЕЯ ЗАПУЩЕНА!</b>\n\nВаш розыгрыш «{data['title']}» активирован. Как только все билеты будут раскуплены, победитель определится автоматически!",
        reply_markup=InlineKeyboardBuilder().button(text="🏠 В лотерейный центр", callback_data="lottery_main").as_markup(),
        parse_mode="HTML"
    )

# --- ЛОГИКА УЧАСТИЯ В ПОЛЬЗОВАТЕЛЬСКИХ ЛОТЕРЕЯХ ---

@router.callback_query(F.data.startswith("buy_ulot:"))
async def process_buy_user_ticket(call: types.CallbackQuery):
    lot_id = int(call.data.split(":")[1])
    user_id = call.from_user.id
    
    cursor.execute("SELECT title, prize_pool, ticket_price, max_tickets, sold_tickets FROM user_lotteries WHERE id = ?", (lot_id,))
    lot = cursor.fetchone()
    if not lot: return await call.answer("❌ Лотерея завершена.", show_alert=True)
    
    title, prize, price, max_t, sold = lot
    if sold >= max_t: return await call.answer("❌ Билетов нет!", show_alert=True)
        
    user = db_get_user(user_id)
    if user[0] < price: return await call.answer(f"❌ Нужно {price:,} 💎", show_alert=True)
        
    # --- ЛОГИКА ЗОЛОТОГО БИЛЕТА ---
    cursor.execute("SELECT gold_ticket FROM users WHERE id = ?", (user_id,))
    has_gold = cursor.fetchone()[0]
    entries = 3 if has_gold > 0 else 1 # В БД будет 3 записи этого юзера

    db_update_stats(user_id, bet=price, win=0)
    
    # Засчитываем только 1 билет в общий счетчик (чтобы лотерея не закрылась слишком быстро)
    new_sold = sold + 1
    cursor.execute("UPDATE user_lotteries SET sold_tickets = ? WHERE id = ?", (new_sold, lot_id))
    
    # Но в таблицу участников записываем 3 раза для повышения шанса
    now = int(time.time())
    for _ in range(entries):
        cursor.execute("INSERT INTO lottery_tickets (user_id, lottery_type, buy_time) VALUES (?, ?, ?)", 
                       (user_id, f"user_lot_{lot_id}", now))
    
    # Списываем золотой билет если он был использован
    if has_gold > 0:
        cursor.execute("UPDATE users SET gold_ticket = gold_ticket - 1 WHERE id = ?", (user_id,))
        
    conn.commit()
    
    bonus_text = " 🔥 Шанс x3!" if has_gold else ""
    await call.answer(f"✅ Билет куплен!{bonus_text}")
    
    # Если это последний билет — выбираем победителя сразу
    if new_sold >= max_t:
        await finish_user_lottery(lot_id, call.message)
    else:
        # Обновляем список лотерей, чтобы цифры изменились
        await show_user_lots(call)

async def finish_user_lottery(lot_id, message):
    """Функция рандома и выплаты приза."""
    try:
        cursor.execute("SELECT title, prize_pool, creator_id FROM user_lotteries WHERE id = ?", (lot_id,))
        lot_data = cursor.fetchone()
        if not lot_data:
            logger.warning(f"Lottery {lot_id} not found in database")
            return

        # Достаем всех участников этой конкретной лотереи
        cursor.execute("SELECT user_id FROM lottery_tickets WHERE lottery_type = ?", (f"user_lot_{lot_id}",))
        rows = cursor.fetchall()
        
        if rows:
            participants = [r[0] for r in rows]
            winner_id = random.choice(participants) # Случайный выбор из списка
            
            # Выдаем выигрыш
            db_update_stats(winner_id, bet=0, win=lot_data[1])
            
            # Красивое сообщение о победе
            text = (
                f"🎊 <b>ЛОТЕРЕЯ ЗАВЕРШЕНА!</b>\n\n"
                f"В розыгрыше «{lot_data[0]}» все билеты проданы!\n"
                f"🏆 Победитель: <code>{winner_id}</code>\n"
                f"💰 Приз <b>{lot_data[1]:,} 💎</b> зачислен на баланс!"
            )
            try:
                await message.answer(text, parse_mode="HTML")
            except TelegramBadRequest as e:
                logger.error(f"Error sending lottery finish message: {e}")
                
            # Уведомляем создателя лотереи
            try:
                await message.bot.send_message(
                    lot_data[2],
                    f"✅ Ваша лотерея '{lot_data[0]}' завершена! Выплачено {lot_data[1]:,} 💎"
                )
            except Exception as e:
                logger.error(f"Error notifying lottery creator {lot_data[2]}: {e}")
        else:
            logger.warning(f"No participants found for lottery {lot_id}")

        # Удаляем лотерею и билеты, чтобы не занимать место в БД
        cursor.execute("DELETE FROM user_lotteries WHERE id = ?", (lot_id,))
        cursor.execute("DELETE FROM lottery_tickets WHERE lottery_type = ?", (f"user_lot_{lot_id}",))
        conn.commit()
    except Exception as e:
        logger.error(f"Error finishing lottery {lot_id}: {e}")