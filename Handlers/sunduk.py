import random
import logging
import time
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Импортируем функции БД и общую проверку
from database import db_get_user, db_update_stats, cursor, conn
from Handlers.common import check_user

logger = logging.getLogger(__name__)
router = Router()

# Защита от spam
CHEST_COOLDOWN = {}

# --- РЕЖИМЫ СУНДУКОВ ---
MODES = {
    "normal": {"name": "Обычный", "emoji": "📦", "chests": 3, "multiplier": 1.0},
    "extreme": {"name": "Экстрим", "emoji": "🔥", "chests": 5, "multiplier": 2.0},
    "mega": {"name": "Мега", "emoji": "💎", "chests": 10, "multiplier": 3.0}
}
@router.message(Command("chests"))
async def chests_start(message: types.Message):
    try:
        user_data = await check_user(message)
        if not user_data: 
            return
            
        args = message.text.split()
        if len(args) < 2 or not args[1].isdigit(): 
            return await message.reply("📝 Использование: /chests [ставка] [режим]\n\nРежимы: normal, extreme, mega")
        
        bet = int(args[1])
        mode = args[2].lower() if len(args) > 2 else "normal"
        
        if mode not in MODES:
            return await message.reply(f"❌ Неизвестный режим. Доступные: {', '.join(MODES.keys())}")
        
        if bet < 10:
            return await message.reply("❌ Минимальная ставка — 10 💎")
            
        if bet > user_data[0]: 
            return await message.reply(f"❌ Недостаточно средств. Ваш баланс: {user_data[0]:,} 💎")

        mode_info = MODES[mode]
        builder = InlineKeyboardBuilder()
        
        # Создаем кнопки для выбранного режима
        for i in range(mode_info["chests"]): 
            builder.button(text=mode_info["emoji"], callback_data=f"chest_op:{bet}:{i}:{message.from_user.id}:{mode}")
        
        # Раскладка в зависимости от количества сундуков
        if mode_info["chests"] <= 3:
            builder.adjust(3)
        elif mode_info["chests"] <= 5:
            builder.adjust(3, 2)
        else:
            builder.adjust(4, 3, 3)
        
        await message.answer(
            f"{mode_info['emoji']} <b>{mode_info['name'].upper()} СУНДУКИ</b>\n\n"
            f"Ставка: {bet:,} 💎\n"
            f"Сундуков: {mode_info['chests']}\n"
            f"Множитель награды: x{mode_info['multiplier']}\n\n"
            f"Выбери один из {mode_info['chests']} сундуков:", 
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error in chests_start: {e}")
        await message.reply("❌ Ошибка при запуске игры.")

@router.callback_query(F.data.startswith("chest_op:"))
async def chest_open(call: types.CallbackQuery):
    try:
        user_id = call.from_user.id
        
        # ЗАЩИТА ОТ SPAM (debounce 2 сек)
        current_time = time.time()
        if user_id in CHEST_COOLDOWN:
            if current_time - CHEST_COOLDOWN[user_id] < 2:
                return await call.answer("⏱️ Слишком быстро! Подождите...", show_alert=True)
        CHEST_COOLDOWN[user_id] = current_time
        
        data = call.data.split(":")
        bet = int(data[1])
        if bet <= 0:
             return await call.answer("❌ Некорректная ставка!", show_alert=True)
        choice_idx = int(data[2])
        player_id = int(data[3])
        mode = data[4] if len(data) > 4 else "normal"

        # Проверка, что на кнопку нажал именно тот, кто запустил игру
        if user_id != player_id:
            return await call.answer("🚫 Это не ваша игра!", show_alert=True)

        # ИСПОЛЬЗУЕМ ТРАНЗАКЦИЮ
        try:
            cursor.execute("BEGIN IMMEDIATE")
            
            # Проверяем баланс внутри транзакции
            cursor.execute("SELECT balance FROM users WHERE id = ?", (user_id,))
            res = cursor.fetchone()
            if not res or res[0] < bet:
                cursor.execute("ROLLBACK")
                return await call.message.edit_text("❌ Недостаточно средств.")
            
            # Списываем ставку АТОМАРНО
            cursor.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (bet, user_id))
            
            # Базовый пул множителей
            mode_info = MODES.get(mode, MODES["normal"])
            num_chests = mode_info["chests"]
            mode_mult = mode_info["multiplier"]
            
            # Создаем базовый пул с более интересным распределением
            if mode == "normal":
                base_pool = [2.0, 0.0, 0.5]
            elif mode == "extreme":
                base_pool = [5.0, 2.0, 0.0, 0.5, 1.5]
            elif mode == "mega":
                base_pool = [10.0, 5.0, 2.0, 0.5, 0.2, 0.0, 1.0, 3.0, 1.5, 0.8]
            else:
                base_pool = [2.0, 0.0, 0.5]
            
            # --- ЛОГИКА ПОДКРУТКИ ---
            u_d = db_get_user(user_id)
            status = u_d[6]
            
            if status == 'win':
                # Гарантируем выигрыш
                outcomes = [max(base_pool) * 1.5] * num_chests
            elif status == 'lose':
                # Гарантируем проигрыш
                outcomes = [0.0] * num_chests
            else:
                # Нормальная игра
                if len(base_pool) >= num_chests:
                    outcomes = random.sample(base_pool, num_chests)
                else:
                    outcomes = base_pool.copy()
                    while len(outcomes) < num_chests:
                        outcomes.append(random.uniform(0.1, 2.5))
            
            # Перемешиваем
            random.shuffle(outcomes)
            
            # Результат по выбранному индексу
            mult = outcomes[choice_idx] * mode_mult
            win = int(bet * mult)
            
            # Добавляем выигрыш (ставка уже вычтена)
            cursor.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (win, user_id))
            
            # Обновляем статистику
            if win > 0:
                cursor.execute("UPDATE users SET total_wins = total_wins + ?  WHERE id = ?", (win, user_id))
            cursor.execute("UPDATE users SET total_bets = total_bets + ? WHERE id = ?", (bet, user_id))
            
            cursor.execute("SELECT balance FROM users WHERE id = ?", (user_id,))
            new_balance = cursor.fetchone()[0]
            
            conn.commit()
            
        except Exception as e:
            cursor.execute("ROLLBACK")
            logger.error(f"Error in chest_open transaction: {e}")
            return await call.message.edit_text("❌ Ошибка при открытии сундука.")
        
        # Расчет профита
        profit = win - bet
        profit_text = f"+{profit:,}" if profit >= 0 else f"{profit:,}"

        # Формируем сообщение с результатом
        result_msg = (
            f"{mode_info['emoji']} <b>РЕЗУЛЬТАТ {mode_info['name'].upper()}</b>\n\n"
            f"Сундук №{choice_idx + 1} | Множитель: x{mult:.1f}\n"
            f"📈 Итог: {profit_text} 💎\n"
            f"💵 Баланс: {new_balance:,} 💎"
        )

        # Визуализация содержимого (раскрываем карты)
        reveal_text = "\n\n🔍 Содержимое сундуков:\n"
        for i, m in enumerate(outcomes):
            if i == choice_idx:
                reveal_text += f"{mode_info['emoji']} №{i+1}: {m:.1f}x ← (Твой выбор)\n"
            else:
                reveal_text += f"{mode_info['emoji']} №{i+1}: {m:.1f}x\n"

        await call.message.edit_text(result_msg + reveal_text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error in chest_open: {e}")
        await call.message.edit_text("❌ Ошибка при открытии сундука.")