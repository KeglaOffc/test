import asyncio
import random
from aiogram import Router, types
from aiogram.filters import Command
# Добавляем импорт ошибки для обработки флуда
from aiogram.exceptions import TelegramRetryAfter 
# Импортируем нужные функции из базы и вспомогательную проверку
from database import db_get_user, db_update_stats, cursor, conn
from Handlers.common import check_user 

router = Router()

@router.message(Command("slot", "slots", "football", "basket"))
async def play_animated_games(message: types.Message):
    user_data = await check_user(message)
    if not user_data: return
    
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        cmd = message.text.split()[0]
        return await message.reply(f"📝 Формат: {cmd} [ставка]")
    
    bet = int(args[1])
    
    # --- ПРОВЕРКА БЕЗЛИМИТА ---
    is_no_limit = user_data[9] == 777
    if not is_no_limit and bet > 1000000:
        return await message.reply("❌ Максимальная ставка — 1,000,000 💎\n🛒 Купите 'Безлимит' в /shop, чтобы ставить больше!")
    
    if bet > user_data[0] or bet < 10:
        return await message.reply(f"❌ Некорректная ставка. Баланс: {user_data[0]:,}")

    cmd = args[0].lower()
    game_type = "slot"
    emoji = "🎰"
    
    if "football" in cmd:
        game_type = "football"
        emoji = "⚽"
    elif "basket" in cmd:
        game_type = "basket"
        emoji = "🏀"

    # Отправляем дайс и получаем значение
    msg = await message.answer_dice(emoji=emoji)
    val = msg.dice.value

    # --- СИСТЕМА ПОДХВАТА ПОДКРУТКИ ---
    cursor.execute("SELECT rig_type FROM rig_table WHERE user_id = ? AND game = ?", (message.from_user.id, game_type))
    rig = cursor.fetchone()
    
    forced_val = None
    if rig:
        rig_type = rig[0]
        if rig_type == "win":
            if game_type == "slot": forced_val = random.choice([1, 22, 43, 64])
            elif game_type == "football": forced_val = random.choice([3, 4, 5])
            elif game_type == "basket": forced_val = random.choice([4, 5])
        elif rig_type == "lose":
            if game_type == "slot": forced_val = 13
            elif game_type == "football": forced_val = 1
            elif game_type == "basket": forced_val = 1

    if forced_val is not None:
        val = forced_val

    await asyncio.sleep(3.5) # Ожидание анимации
    
    win = 0
    
    # Расчет выигрыша
    if game_type == "slot":
        if val in [1, 22, 43, 64]:
            win = bet * 5
        elif val in [
            2, 3, 4, 5, 6, 7, 8, 10, 11, 14, 15, 16, 19, 21, 
            23, 24, 25, 26, 27, 28, 30, 31, 32, 35, 36, 38, 
            42, 44, 45, 46, 47, 48, 49, 51, 52, 55, 56, 57, 
            62, 63
        ]:
            win = bet * 2
            
    elif game_type == "football":
        if val in [3, 4, 5]: win = int(bet * 1.8)
    elif game_type == "basket":
        if val in [4, 5]: win = int(bet * 1.8)

    # Обновляем БД
    db_update_stats(message.from_user.id, bet, win)
    new_balance = db_get_user(message.from_user.id)[0]

    # --- НОВАЯ ЧАСТЬ: БЕЗОПАСНАЯ ОТПРАВКА ---
    game_res_text = "ВЫИГРЫШ!" if win > 0 else "ПРОИГРЫШ"
    final_text = (
        f"🎰 **РЕЗУЛЬТАТ:** {game_res_text}\n"
        f"💰 Вы получили: `{win:,}` 💎\n"
        f"💳 Баланс: `{new_balance:,}` 💎"
    )

    try:
        await message.reply(final_text, parse_mode="Markdown")
    except TelegramRetryAfter as e:
        # Если словили ограничение (флуд), ждем e.retry_after секунд и пробуем снова
        await asyncio.sleep(e.retry_after)
        try:
            await message.reply(final_text, parse_mode="Markdown")
        except:
            pass # Если не вышло со второго раза, просто молчим, чтобы бот не упал