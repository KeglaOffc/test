from aiogram import Router, types
from aiogram.filters import Command
from aiogram import types, F
# Импортируем все инструменты для работы с БД
from database import cursor, conn, get_real_id, db_get_user, db_get_global_stats

router = Router()
# Твой реальный ID для проверки прав
ADMIN_ID = 5030561581

@router.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.chat.type != "private" or message.from_user.id != ADMIN_ID:
        return 

    stats = db_get_global_stats() 
    
    text = (
        f"👑 <b>АДМИН-ПАНЕЛЬ</b>\n\n"
        f"👥 Игроков: <code>{stats[0]}</code>\n"
        f"💰 Банк: <code>{stats[1] if stats[1] else 0:,}</code> 💎\n\n"
        f"<b>Команды (Ник или ID):</b>\n"
        f"⚙️ <code>/rig [Кто] [win/lose/off]</code> — общая подкрутка\n"
        f"🕹 <code>/podk [Кто] [игра] [win/lose/off]</code> — на конкретную игру\n"
        f"💎 <code>/setbal [Кто] [сумма]</code> — выдать баланс\n"
        f"🚫 <code>/ban [Кто]</code> — забанить/разбанить\n"
        f"🔍 <code>/info [Кто]</code> — данные игрока\n"
        f"📢 <code>/broadcast [текст]</code> — рассылка всем\n"
        f"   <code>/show_mines [ID_игрока]</code> - глянуть мины\n\n"
        f"<b>Список игр для /podk:</b>\n"
        f"<code>slot</code>, <code>football</code>, <code>basket</code>, <code>dice</code>, <code>darts</code>"
    )
    await message.answer(text, parse_mode="HTML")

