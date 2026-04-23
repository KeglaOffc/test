from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
import asyncio
import time
import os
# Импортируем все инструменты для работы с БД
from database import cursor, conn, get_real_id, db_get_user, db_get_global_stats, set_maintenance_mode, get_maintenance_mode
# Импортируем предметы для майнинга
from Handlers.mining import SHOP_ITEMS

router = Router()
# Твой реальный ID для проверки прав (берется из переменных окружения или дефолтный)
ADMIN_ID = int(os.getenv("ADMIN_ID", 5030561581))

@router.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.chat.type != "private" or message.from_user.id != ADMIN_ID:
        return 

    stats = db_get_global_stats() 
    
    builder = InlineKeyboardBuilder()
    builder.button(text="💰 Управление балансом", callback_data="admin_balance")
    builder.button(text="⚙️ Подкрутка игроков", callback_data="admin_rig")
    builder.button(text="🚫 Блокировка/Разблокировка", callback_data="admin_ban")
    builder.button(text="🔍 Информация о игроке", callback_data="admin_info")
    builder.button(text="📊 Статистика бота", callback_data="admin_stats")
    builder.button(text="⭐ Выдать предметы", callback_data="admin_items")
    builder.button(text="⛏️ Управление майнингом", callback_data="admin_mining")
    builder.button(text="📢 Рассылка", callback_data="admin_broadcast")
    builder.button(text="🎮 Управление игроками", callback_data="admin_players")
    
    # Кнопка тех. работ
    is_maint = get_maintenance_mode()
    maint_text = "🟢 Тех. работы: ВЫКЛ" if not is_maint else "🔴 Тех. работы: ВКЛ"
    builder.button(text=maint_text, callback_data="admin_toggle_maintenance")
    
    builder.adjust(1)
    
    text = (
        f"👑 <b>АДМИН-ПАНЕЛЬ КАЗИНО</b>\n\n"
        f"<b>📊 ОБЩАЯ СТАТИСТИКА:</b>\n"
        f"👥 Игроков: <code>{stats[0] if stats[0] else 0}</code>\n"
        f"💰 Общий банк: <code>{stats[1] if stats[1] else 0:,}</code> 💎\n\n"
        f"<b>⚡ БЫСТРЫЕ КОМАНДЫ:</b>\n"
        f"<code>/setbal [Кто] [сумма]</code> - установить баланс\n"
        f"<code>/rig [Кто] [win/lose/off]</code> - подкрутка\n"
        f"<code>/podk [Кто] [игра] [mode]</code> - подкрутка игры\n"
        f"<code>/ban [Кто]</code> - блокировка\n"
        f"<code>/info [Кто]</code> - информация\n"
        f"<code>/additem [Кто] [предмет] [кол-во]</code> - выдать предмет\n"
        f"<code>/getbans</code> - список забанненых\n"
        f"<code>/reset_user [ID]</code> - сброс игрока\n"
        f"<code>/show_mines [ID]</code> - карта мин\n"
        f"<code>/broadcast [текст]</code> - рассылка\n"
        f"<code>/maintenance [on/off]</code> - тех. работы\n\n"
        f"Нажми кнопки ниже для подробного управления."
    )
    await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")

