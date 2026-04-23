import datetime
import time
import random
import logging
import asyncio
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database import db_get_user, db_update_stats, cursor, conn
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
PRO_PRICE = 100000          # Цена билета в Про-лотерее
PRO_LIMIT = 2               # Лимит билетов в сутки для Про
HOURLY_PRICE = 500          # Цена билета в часовой лотерее
HOURLY_LIMIT = 10           # Лимит билетов в час для одного игрока
INSTANT_PRICE = 1000        # Цена билета в мгновенной лотерее
SYSTEM_FEE = 0.05           # Комиссия системы (5%)

router = Router()

async def is_owner(call: types.CallbackQuery):
    """
    Проверяет, является ли нажавший кнопку тем же пользователем, 
    который вызвал команду. Предотвращает 'воровство' интерфейса.
    """
    if call.message.reply_to_message and call.message.reply_to_message.from_user.id != call.from_user.id:
        await call.answer("❌ Это не ваше меню! Введите команду /lottery сами.", show_alert=True)
        return False
    return True

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ИНТЕРФЕЙСА ---

def get_main_kb():
    """Генерация главного меню лотерейного центра."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🕐 Часовая", callback_data="view_hourly")
    builder.button(text="⚡ Мгновенная", callback_data="buy_lottery:instant")
    builder.button(text="🎪 Пользовательская", callback_data="view_user_lotteries")
    builder.button(text="💼 Профессиональная", callback_data="view_pro")
    builder.button(text="📊 Мои билеты", callback_data="my_tickets_stats")
    builder.button(text="❓ Помощь", callback_data="lothelp_cb")
    builder.button(text="🏠 В профиль", callback_data="back_to_profile")
    builder.adjust(2, 2, 1, 2)
    return builder.as_markup()

# --- ОБРАБОТЧИКИ ОСНОВНЫХ КОМАНД ---

@router.message(Command("lottery"))
async def lottery_menu(message: types.Message):
    """Точка входа в меню лотерей."""
    if not await check_user(message): 
        return
    
    logger.info(f"User {message.from_user.id} opened lottery menu")
    text = (
        "🎰 <b>ГЛАВНОЕ МЕНЮ ЛОТЕРЕЙ</b>\n\n"
        "Добро пожаловать в игровой центр! Испытайте свою удачу в одном из доступных режимов.\n\n"
        "📢 <i>Подсказка: используйте кнопки ниже для навигации.</i>"
    )
    await message.answer(text, reply_markup=get_main_kb(), parse_mode="HTML")

@router.message(Command("lothelp"))
async def cmd_lothelp(message: types.Message):
    """Вывод подробной справки по всем режимам."""
    text = (
        "❓ <b>ПОЛНАЯ СПРАВКА ПО ЛОТЕРЕЯМ</b>\n\n"
        "1️⃣ <b>Часовая</b> — Общий банк формируется из покупок. Розыгрыш в конце каждого часа.\n"
        "2️⃣ <b>Мгновенная</b> — Купил, стер слой, выиграл (или нет). Результат сразу.\n"
        "3️⃣ <b>Пользовательская</b> — Лотереи, созданные игроками. Вы сами ставите условия.\n"
        "4️⃣ <b>Профессиональная</b> — Высокие ставки для хайриллеров. Шанс на джекпот.\n\n"
        "💡 <i>Комиссия при создании пользовательских игр составляет 5%.</i>"
    )
    await message.answer(text, parse_mode="HTML")

@router.callback_query(F.data == "lothelp_cb")
async def lothelp_callback(call: types.CallbackQuery):
    """Справка внутри инлайн-меню."""
    text = (
        "❓ <b>ТЕХНИЧЕСКАЯ ИНФОРМАЦИЯ</b>\n\n"
        "• <b>Лимиты:</b>\n"
        "  — Часовая: до 10 билетов.\n"
        "  — Про: до 2 билетов в 24 часа.\n"
        "• <b>Выплаты:</b>\n"
        "  — Начисляются автоматически на баланс профиля.\n\n"
        "Удачи, игрок!"
    )
    builder = InlineKeyboardBuilder().button(text="🔙 Назад", callback_data="lottery_main")
    await call.message.edit_text(text, reply_markup=builder.as_markup())

@router.callback_query(F.data == "lottery_main")
async def lottery_main_callback(call: types.CallbackQuery, state: FSMContext):
    """Возврат в главное меню из любого раздела."""
    await state.clear()
    await call.message.edit_text("🎰 <b>ГЛАВНОЕ МЕНЮ ЛОТЕРЕЙ</b>", reply_markup=get_main_kb(), parse_mode="HTML")

@router.callback_query(F.data == "back_to_profile")
async def back_to_profile(call: types.CallbackQuery):
    """Удаление сообщения меню и вызов функции профиля."""
    
@router.callback_query(F.data == "back_to_main")
async def back_to_profile(call: types.CallbackQuery):
    # Вместо импорта просто вызываем текст профиля
    # Если хочешь вернуться в меню помощи:
    from Handlers.common import cmd_help
    await cmd_help(call.message)
    await call.answer()
    
    try:
        await call.message.delete()
        await start_command(call.message)
    except Exception as e:
        logger.error(f"Error returning to profile: {e}")

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
    draw_id, pool = res if res else (1, 100000)
    
    user_id = event.from_user.id
    start_of_hour = int(time.time()) // 3600 * 3600
    cursor.execute("SELECT COUNT(*) FROM lottery_tickets WHERE user_id = ? AND lottery_type = 'hourly' AND buy_time > ?", (user_id, start_of_hour))
    my_tickets = cursor.fetchone()[0]

    text = (
        f"🕐 <b>ЧАСОВАЯ ЛОТЕРЕЯ #{draw_id}</b>\n\n"
        f"⏳ До розыгрыша: <code>{minutes:02d}:{seconds:02d}</code>\n"
        f"💰 Текущий джекпот: <code>{pool:,}</code> 💎\n"
        f"🎫 Ваших билетов: <code>{my_tickets}/{HOURLY_LIMIT}</code>\n\n"
        "Чем больше билетов, тем выше шанс победить!"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text=f"🎫 КУПИТЬ БИЛЕТ ({HOURLY_PRICE})", callback_data="buy_hourly_ticket")
    builder.button(text="🔙 НАЗАД", callback_data="lottery_main")
    
    if isinstance(event, types.Message):
        await event.answer(text, reply_markup=builder.adjust(1).as_markup(), parse_mode="HTML")
    else:
        await event.message.edit_text(text, reply_markup=builder.adjust(1).as_markup(), parse_mode="HTML")

@router.callback_query(F.data == "buy_hourly_ticket")
async def buy_hourly_ticket_proc(call: types.CallbackQuery):
    user_id = call.from_user.id
    user = db_get_user(user_id)
    
    # --- ПРОВЕРКА ЛИМИТОВ ---
    start_of_hour = int(time.time()) // 3600 * 3600
    cursor.execute("SELECT COUNT(*) FROM lottery_tickets WHERE user_id = ? AND lottery_type = 'hourly' AND buy_time > ?", (user_id, start_of_hour))
    if cursor.fetchone()[0] >= HOURLY_LIMIT:
        return await call.answer("❌ Лимит: 10 билетов в час!", show_alert=True)
    
    if user[0] < HOURLY_PRICE:
        return await call.answer("❌ Недостаточно 💎 на балансе!", show_alert=True)

    # --- НОВАЯ ЛОГИКА (ЗОЛОТОЙ БИЛЕТ) ---
    cursor.execute("SELECT gold_ticket FROM users WHERE id = ?", (user_id,))
    has_gold = cursor.fetchone()[0]
    
    # Если есть золотой билет — вставляем 3 записи (шанс x3), иначе 1
    entries = 3 if has_gold > 0 else 1
    
    # Списываем деньги один раз
    db_update_stats(user_id, bet=HOURLY_PRICE, win=0)
    
    # Добавляем записи в таблицу (шансы)
    now = int(time.time())
    for _ in range(entries):
        cursor.execute("INSERT INTO lottery_tickets (user_id, lottery_type, buy_time) VALUES (?, 'hourly', ?)", (user_id, now))
    
    cursor.execute("UPDATE hourly_state SET prize_pool = prize_pool + ?", (int(HOURLY_PRICE * 0.95),))
    conn.commit()
    
    bonus_msg = " (Шансы x3 с Золотым билетом! ✨)" if has_gold else ""
    await call.answer(f"✅ Билет успешно куплен!{bonus_msg}")
    await show_hourly(call)

# --- ЛОГИКА МГНОВЕННОЙ ЛОТЕРЕИ ---

@router.message(Command("lotinstant"))
async def fast_instant(message: types.Message):
    await show_instant(message)

@router.callback_query(F.data == "buy_lottery:instant")
async def cb_instant(call: types.CallbackQuery):
    await show_instant(call)

async def show_instant(event):
    text = (
        "⚡ <b>МГНОВЕННАЯ ЛОТЕРЕЯ</b>\n\n"
        "Правила просты: покупаете билет и сразу стираете защитный слой.\n"
        f"🎫 Стоимость участия: <b>{INSTANT_PRICE:,} 💎</b>\n\n"
        "Возможные призы: от 500 до 50,000 💎!"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="🎫 Купить и стереть", callback_data="inst_buy_process")
    builder.button(text="🔙 Назад", callback_data="lottery_main")
    if isinstance(event, types.Message):
        await event.answer(text, reply_markup=builder.adjust(1).as_markup(), parse_mode="HTML")
    else:
        await event.message.edit_text(text, reply_markup=builder.adjust(1).as_markup(), parse_mode="HTML")

@router.callback_query(F.data == "inst_buy_process")
async def inst_buy_process(call: types.CallbackQuery):
    user = db_get_user(call.from_user.id)
    if user[0] < INSTANT_PRICE:
        return await call.answer("❌ У вас не хватает 💎", show_alert=True)

    db_update_stats(call.from_user.id, bet=INSTANT_PRICE, win=0)
    
    text = (
        "🎫 <b>БИЛЕТ У ВАС В РУКАХ!</b>\n\n"
        "Защитный слой: <code>[ ▓▓▓▓▓▓▓▓▓▓▓▓ ]</code>\n\n"
        "Скорее жми кнопку ниже!"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="🔍 СТЕРЕТЬ СЛОЙ", callback_data="inst_reveal_result")
    await call.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")

@router.callback_query(F.data == "inst_reveal_result")
async def inst_reveal_result(call: types.CallbackQuery):
    # Логика распределения выигрыша
    rnd = random.random() * 100
    if rnd <= 70: win = random.randint(300, 1200)      # 70% шанс на мелкий приз
    elif rnd <= 95: win = random.randint(1500, 6000)   # 25% шанс на средний
    else: win = random.randint(12000, 65000)           # 5% шанс на джекпот

    db_update_stats(call.from_user.id, bet=0, win=win)
    
    res_text = (
        f"✨ <b>РЕЗУЛЬТАТ РОЗЫГРЫША</b> ✨\n\n"
        f"💰 Ваш выигрыш: <b>{win:,} 💎</b>\n\n"
        f"Деньги уже зачислены на ваш счет."
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Купить еще один", callback_data="inst_buy_process")
    builder.button(text="🔙 В главное меню", callback_data="lottery_main")
    await call.message.edit_text(res_text, reply_markup=builder.adjust(1).as_markup(), parse_mode="HTML")

# --- ЛОГИКА ПРО-ЛОТЕРЕИ ---

@router.message(Command("lotpro"))
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
    day_ago = int(time.time()) - 86400
    cursor.execute("SELECT COUNT(*) FROM lottery_tickets WHERE user_id = ? AND lottery_type = 'pro' AND buy_time > ?", (call.from_user.id, day_ago))
    
    if cursor.fetchone()[0] >= PRO_LIMIT:
        return await call.answer("❌ Приходите завтра! Лимит исчерпан.", show_alert=True)
    if user[0] < PRO_PRICE:
        return await call.answer("❌ Баланс слишком мал для Про-игр!", show_alert=True)

    # Логика выигрыша для Про: 3% шанс на супер-приз
    is_jackpot = random.random() < 0.03
    win = 2000000 if is_jackpot else random.randint(40000, 250000)
    
    cursor.execute("INSERT INTO lottery_tickets (user_id, lottery_type, buy_time) VALUES (?, 'pro', ?)", (call.from_user.id, int(time.time())))
    db_update_stats(call.from_user.id, bet=PRO_PRICE, win=win)
    conn.commit()
    
    msg_win = f"🎉 <b>ДЖЕКПОТ!</b>" if is_jackpot else "✅ <b>Результат игры</b>"
    await call.message.edit_text(
        f"{msg_win}\n\n"
        f"💰 Выигрыш составил: <code>{win:,}</code> 💎\n\n"
        "Средства зачислены мгновенно.", 
        reply_markup=InlineKeyboardBuilder().button(text="🔙 Назад", callback_data="view_pro").as_markup()
    )

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
        text=f"🎪 <b>ШАГ 2/4 (Название: {title_fixed})</b>\n\nКакая сумма будет разыграна? (минимум 10,000 💎):"
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
        text=f"🎪 <b>ШАГ 3/4 (Приз: {val:,})</b>\n\nСколько будет стоить один билет?"
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
        text=f"🎪 <b>ШАГ 4/4 (Цена: {price:,})</b>\n\nКакое общее количество билетов выпустить?"
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
        reply_markup=InlineKeyboardBuilder().button(text="🏠 В лотерейный центр", callback_data="lottery_main").as_markup()
    )
    
# --- ДОПОЛНИТЕЛЬНАЯ СТАТИСТИКА ---

@router.callback_query(F.data == "my_tickets_stats")
async def my_tickets_stats(call: types.CallbackQuery):
    """Отображение купленных билетов пользователя (Расширение кода)."""
    user_id = call.from_user.id
    cursor.execute("SELECT COUNT(*) FROM lottery_tickets WHERE user_id = ?", (user_id,))
    total_bought = cursor.fetchone()[0]
    
    text = (
        "📊 <b>ВАША СТАТИСТИКА БИЛЕТОВ</b>\n\n"
        f"Куплено системных билетов: <code>{total_bought}</code>\n"
        "Здесь будет отображаться история ваших последних розыгрышей."
    )
    builder = InlineKeyboardBuilder().button(text="🔙 Назад", callback_data="lottery_main")
    await call.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")

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
    conn.commit()
    
    bonus_text = " 🔥 Шанс x3!" if has_gold else ""
    await call.answer(f"✅ Билет куплен!{bonus_text}")
    
    if new_sold >= max_t:
        await finish_user_lottery(lot_id, call.message)
    else:
        await show_user_lots(call)
    
    # Если это последний билет — выбираем победителя сразу
    if new_sold >= max_t:
        await finish_user_lottery(lot_id, call.message)
    else:
        # Обновляем список лотерей, чтобы цифры изменились
        await show_user_lots(call)

async def finish_user_lottery(lot_id, message):
    """Функция рандома и выплаты приза."""
    cursor.execute("SELECT title, prize_pool FROM user_lotteries WHERE id = ?", (lot_id,))
    lot_data = cursor.fetchone()
    if not lot_data: return

    # Достаем всех участников этой конкретной лотереи
    cursor.execute("SELECT user_id FROM lottery_tickets WHERE lottery_type = ?", (f"user_lot_{lot_id}",))
    rows = cursor.fetchall()
    
    if rows:
        participants = [r[0] for r in rows]
        winner_id = random.choice(participants) # Случайный выбор из списка
        
        # Выдаем выигрыш
        db_update_stats(winner_id, bet=0, win=lot_data[1])
        
        # Красивое сообщение о победе
        await message.answer(
            f"🎊 <b>ЛОТЕРЕЯ ЗАВЕРШЕНА!</b>\n\n"
            f"В розыгрыше «{lot_data[0]}» все билеты проданы!\n"
            f"🏆 Победитель: <code>{winner_id}</code>\n"
            f"💰 Приз <b>{lot_data[1]:,} 💎</b> зачислен на баланс!",
            parse_mode="HTML"
        )

    # Удаляем лотерею и билеты, чтобы не занимать место в БД
    cursor.execute("DELETE FROM user_lotteries WHERE id = ?", (lot_id,))
    cursor.execute("DELETE FROM lottery_tickets WHERE lottery_type = ?", (f"user_lot_{lot_id}",))
    conn.commit()