@router.message(Command("setbal"))
async def admin_setbal(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        args = message.text.split()
        target = args[1]
        amt = args[2]
        
        real_id = get_real_id(target)
        if not real_id: return await message.answer("❌ Игрок не найден.")

        # Исправлено: используем колонку id вместо user_id
        cursor.execute("UPDATE users SET balance = ? WHERE id = ?", (int(amt), real_id))
        conn.commit()
        await message.answer(f"✅ Баланс игрока <code>{target}</code> (ID: {real_id}) изменен на {int(amt):,} 💎")
    except (IndexError, ValueError):
        await message.answer("📝 Формат: <code>/setbal [Ник/ID] [сумма]</code>")

@router.message(Command("rig"))
async def admin_rig(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        args = message.text.split()
        target = args[1]
        mode = args[2].lower()
        
        if mode not in ['win', 'lose', 'off']:
            return await message.answer("❌ Режимы: win, lose, off")

        real_id = get_real_id(target)
        if not real_id: return await message.answer("❌ Игрок не найден.")

        # Исправлено: используем колонку id вместо user_id
        cursor.execute("UPDATE users SET rigged_mode = ? WHERE id = ?", (mode, real_id))
        conn.commit()
        await message.answer(f"⚙️ Подкрутка для <code>{target}</code> установлена в: <b>{mode}</b>")
    except IndexError:
        await message.answer("📝 Формат: <code>/rig [Ник/ID] [win/lose/off]</code>")

@router.message(Command("podk"))
async def admin_podk(message: types.Message):
    """Индивидуальная подкрутка на конкретную игру в rig_table"""
    if message.from_user.id != ADMIN_ID: return
    try:
        args = message.text.split()
        target = args[1]
        game = args[2].lower()
        mode = args[3].lower()

        real_id = get_real_id(target)
        if not real_id: return await message.answer("❌ Игрок не найден.")

        if mode == "off":
            cursor.execute("DELETE FROM rig_table WHERE user_id = ? AND game = ?", (real_id, game))
            msg = f"✅ Подкрутка для <code>{target}</code> в игре <code>{game}</code> <b>выключена</b>."
        else:
            cursor.execute("""
                INSERT INTO rig_table (user_id, game, rig_type, status) 
                VALUES (?, ?, ?, 'active')
                ON CONFLICT(user_id, game) DO UPDATE SET rig_type = ?, status = 'active'
            """, (real_id, game, mode, mode))
            msg = f"🕹 Подкрутка для <code>{target}</code> в игре <code>{game}</code>: <b>{mode}</b>"
        
        conn.commit()
        await message.answer(msg)
    except IndexError:
        await message.answer("📝 Формат: <code>/podk [Ник/ID] [игра] [win/lose/off]</code>")
        
@router.message(Command("show_mines"))
async def admin_show_mines(message: types.Message):
    if message.from_user.id != 8105418718: return

    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        return await message.answer("❌ Введите ID игрока цифрами.")
    
    target_id = int(args[1])

    # Получаем позы мин и РАЗМЕР поля
    cursor.execute("SELECT mines_pos, field_size FROM mines_games WHERE user_id = ? AND status = 'active'", (target_id,))
    res = cursor.fetchone()

    if not res:
        return await message.answer(f"❌ У игрока {target_id} нет активной игры.")

    mine_positions = [int(x) for x in res[0].split(",")]
    size = res[1] # Это наш 3, 5, 7 или 9

    grid_text = f"🕵️ <b>КАРТА МИН ({size}x{size}):</b>\nID: <code>{target_id}</code>\n\n"
    
    # Рисуем динамическую сетку
    total_cells = size * size
    for i in range(total_cells):
        grid_text += "💣 " if i in mine_positions else "💎 "
        # Делаем перенос строки согласно размеру поля
        if (i + 1) % size == 0:
            grid_text += "\n"

    await message.answer(grid_text, parse_mode="HTML")
    
@router.message(Command("ban"))
async def admin_ban(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        target = message.text.split()[1]
        real_id = get_real_id(target)
        if not real_id: return await message.answer("❌ Игрок не найден.")

        u = db_get_user(real_id)
        new_ban_state = 0 if u[2] else 1
        
        # Исправлено: используем колонку id вместо user_id
        cursor.execute("UPDATE users SET banned = ? WHERE id = ?", (new_ban_state, real_id))
        conn.commit()
        
        res_text = "🚫 Забанен" if new_ban_state else "✅ Разбанен"
        await message.answer(f"{res_text} игрок <code>{target}</code> (ID: {real_id})")
    except IndexError:
        await message.answer("📝 Формат: <code>/ban [Ник/ID]</code>")

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
        
        # Индексы из твоего database.py:
        # 0:balance, 2:banned, 3:total_bets, 4:total_wins, 5:games_played, 6:rigged_mode, 8:custom_id
        
        balance = u[0]
        is_banned = "Да" if u[2] else "Нет"
        total_bets = u[3]
        wins = u[4]
        total_games = u[5]
        rig_mode = u[6]
        nickname = u[8]
        
        # Считаем проигрыши
        losses = total_games - wins
        # Считаем чистый профит (выигрыши минус ставки)
        net_profit = wins - total_bets

        text = (
            f"🔍 <b>ДАННЫЕ ИГРОКА: {target}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🎫 <b>Ник:</b> <code>{nickname}</code>\n"
            f"🔢 <b>ID:</b> <code>{real_id}</code>\n"
            f"💰 <b>Баланс:</b> <code>{balance:,}</code> 💎\n"
            f"⚙️ <b>Режим:</b> <code>{rig_mode}</code>\n"
            f"🚫 <b>В бане:</b> <b>{is_banned}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>СТАТИСТИКА ИГР:</b>\n"
            f"🎮 Всего игр: <code>{total_games}</code>\n"
            f"✅ Побед: <code>{wins}</code>\n"
            f"❌ Проигрышей: <code>{losses}</code>\n"
            f"📈 Чистая прибыль: <code>{net_profit:,}</code> 💎\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        
        await message.answer(text, parse_mode="HTML")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка при получении инфо: {e}")
        
@router.message(Command("broadcast"))
async def admin_bc(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    text = message.text.replace("/broadcast ", "").strip()
    if not text or text == "/broadcast":
        return await message.answer("📝 Введите текст для рассылки.")
    
    cursor.execute("SELECT id FROM users")
    users = cursor.fetchall()
    
    count = 0
    await message.answer(f"🚀 Начинаю рассылку на {len(users)} пользователей...")
    
    for u in users:
        try:
            await message.bot.send_message(u[0], text)
            count += 1
            if count % 20 == 0: await asyncio.sleep(0.5) # Защита от спам-фильтра
        except Exception:
            continue
            
    await message.answer(f"✅ Рассылка завершена. Получили: {count} чел.")