import asyncio
import logging
import time

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import (
    conn,
    cursor,
    db_get_user,
    db_has_free_games,
    db_increment_pvp_wins,
    db_update_stats,
)
from utils import safe_send_message

logger = logging.getLogger(__name__)
router = Router()

class PvPState(StatesGroup):
    waiting_bet = State()
    selecting_mode = State()

@router.message(Command("pvp"))
async def pvp_menu(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.button(text="🎲 Кости (Dice)", callback_data="pvp_mode:dice")
    builder.button(text="🎯 Дартс (Darts)", callback_data="pvp_mode:darts") 
    builder.button(text="🏀 Баскетбол (Basketball)", callback_data="pvp_mode:basketball")
    builder.button(text="⚽ Футбол (Football)", callback_data="pvp_mode:football")
    builder.button(text="🔍 Найти соперника", callback_data="pvp_list")
    builder.button(text="📋 Мои игры", callback_data="pvp_my")
    builder.adjust(2, 2, 1, 1)
    
    user_data = db_get_user(message.from_user.id)
    pvp_wins = user_data[13] if len(user_data) > 14 else 0  # Индекс pvp_wins в обновленной схеме
    has_free_games = db_has_free_games(message.from_user.id)
    
    status_text = ""
    if has_free_games:
        status_text = "🏆 **ВИП СТАТУС:** Все игры бесплатны!\n"
    elif pvp_wins >= 50:
        status_text = f"🏆 **ПОБЕД:** {pvp_wins}/50 - Доступ к бесплатным играм активирован!\n"
    else:
        status_text = f"📊 **Прогресс:** {pvp_wins}/50 побед до бесплатных игр\n"
    
    text = (
        f"⚔️ **PVP АРЕНА (1x1)**\n\n"
        f"{status_text}\n"
        f"Выберите режим игры:\n"
        f"🎲 **Кости** - Классическая игра в кости\n"
        f"🎯 **Дартс** - Стрельба по мишени\n"
        f"🏀 **Баскетбол** - Броски в кольцо\n"
        f"⚽ **Футбол** - Удары по воротам\n\n"
        f"🆓 **Бесплатный вход:** Можно сыграть без ставки, но выигрыш составит только 50% от банка.\n"
        f"⚠️ Комиссия арены: 5% с выигрыша."
    )
    await message.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@router.callback_query(F.data == "pvp_menu")
async def back_to_pvp(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await pvp_menu(call.message)
    await call.answer()

@router.callback_query(F.data.startswith("pvp_mode:"))
async def pvp_select_mode(call: types.CallbackQuery, state: FSMContext):
    game_mode = call.data.split(":")[1]
    await state.update_data(game_mode=game_mode)
    
    mode_names = {
        'dice': '🎲 Кости',
        'darts': '🎯 Дартс', 
        'basketball': '🏀 Баскетбол',
        'football': '⚽ Футбол'
    }
    
    await call.message.edit_text(
        f"💸 **СОЗДАНИЕ ДУЭЛИ - {mode_names[game_mode]}**\n\nВведите сумму ставки (минимум 100 💎):",
        reply_markup=InlineKeyboardBuilder().button(text="🔙 Отмена", callback_data="pvp_menu").as_markup(),
        parse_mode="Markdown"
    )
    await state.set_state(PvPState.waiting_bet)

@router.callback_query(F.data == "pvp_create")
async def pvp_create_start(call: types.CallbackQuery, state: FSMContext):
    await call.message.edit_text(
        "💸 **СОЗДАНИЕ ДУЭЛИ**\n\nВведите сумму ставки (минимум 100 💎):",
        reply_markup=InlineKeyboardBuilder().button(text="🔙 Отмена", callback_data="pvp_menu").as_markup(),
        parse_mode="Markdown"
    )
    await state.set_state(PvPState.waiting_bet)

@router.message(PvPState.waiting_bet)
async def pvp_create_process(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.reply("❌ Введите число!")
    
    bet = int(message.text)
    if bet <= 0:
        return await message.reply("❌ Ставка должна быть положительной!")
    if bet < 100:
        return await message.reply("❌ Минимальная ставка — 100 💎")
    
    user_data = db_get_user(message.from_user.id)
    
    # Проверяем, имеет ли пользователь бесплатные игры
    has_free_games = db_has_free_games(message.from_user.id)
    
    if not has_free_games and user_data[0] < bet:
        return await message.reply(f"❌ Недостаточно средств! Баланс: {user_data[0]:,} 💎")
    
    # Получаем режим игры из состояния
    data = await state.get_data()
    game_mode = data.get('game_mode', 'dice')
    
    # Списываем ставку только если у пользователя нет бесплатных игр
    has_free_games = db_has_free_games(message.from_user.id)
    if not has_free_games:
        db_update_stats(message.from_user.id, bet=bet, win=0)
    
    # Создаем игру
    now = int(time.time())
    cursor.execute(
        "INSERT INTO pvp_games (creator_id, bet, created_at, join_type, game_mode) VALUES (?, ?, ?, 'paid', ?)",
        (message.from_user.id, bet, now, game_mode)
    )
    conn.commit()
    game_id = cursor.lastrowid
    
    await state.clear()
    
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отменить поиск", callback_data=f"pvp_cancel:{game_id}")
    builder.button(text="🔙 В меню", callback_data="pvp_menu")
    builder.adjust(1)
    
    mode_names = {
        'dice': '🎲 Кости',
        'darts': '🎯 Дартс', 
        'basketball': '🏀 Баскетбол',
        'football': '⚽ Футбол'
    }
    
    # Определяем тип игры
    game_type_text = "🆓 БЕСПЛАТНАЯ" if has_free_games else "💰 ПЛАТНАЯ"
    
    await message.answer(
        f"✅ **ДУЭЛЬ #{game_id} СОЗДАНА!**\n\n"
        f"🎮 Режим: {mode_names[game_mode]}\n"
        f"💰 Ставка: {bet:,} 💎\n"
        f"🎮 Тип игры: {game_type_text}\n"
        f"⏳ Ожидаем соперника...\n\n"
        f"Ваша игра появилась в общем списке.",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )

@router.callback_query(F.data.startswith("pvp_list"))
async def pvp_list_games(call: types.CallbackQuery):
    # Проверяем, есть ли фильтр по режиму
    mode_filter = None
    if call.data.startswith("pvp_list:"):
        mode_filter = call.data.split(":")[1]
    
    if mode_filter:
        cursor.execute(
            "SELECT id, creator_id, bet, game_mode FROM pvp_games WHERE status = 'waiting' AND game_mode = ? ORDER BY bet DESC LIMIT 10",
            (mode_filter,)
        )
    else:
        cursor.execute(
            "SELECT id, creator_id, bet, game_mode FROM pvp_games WHERE status = 'waiting' ORDER BY bet DESC LIMIT 10"
        )
    games = cursor.fetchall()
    
    if not games:
        builder = InlineKeyboardBuilder()
        builder.button(text="⚔️ Создать свою", callback_data="pvp_menu")
        builder.button(text="🔙 Назад", callback_data="pvp_menu")
        builder.adjust(1)
        return await call.message.edit_text(
            "🔍 **АКТИВНЫХ ИГР НЕТ**\n\nНикто еще не создал дуэль в этом режиме. Будьте первым!",
            reply_markup=builder.as_markup(),
            parse_mode="Markdown"
        )
    
    builder = InlineKeyboardBuilder()
    
    # Кнопки фильтрации по режиму
    builder.button(text="🎲 Кости", callback_data="pvp_list:dice")
    builder.button(text="🎯 Дартс", callback_data="pvp_list:darts")
    builder.button(text="🏀 Баскет", callback_data="pvp_list:basketball")
    builder.button(text="⚽ Футбол", callback_data="pvp_list:football")
    
    for game in games:
        game_id, creator_id, bet, game_mode = game
        mode_icons = {
            'dice': '🎲',
            'darts': '🎯',
            'basketball': '🏀',
            'football': '⚽'
        }
        icon = mode_icons.get(game_mode, '🎮')
        
        # Не показываем кнопку "Играть" самому себе
        if creator_id == call.from_user.id:
            builder.button(text=f"🗑 #{game_id} {icon}({bet:,})", callback_data=f"pvp_cancel:{game_id}")
        else:
            # Две кнопки: Платная и Бесплатная
            builder.button(text=f"⚔️ {icon} {bet:,} 💎", callback_data=f"pvp_join:{game_id}")
            builder.button(text=f"🆓 {icon} Бесплатно", callback_data=f"pvp_join_free:{game_id}")
    
    builder.button(text="🔄 Обновить", callback_data="pvp_list")
    builder.button(text="🔙 Назад", callback_data="pvp_menu")
    
    # Adjust: сначала фильтры (4 кнопки), затем игры (по 2 на строку)
    builder.adjust(4)  # Фильтры в одну строку
    # Игры - по 2 кнопки на строку (платная + бесплатная для одной игры)
    remaining_buttons = len([g for g in games if g[1] != call.from_user.id]) * 2 + len([g for g in games if g[1] == call.from_user.id])
    if remaining_buttons > 0:
        builder.adjust(4, *[2 for _ in range((remaining_buttons + 1) // 2)])  # Фильтры + игры
    
    filter_text = f" (режим: {mode_filter})" if mode_filter else ""
    
    await call.message.edit_text(
        f"🔍 **СПИСОК ДУЭЛЕЙ{filter_text}**\n\nВыберите соперника:\n"
        f"⚔️ - Играть на ставку (Полный выигрыш)\n"
        f"🆓 - Играть бесплатно (50% выигрыша)",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )

@router.callback_query(F.data.startswith("pvp_cancel:"))
async def pvp_cancel(call: types.CallbackQuery):
    game_id = int(call.data.split(":")[1])
    user_id = call.from_user.id
    
    cursor.execute("SELECT creator_id, bet, status FROM pvp_games WHERE id = ?", (game_id,))
    game = cursor.fetchone()
    
    if not game:
        return await call.answer("❌ Игра не найдена", show_alert=True)
    
    if game[0] != user_id:
        return await call.answer("❌ Это не ваша игра!", show_alert=True)
        
    if game[2] != 'waiting':
        return await call.answer("❌ Игра уже началась или завершена!", show_alert=True)
    
    # Возврат средств
    bet = game[1]
    cursor.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (bet, user_id))
    cursor.execute("DELETE FROM pvp_games WHERE id = ?", (game_id,))
    conn.commit()
    
    await call.answer("✅ Игра отменена, деньги возвращены.")
    await pvp_list_games(call)

@router.callback_query(F.data.startswith("pvp_join"))
async def pvp_join(call: types.CallbackQuery):
    is_free = "free" in call.data
    game_id = int(call.data.split(":")[1])
    joiner_id = call.from_user.id
    
    cursor.execute("SELECT creator_id, bet, status, game_mode FROM pvp_games WHERE id = ?", (game_id,))
    game = cursor.fetchone()
    
    if not game:
        return await call.answer("❌ Игра уже не существует", show_alert=True)
        
    creator_id, bet, status, game_mode = game
    
    if status != 'waiting':
        return await call.answer("❌ Игра уже идет или завершена", show_alert=True)
        
    if creator_id == joiner_id:
        return await call.answer("❌ Нельзя играть с самим собой!", show_alert=True)
    
    # Если платный вход - проверяем баланс и списываем
    if not is_free:
        # Проверяем, имеет ли пользователь бесплатные игры
        if db_has_free_games(joiner_id):
            is_free = True  # Пользователь с 50+ победами играет бесплатно
        else:
            joiner_data = db_get_user(joiner_id)
            if joiner_data[0] < bet:
                return await call.answer(f"❌ Недостаточно средств! Нужно {bet:,} 💎", show_alert=True)
            db_update_stats(joiner_id, bet=bet, win=0)
    
    join_type = 'free' if is_free else 'paid'
    
    # Обновление статуса игры с проверкой race condition
    cursor.execute("UPDATE pvp_games SET joiner_id = ?, status = 'active', join_type = ? WHERE id = ? AND status = 'waiting'", 
                   (joiner_id, join_type, game_id))
    
    if cursor.rowcount == 0:
        # Если не удалось обновить (кто-то успел раньше), возвращаем деньги
        if not is_free:
            db_update_stats(joiner_id, bet=0, win=bet)
        conn.commit()
        return await call.answer("❌ Кто-то уже присоединился к этой игре!", show_alert=True)
        
    conn.commit()
    
    pot_display = bet if is_free else bet * 2
    
    # Получаем название режима
    mode_names = {
        'dice': '🎲 Кости',
        'darts': '🎯 Дартс', 
        'basketball': '🏀 Баскетбол',
        'football': '⚽ Футбол'
    }
    mode_name = mode_names.get(game_mode, '🎮 Игра')
    
    # Проверяем, имеет ли присоединившийся игрок бесплатные игры
    joiner_has_free_games = db_has_free_games(joiner_id)
    if joiner_has_free_games:
        is_free = True
        join_type = 'free'
    
    await call.message.edit_text(
        f"⚔️ **ДУЭЛЬ #{game_id} НАЧАЛАСЬ!**\n\n"
        f"🎮 Режим: {mode_name}\n"
        f"👤 **Игрок 1** (Создатель): `{creator_id}`\n"
        f"👤 **Игрок 2** (Соперник): `{joiner_id}` ({'🏆 ВИП Бесплатно' if joiner_has_free_games else '🆓 Бесплатно' if is_free else '💰 Платно'})\n"
        f"💰 Банк раунда: {pot_display:,} 💎\n\n"
        f"🎲 **ПОРЯДОК ХОДА:**\n"
        f"1️⃣ Игрок 1 делает попытку первым\n"
        f"2️⃣ Игрок 2 делает попытку вторым\n\n"
        f"🎯 Победит тот, у кого лучший результат!",
        parse_mode="Markdown"
    )
    
    if game_mode == 'dice':
        await play_dice_game(call, creator_id, joiner_id, bet, is_free, game_id)
    elif game_mode == 'darts':
        await play_darts_game(call, creator_id, joiner_id, bet, is_free, game_id)
    elif game_mode == 'basketball':
        await play_basketball_game(call, creator_id, joiner_id, bet, is_free, game_id)
    elif game_mode == 'football':
        await play_football_game(call, creator_id, joiner_id, bet, is_free, game_id)


async def play_dice_game(call, creator_id, joiner_id, bet, is_free, game_id):
    """Игра в кости - классическая игра"""
    await asyncio.sleep(2)
    await call.message.answer(
        f"🎲 **ХОД ИГРОКА 1** (Создатель)...\n"
        f"👤 Игрок: {creator_id}\n"
        f"💰 Ставка: {bet:,} 💎\n"
        f"🎯 Бросаем кубик!",
        parse_mode="Markdown"
    )
    await asyncio.sleep(1.5)
    
    dice1_msg = await call.message.answer_dice(emoji="🎲")
    val1 = dice1_msg.dice.value
    await asyncio.sleep(3)
    
    await call.message.answer(
        f"🎲 **ХОД ИГРОКА 2** (Соперник)...\n"
        f"👤 Игрок: {joiner_id}\n"
        f"{'🆓 Бесплатный вход' if is_free else '💰 Платный вход'}\n"
        f"🎯 Бросаем кубик!",
        parse_mode="Markdown"
    )
    await asyncio.sleep(1.5)
    
    dice2_msg = await call.message.answer_dice(emoji="🎲")
    val2 = dice2_msg.dice.value
    await asyncio.sleep(3)
    
    # Определение победителя
    await determine_winner(call, creator_id, joiner_id, val1, val2, bet, is_free, game_id, "🎲 Кости")

async def play_darts_game(call, creator_id, joiner_id, bet, is_free, game_id):
    """Игра в дартс - стрельба по мишени"""
    await asyncio.sleep(2)
    await call.message.answer(
        f"🎯 **ХОД ИГРОКА 1** (Создатель)...\n"
        f"👤 Игрок: {creator_id}\n"
        f"💰 Ставка: {bet:,} 💎\n"
        f"🎯 Стреляем в мишень!",
        parse_mode="Markdown"
    )
    await asyncio.sleep(1.5)
    
    darts1_msg = await call.message.answer_dice(emoji="🎯")
    val1 = darts1_msg.dice.value
    await asyncio.sleep(3)
    
    await call.message.answer(
        f"🎯 **ХОД ИГРОКА 2** (Соперник)...\n"
        f"👤 Игрок: {joiner_id}\n"
        f"{'🆓 Бесплатный вход' if is_free else '💰 Платный вход'}\n"
        f"🎯 Стреляем в мишень!",
        parse_mode="Markdown"
    )
    await asyncio.sleep(1.5)
    
    darts2_msg = await call.message.answer_dice(emoji="🎯")
    val2 = darts2_msg.dice.value
    await asyncio.sleep(3)
    
    # Определение победителя
    await determine_winner(call, creator_id, joiner_id, val1, val2, bet, is_free, game_id, "🎯 Дартс")

async def play_basketball_game(call, creator_id, joiner_id, bet, is_free, game_id):
    """Игра в баскетбол - броски в кольцо"""
    await asyncio.sleep(2)
    await call.message.answer(
        f"🏀 **ХОД ИГРОКА 1** (Создатель)...\n"
        f"👤 Игрок: {creator_id}\n"
        f"💰 Ставка: {bet:,} 💎\n"
        f"🏀 Бросаем мяч в кольцо!",
        parse_mode="Markdown"
    )
    await asyncio.sleep(1.5)
    
    basketball1_msg = await call.message.answer_dice(emoji="🏀")
    val1 = basketball1_msg.dice.value
    await asyncio.sleep(3)
    
    await call.message.answer(
        f"🏀 **ХОД ИГРОКА 2** (Соперник)...\n"
        f"👤 Игрок: {joiner_id}\n"
        f"{'🆓 Бесплатный вход' if is_free else '💰 Платный вход'}\n"
        f"🏀 Бросаем мяч в кольцо!",
        parse_mode="Markdown"
    )
    await asyncio.sleep(1.5)
    
    basketball2_msg = await call.message.answer_dice(emoji="🏀")
    val2 = basketball2_msg.dice.value
    await asyncio.sleep(3)
    
    # Определение победителя
    await determine_winner(call, creator_id, joiner_id, val1, val2, bet, is_free, game_id, "🏀 Баскетбол")

async def play_football_game(call, creator_id, joiner_id, bet, is_free, game_id):
    """Игра в футбол - удары по воротам"""
    await asyncio.sleep(2)
    await call.message.answer(
        f"⚽ **ХОД ИГРОКА 1** (Создатель)...\n"
        f"👤 Игрок: {creator_id}\n"
        f"💰 Ставка: {bet:,} 💎\n"
        f"⚽ Бьем по воротам!",
        parse_mode="Markdown"
    )
    await asyncio.sleep(1.5)
    
    football1_msg = await call.message.answer_dice(emoji="⚽")
    val1 = football1_msg.dice.value
    await asyncio.sleep(3)
    
    await call.message.answer(
        f"⚽ **ХОД ИГРОКА 2** (Соперник)...\n"
        f"👤 Игрок: {joiner_id}\n"
        f"{'🆓 Бесплатный вход' if is_free else '💰 Платный вход'}\n"
        f"⚽ Бьем по воротам!",
        parse_mode="Markdown"
    )
    await asyncio.sleep(1.5)
    
    football2_msg = await call.message.answer_dice(emoji="⚽")
    val2 = football2_msg.dice.value
    await asyncio.sleep(3)
    
    # Определение победителя
    await determine_winner(call, creator_id, joiner_id, val1, val2, bet, is_free, game_id, "⚽ Футбол")

async def determine_winner(call, creator_id, joiner_id, val1, val2, bet, is_free, game_id, game_name):
    """Универсальная функция определения победителя"""
    winner_id = None
    result_text = ""
    
    # Логика банка
    # Если платный: Банк = bet * 2. Победитель получает (bet*2)*0.95.
    # Если бесплатный: Банк = bet. 
    #   Если выигрывает Создатель: Получает bet (возврат).
    #   Если выигрывает Бесплатный: Получает bet * 0.5. Создатель получает bet * 0.5 (возврат половины).
    
    if val1 > val2:
        winner_id = creator_id
        result_text = f"🏆 Победил Игрок 1 (`{creator_id}`)!\n\n"
        
        if is_free:
            # Создатель победил бесплатника -> просто возврат ставки
            win_amount = bet
            db_update_stats(creator_id, bet=0, win=win_amount)
            result_text += f"💰 Возврат ставки: {win_amount:,} 💎"
        else:
            # Обычная победа
            total_pot = bet * 2
            commission = int(total_pot * 0.05)
            win_amount = total_pot - commission
            db_update_stats(creator_id, bet=0, win=win_amount)
            result_text += f"💰 Выигрыш: {win_amount:,} 💎 (Комиссия {commission:,})"

    elif val2 > val1:
        winner_id = joiner_id
        result_text = f"🏆 Победил Игрок 2 (`{joiner_id}`)!\n\n"
        
        if is_free:
            # Бесплатник победил -> получает 50% от ставки создателя
            win_amount = int(bet * 0.5)
            creator_refund = int(bet * 0.5)
            
            db_update_stats(joiner_id, bet=0, win=win_amount)
            db_update_stats(creator_id, bet=0, win=creator_refund) # Возврат половины создателю
            
            result_text += f"💰 Выигрыш (50%): {win_amount:,} 💎\n(Создателю возвращено {creator_refund:,} 💎)"
        else:
            # Обычная победа
            total_pot = bet * 2
            commission = int(total_pot * 0.05)
            win_amount = total_pot - commission
            db_update_stats(joiner_id, bet=0, win=win_amount)
            result_text += f"💰 Выигрыш: {win_amount:,} 💎 (Комиссия {commission:,})"
            
    else:
        # Ничья
        result_text = f"🤝 **НИЧЬЯ!** ({val1} vs {val2})\n\n💰 Ставки возвращены."
        
        # Возврат создателю
        cursor.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (bet, creator_id))
        # Возврат джойнеру (если платил)
        if not is_free:
            cursor.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (bet, joiner_id))
        conn.commit()

    # Запись результата
    cursor.execute("UPDATE pvp_games SET status = 'finished', winner_id = ? WHERE id = ?", (winner_id, game_id))
    
    # Увеличиваем счетчик PVP побед для победителя
    if winner_id:
        new_pvp_wins = db_increment_pvp_wins(winner_id)
        
        # Проверяем достижение 50 побед
        if new_pvp_wins == 50:
            # Отправляем поздравление победителю
            try:
                congrats_text = (
                    "🎉 **Ура!** 🎉\n\n"
                    "Вы достигли **50 ПОБЕД** в PVP арене!\n\n"
                    "🏆 **Ваша награда:** Бесплатный доступ ко всем играм!\n"
                    "Теперь вы можете играть в любые игры без ставок!\n\n"
                    "Спасибо за участие в нашем казино!"
                )
                await safe_send_message(call.message.bot, winner_id, congrats_text, parse_mode="Markdown")
            except Exception as e:
                logger.warning(f"Failed to send congratulations to {winner_id}: {e}")
    
    conn.commit()
    
    # Иконки для результатов
    icons = {
        "🎲 Кости": "🎲",
        "🎯 Дартс": "🎯",
        "🏀 Баскетбол": "🏀",
        "⚽ Футбол": "⚽"
    }
    icon = icons.get(game_name, "🎲")
    
    try:
        await call.message.answer(
            f"{result_text}\n"
            f"{icon} **Результаты:**\n"
            f"Игрок 1: {val1}\n"
            f"Игрок 2: {val2}\n"
            f"{'🏆 Победил Игрок 1!' if val1 > val2 else '🏆 Победил Игрок 2!' if val2 > val1 else '🤝 Ничья!'}\n"
            f"Разница: {abs(val1 - val2) if val1 != val2 else 0}",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.warning(f"Failed to send game results: {e}")
    
    # Уведомления в ЛС
    msg = f"⚔️ **Дуэль #{game_id} ({game_name}) завершена!**\nСчет: {val1}:{val2}\n"
    if winner_id == creator_id: msg += "🏆 Вы победили!"
    elif winner_id == joiner_id: msg += "💀 Вы проиграли."
    else: msg += "🤝 Ничья."
    await safe_send_message(call.message.bot, creator_id, msg, parse_mode="Markdown")
    
    if joiner_id != call.from_user.id:
        await safe_send_message(call.message.bot, joiner_id, msg, parse_mode="Markdown")

@router.callback_query(F.data == "pvp_my")
async def pvp_my_games(call: types.CallbackQuery):
    user_id = call.from_user.id
    cursor.execute(
        "SELECT id, bet, status FROM pvp_games WHERE creator_id = ? AND status = 'waiting' ORDER BY id DESC",
        (user_id,)
    )
    games = cursor.fetchall()
    
    if not games:
        return await call.answer("❌ У вас нет активных заявок", show_alert=True)
    
    builder = InlineKeyboardBuilder()
    for game in games:
        game_id, bet, status = game
        builder.button(text=f"🗑 Отменить #{game_id} ({bet:,})", callback_data=f"pvp_cancel:{game_id}")
    
    builder.button(text="🔙 Назад", callback_data="pvp_menu")
    builder.adjust(1)
    
    await call.message.edit_text(
        "📋 **ВАШИ АКТИВНЫЕ ЗАЯВКИ**",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