@router.callback_query(F.data == "admin_toggle_maintenance")
async def admin_toggle_maintenance(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    
    current_state = get_maintenance_mode()
    new_state = not current_state
    set_maintenance_mode(new_state)
    
    state_text = "ВКЛЮЧЕНЫ" if new_state else "ВЫКЛЮЧЕНЫ"
    await call.answer(f"🔧 Технические работы {state_text}")
    
    # Обновляем меню
    await admin_panel(call.message)

@router.message(Command("maintenance"))
async def admin_maintenance_cmd(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        arg = message.text.split()[1].lower()
        if arg in ["on", "1", "true"]:
            set_maintenance_mode(True)
            await message.answer("🔴 <b>Технические работы ВКЛЮЧЕНЫ</b>\nБот доступен только администраторам.", parse_mode="HTML")
        elif arg in ["off", "0", "false"]:
            set_maintenance_mode(False)
            await message.answer("🟢 <b>Технические работы ВЫКЛЮЧЕНЫ</b>\nБот доступен всем.", parse_mode="HTML")
        else:
            await message.answer("📝 Используйте: <code>/maintenance [on/off]</code>", parse_mode="HTML")
    except IndexError:
        state = "ВКЛЮЧЕНЫ" if get_maintenance_mode() else "ВЫКЛЮЧЕНЫ"
        await message.answer(f"🔧 Статус тех. работ: <b>{state}</b>\nДля изменения: <code>/maintenance [on/off]</code>", parse_mode="HTML")

# === CALLBACK HANDLERS ===
@router.callback_query(F.data == "admin_balance")
async def admin_balance_menu(call: types.CallbackQuery):
    text = (
        "<b>💰 УПРАВЛЕНИЕ БАЛАНСОМ</b>\n\n"
        "Используй команды:\n"
        "<code>/setbal [Ник/ID] [сумма]</code> - установить точную сумму\n"
        "<code>/addbal [Ник/ID] [сумма]</code> - добавить сумму\n"
        "<code>/subbal [Ник/ID] [сумма]</code> - отнять сумму\n"
        "<code>/reset_money [Ник/ID]</code> - обнулить баланс\n\n"
        "Пример: /setbal 123456789 100000"
    )
    await call.message.edit_text(text, parse_mode="HTML")

@router.callback_query(F.data == "admin_rig")
async def admin_rig_menu(call: types.CallbackQuery):
    text = (
        "<b>⚙️ СИСТЕМА ПОДКРУТКИ</b>\n\n"
        "❌ <b>ПОДКРУТКА ОТКЛЮЧЕНА</b>\n"
        "В данный момент все игры работают в честном режиме.\n"
        "Команды /rig и /podk деактивированы."
    )
    await call.message.edit_text(text, parse_mode="HTML")

@router.callback_query(F.data == "admin_ban")
async def admin_ban_menu(call: types.CallbackQuery):
    text = (
        "<b>🚫 БЛОКИРОВКА ИГРОКОВ</b>\n\n"
        "Забанить/Разбанить:\n"
        "<code>/ban [Ник/ID]</code>\n\n"
        "Посмотреть забанненых:\n"
        "<code>/getbans</code>\n\n"
        "Полностью удалить игрока:\n"
        "<code>/deluser [ID]</code>\n\n"
        "Это необратимо!"
    )
    await call.message.edit_text(text, parse_mode="HTML")

@router.callback_query(F.data == "admin_info")
async def admin_info_menu(call: types.CallbackQuery):
    text = (
        "<b>🔍 ИНФОРМАЦИЯ О ИГРОКАХ</b>\n\n"
        "Получить всю информацию:\n"
        "<code>/info [Ник/ID]</code>\n\n"
        "Показать карту мин:\n"
        "<code>/show_mines [ID]</code>\n\n"
        "Полный список всех игроков:\n"
        "<code>/allplayers</code>"
    )
    await call.message.edit_text(text, parse_mode="HTML")

@router.callback_query(F.data == "admin_stats")
async def admin_stats_menu(call: types.CallbackQuery):
    stats = db_get_global_stats()
    
    cursor.execute("SELECT COUNT(*) FROM users WHERE banned = 1")
    banned_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM daily_stats WHERE profit > 0")
    winners_today = cursor.fetchone()[0]
    
    text = (
        "<b>📊 СТАТИСТИКА БОТА</b>\n\n"
        f"👥 Всего игроков: <code>{stats[0] if stats[0] else 0}</code>\n"
        f"💰 Общий банк: <code>{stats[1] if stats[1] else 0:,}</code> 💎\n"
        f"🚫 Забанено: <code>{banned_count}</code>\n"
        f"🏆 Выигравших сегодня: <code>{winners_today}</code>\n"
    )
    await call.message.edit_text(text, parse_mode="HTML")

@router.callback_query(F.data == "admin_items")
async def admin_items_menu(call: types.CallbackQuery):
    text = (
        "<b>⭐ ВЫДАЧА ПРЕДМЕТОВ</b>\n\n"
        "Используй команду:\n"
        "<code>/additem [Ник/ID] [предмет] [кол-во]</code>\n\n"
        "Доступные предметы:\n"
        "• mine_shield - саперный щит\n"
        "• mine_scan - сканер мин\n"
        "• energy_drink - энергетик\n"
        "• gold_ticket - золотой билет\n"
        "• rerolls - переброс кубика\n"
        "• bet_insure - страховка\n\n"
        "Пример: /additem player1 energy_drink 5"
    )
    await call.message.edit_text(text, parse_mode="HTML")

@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_menu(call: types.CallbackQuery):
    text = (
        "<b>📢 РАССЫЛКА ПО ВСЕМ ИГРОКАМ</b>\n\n"
        "Отправить сообщение:\n"
        "<code>/broadcast [текст]</code>\n\n"
        "Пример:\n"
        "/broadcast 🎉 Сегодня УДВОЕННАЯ награда в лотерее!"
    )
    await call.message.edit_text(text, parse_mode="HTML")

@router.callback_query(F.data == "admin_players")
async def admin_players_menu(call: types.CallbackQuery):
    text = (
        "<b>🎮 УПРАВЛЕНИЕ ИГРОКАМИ</b>\n\n"
        "Полный сброс игрока:\n"
        "<code>/reset_user [ID]</code>\n\n"
        "Обнулить баланс:\n"
        "<code>/reset_money [ID]</code>\n\n"
        "Удалить игрока:\n"
        "<code>/deluser [ID]</code>\n\n"
        "Список забанено:\n"
        "<code>/getbans</code>\n\n"
        "Все игроки:\n"
        "<code>/allplayers</code>"
    )
    await call.message.edit_text(text, parse_mode="HTML")

@router.callback_query(F.data == "admin_mining")
async def admin_mining_menu(call: types.CallbackQuery):
    text = (
        "<b>⛏️ УПРАВЛЕНИЕ МАЙНИНГОМ</b>\n\n"
        "Дать железо:\n"
        "<code>/mine_add [ID] [cpu_s9/gpu_4090/...]  [кол-во]</code>\n\n"
        "Установить мощь:\n"
        "<code>/mine_set [ID] [мощь hs]</code>\n\n"
        "Установить потребление:\n"
        "<code>/mine_watt [ID] [потребление W]</code>\n\n"
        "Сброс фермы:\n"
        "<code>/mine_reset [ID]</code>\n\n"
        "Дать энергетики:\n"
        "<code>/mine_boost [ID] [кол-во]</code>"
    )
    await call.message.edit_text(text, parse_mode="HTML")

# === КОМАНДЫ ===

@router.message(Command("setbal"))
async def admin_setbal(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        args = message.text.split()
        target = args[1]
        amt = int(args[2])
        
        real_id = get_real_id(target)
        if not real_id: return await message.answer("❌ Игрок не найден.")

        cursor.execute("UPDATE users SET balance = ? WHERE id = ?", (amt, real_id))
        conn.commit()
        await message.answer(f"✅ Баланс <code>{target}</code> установлен на {amt:,} 💎", parse_mode="HTML")
    except (IndexError, ValueError):
        await message.answer("📝 Формат: <code>/setbal [Ник/ID] [сумма]</code>", parse_mode="HTML")

@router.message(Command("addbal"))
async def admin_addbal(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        args = message.text.split()
        target = args[1]
        amt = int(args[2])
        
        real_id = get_real_id(target)
        if not real_id: return await message.answer("❌ Игрок не найден.")

        cursor.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (amt, real_id))
        conn.commit()
        await message.answer(f"✅ Добавлено {amt:,} 💎 игроку <code>{target}</code>", parse_mode="HTML")
    except (IndexError, ValueError):
        await message.answer("📝 Формат: <code>/addbal [Ник/ID] [сумма]</code>", parse_mode="HTML")

@router.message(Command("subbal"))
async def admin_subbal(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        args = message.text.split()
        target = args[1]
        amt = int(args[2])
        
        real_id = get_real_id(target)
        if not real_id: return await message.answer("❌ Игрок не найден.")

        cursor.execute("UPDATE users SET balance = MAX(0, balance - ?) WHERE id = ?", (amt, real_id))
        conn.commit()
        await message.answer(f"✅ Отнято {amt:,} 💎 у игрока <code>{target}</code>", parse_mode="HTML")
    except (IndexError, ValueError):
        await message.answer("📝 Формат: <code>/subbal [Ник/ID] [сумма]</code>", parse_mode="HTML")

@router.message(Command("rig"))
async def admin_rig(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("❌ Подкрутка отключена. Игра честная!", parse_mode="HTML")

@router.message(Command("podk"))
async def admin_podk(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer("❌ Подкрутка отключена. Игра честная!", parse_mode="HTML")

@router.message(Command("ban"))
async def admin_ban(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        target = message.text.split()[1]
        real_id = get_real_id(target)
        if not real_id: return await message.answer("❌ Игрок не найден.")

        u = db_get_user(real_id)
        new_ban_state = 0 if u[2] else 1
        
        cursor.execute("UPDATE users SET banned = ? WHERE id = ?", (new_ban_state, real_id))
        conn.commit()
        
        res_text = "🚫 Забанен" if new_ban_state else "✅ Разбанен"
        await message.answer(f"{res_text} игрок <code>{target}</code> (ID: {real_id})", parse_mode="HTML")
    except IndexError:
        await message.answer("📝 Формат: <code>/ban [Ник/ID]</code>", parse_mode="HTML")

@router.message(Command("getbans"))
async def admin_getbans(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    
    cursor.execute("SELECT id, custom_id, balance FROM users WHERE banned = 1 ORDER BY id DESC")
    banned = cursor.fetchall()
    
    if not banned:
        return await message.answer("✅ Забанненых игроков нет!")
    
    text = "<b>🚫 СПИСОК ЗАБАННЕНЫХ:</b>\n\n"
    for uid, nick, balance in banned[:50]:
        text += f"🔴 ID: <code>{uid}</code> | Ник: <code>{nick or uid}</code> | Баланс: {balance:,} 💎\n"
    
    await message.answer(text, parse_mode="HTML")

@router.message(Command("allplayers"))
async def admin_allplayers(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    
    cursor.execute("SELECT COUNT(*) FROM users")
    total = cursor.fetchone()[0]
    
    cursor.execute("SELECT id, custom_id, balance FROM users ORDER BY balance DESC LIMIT 20")
    top_players = cursor.fetchall()
    
    text = f"<b>🎮 ТОП ИГРОКОВ ({total} всего)</b>\n\n"
    for i, (uid, nick, balance) in enumerate(top_players, 1):
        text += f"{i}. <code>{nick or uid}</code> - {balance:,} 💎\n"
    
    await message.answer(text, parse_mode="HTML")

@router.message(Command("info"))
async def admin_info(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        args = message.text.split()
        if len(args) < 2:
            return await message.answer("📝 Формат: <code>/info [Ник/ID]</code>", parse_mode="HTML")
            
        target = args[1]
        real_id = get_real_id(target)
        if not real_id: 
            return await message.answer("❌ Игрок не найден.")
            
        u = db_get_user(real_id)
        
        balance = u[0]
        is_banned = "🚫 Да" if u[2] else "✅ Нет"
        total_bets = u[3]
        wins = u[4]
        total_games = u[5]
        rig_mode = u[6]
        nickname = u[8]
        
        losses = total_games - wins
        net_profit = wins - total_bets

        text = (
            f"🔍 <b>ДАННЫЕ ИГРОКА: {target}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🎫 Ник: <code>{nickname}</code>\n"
            f"🔢 ID: <code>{real_id}</code>\n"
            f"💰 Баланс: <code>{balance:,}</code> 💎\n"
            f"⚙️ Подкрутка: <code>{rig_mode}</code>\n"
            f"🚫 В бане: {is_banned}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📊 СТАТИСТИКА:\n"
            f"🎮 Игр: <code>{total_games}</code>\n"
            f"✅ Побед: <code>{wins}</code>\n"
            f"❌ Проигрышей: <code>{losses}</code>\n"
            f"📈 Профит: <code>{net_profit:,}</code> 💎\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        
        await message.answer(text, parse_mode="HTML")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@router.message(Command("additem"))
async def admin_additem(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        args = message.text.split()
        target = args[1]
        item = args[2]
        amount = int(args[3])
        
        real_id = get_real_id(target)
        if not real_id: return await message.answer("❌ Игрок не найден.")
        
        items = ["mine_shield", "mine_scan", "energy_drink", "gold_ticket", "rerolls", "bet_insure"]
        if item not in items:
            return await message.answer(f"❌ Неизвестный предмет. Доступные: {', '.join(items)}")
        
        cursor.execute(f"UPDATE users SET {item} = COALESCE({item}, 0) + ? WHERE id = ?", (amount, real_id))
        conn.commit()
        
        await message.answer(f"✅ Выдано {amount} x <code>{item}</code> игроку <code>{target}</code>", parse_mode="HTML")
    except (IndexError, ValueError):
        await message.answer("📝 Формат: <code>/additem [Ник/ID] [предмет] [кол-во]</code>", parse_mode="HTML")

@router.message(Command("show_mines"))
async def admin_show_mines(message: types.Message):
    if message.from_user.id != ADMIN_ID: return

    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        return await message.answer("❌ Введите ID игрока цифрами.")
    
    target_id = int(args[1])

    cursor.execute("SELECT mines_pos, field_size FROM mines_games WHERE user_id = ? AND status = 'active'", (target_id,))
    res = cursor.fetchone()

    if not res:
        return await message.answer(f"❌ У игрока {target_id} нет активной игры.")

    mine_positions = [int(x) for x in res[0].split(",")]
    size = res[1]

    grid_text = f"🕵️ <b>КАРТА МИН ({size}x{size})</b>\nID: <code>{target_id}</code>\n\n"
    
    total_cells = size * size
    for i in range(total_cells):
        grid_text += "💣 " if i in mine_positions else "💎 "
        if (i + 1) % size == 0:
            grid_text += "\n"

    await message.answer(grid_text, parse_mode="HTML")

# Функция broadcast перенесена в новый раздел РАССЫЛКА В ЧАТЫ (смотри ниже)

@router.message(Command("reset_user"))
async def admin_reset_user(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        real_id = int(message.text.split()[1])
        
        cursor.execute("""
            UPDATE users SET 
            balance = 5000, 
            total_bets = 0, 
            total_wins = 0, 
            games_played = 0,
            rigged_mode = 'off'
            WHERE id = ?
        """, (real_id,))
        conn.commit()
        
        await message.answer(f"✅ Игрок {real_id} полностью сброшен!")
    except (IndexError, ValueError):
        await message.answer("📝 Формат: <code>/reset_user [ID]</code>", parse_mode="HTML")

@router.message(Command("deluser"))
async def admin_deluser(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        real_id = int(message.text.split()[1])
        
        cursor.execute("DELETE FROM users WHERE id = ?", (real_id,))
        cursor.execute("DELETE FROM daily_stats WHERE user_id = ?", (real_id,))
        cursor.execute("DELETE FROM mines_games WHERE user_id = ?", (real_id,))
        conn.commit()
        
        await message.answer(f"✅ Игрок {real_id} удален из системы!")
    except (IndexError, ValueError):
        await message.answer("📝 Формат: <code>/deluser [ID]</code>", parse_mode="HTML")

# ========== КОМАНДЫ МАЙНИНГА ==========

@router.message(Command("mine_add"))
async def admin_mine_add(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        args = message.text.split()
        if len(args) < 4:
            return await message.answer("📝 Формат: <code>/mine_add [ID] [предмет] [кол-во]</code>", parse_mode="HTML")
        
        user_id = int(args[1])
        item_name = args[2]
        amount = int(args[3])
        
        if item_name not in SHOP_ITEMS:
            return await message.answer(f"❌ Предмет '{item_name}' не найден.")
        
        item = SHOP_ITEMS[item_name]
        
        # Проверяем есть ли ферма
        cursor.execute("SELECT * FROM mining_farms WHERE user_id = ?", (user_id,))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO mining_farms (user_id) VALUES (?)", (user_id,))
            conn.commit()
        
        for _ in range(amount):
            cursor.execute("INSERT INTO mining_items (user_id, name, hs, watt, wear, lvl) VALUES (?, ?, ?, ?, 100, 1)",
                          (user_id, item['name'], item['hs'], item['watt']))
        conn.commit()
        
        await message.answer(f"✅ Добавлено {amount} x {item['name']} игроку {user_id}", parse_mode="HTML")
    except (IndexError, ValueError):
        await message.answer("📝 Формат: <code>/mine_add [ID] [предмет] [кол-во]</code>", parse_mode="HTML")

@router.message(Command("mine_set"))
async def admin_mine_set(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        args = message.text.split()
        user_id = int(args[1])
        hs = int(args[2])
        
        cursor.execute("UPDATE mining_farms SET total_hs = ? WHERE user_id = ?", (hs, user_id))
        conn.commit()
        await message.answer(f"✅ Мощность фермы игрока {user_id} установлена на {hs} H/s", parse_mode="HTML")
    except (IndexError, ValueError):
        await message.answer("📝 Формат: <code>/mine_set [ID] [мощь]</code>", parse_mode="HTML")

@router.message(Command("mine_watt"))
async def admin_mine_watt(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        args = message.text.split()
        user_id = int(args[1])
        watt = int(args[2])
        
        cursor.execute("UPDATE mining_farms SET total_watt = ? WHERE user_id = ?", (watt, user_id))
        conn.commit()
        await message.answer(f"✅ Потребление фермы игрока {user_id} установлено на {watt} W/h", parse_mode="HTML")
    except (IndexError, ValueError):
        await message.answer("📝 Формат: <code>/mine_watt [ID] [потребление]</code>", parse_mode="HTML")

@router.message(Command("mine_reset"))
async def admin_mine_reset(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        user_id = int(message.text.split()[1])
        
        cursor.execute("DELETE FROM mining_items WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM mining_farms WHERE user_id = ?", (user_id,))
        conn.commit()
        
        await message.answer(f"✅ Ферма игрока {user_id} полностью сброшена", parse_mode="HTML")
    except (IndexError, ValueError):
        await message.answer("📝 Формат: <code>/mine_reset [ID]</code>", parse_mode="HTML")

@router.message(Command("mine_boost"))
async def admin_mine_boost(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        args = message.text.split()
        user_id = int(args[1])
        amount = int(args[2])
        
        cursor.execute("UPDATE users SET energy_drink = COALESCE(energy_drink, 0) + ? WHERE id = ?", (amount, user_id))
        conn.commit()
        
        await message.answer(f"✅ Выдано {amount} энергетиков игроку {user_id}", parse_mode="HTML")
    except (IndexError, ValueError):
        await message.answer("📝 Формат: <code>/mine_boost [ID] [кол-во]</code>", parse_mode="HTML")

# ========== РАССЫЛКА В ЧАТЫ ==========

@router.message(Command("bcgroup"))
async def admin_broadcast_group(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        args = message.text.split(maxsplit=2)
        if len(args) < 3:
            return await message.answer("📝 Формат: <code>/bcgroup [ID группы] [текст]</code>", parse_mode="HTML")
        
        group_id = int(args[1])
        text = args[2]
        
        try:
            await message.bot.send_message(group_id, text, parse_mode="HTML")
            await message.answer(f"✅ Сообщение отправлено в чат {group_id}", parse_mode="HTML")
        except Exception as e:
            await message.answer(f"❌ Ошибка: {str(e)}", parse_mode="HTML")
    except (IndexError, ValueError):
        await message.answer("📝 Формат: <code>/bcgroup [ID группы] [текст]</code>", parse_mode="HTML")

@router.message(Command("broadcast"))
async def admin_broadcast_all(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    text = message.text.replace("/broadcast ", "").strip()
    if not text or text == "/broadcast":
        return await message.answer("📝 Введите текст для рассылки.")
    
    cursor.execute("SELECT id FROM users WHERE banned = 0")
    users = cursor.fetchall()
    
    count = 0
    msg = await message.answer(f"🚀 Начинаю рассылку на {len(users)} пользователей...")
    
    for u in users:
        try:
            await message.bot.send_message(u[0], text, parse_mode="HTML")
            count += 1
            if count % 20 == 0: await asyncio.sleep(0.5)
        except Exception:
            continue
            
    await msg.edit_text(f"✅ Рассылка завершена. Получили: {count}/{len(users)} чел.")

@router.message(Command("bchelp"))
async def admin_bc_help(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    text = (
        "<b>📢 СПРАВКА ПО РАССЫЛКЕ</b>\n\n"
        "Рассылка всем игрокам:\n"
        "<code>/broadcast [текст]</code>\n\n"
        "Рассылка в конкретный чат/группу:\n"
        "<code>/bcgroup [ID группы] [текст]</code>\n\n"
        "<b>ПРИМЕРЫ ТЕКСТА:</b>\n"
        "🎉 Сегодня удвоенная награда в лотерее!\n"
        "⚠️ Техническое обслуживание: +10% ко всем выигрышам\n"
        "📱 Установите наш бота в групповой чат: /start\n\n"
        "<i>Поддержка форматирования:</i> **жирный**, __подчеркивание__, ~~зачеркивание__"
    )
    await message.answer(text, parse_mode="HTML")