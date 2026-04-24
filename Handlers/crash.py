import asyncio
import random
import logging
import time
from aiogram import types, Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.exceptions import TelegramBadRequest
from database import db_get_user, db_update_stats, db_get_rig
from Handlers.common import check_user

logger = logging.getLogger(__name__)
CRASH_COOLDOWN = {}

router = Router()

class CrashGame(StatesGroup):
    bet = State()
    waiting_for_start = State()

active_games = {}

@router.message(Command("crash"))
async def start_crash(message: Message, state: FSMContext):
    user_data = await check_user(message)
    if not user_data:
        return
    
    user_id = message.from_user.id
    current_time = time.time()
    if user_id in CRASH_COOLDOWN:
        if current_time - CRASH_COOLDOWN[user_id] < 3:
            return await message.answer("⏱️ Слишком быстро! Подождите...")
    CRASH_COOLDOWN[user_id] = current_time
    
    await message.answer("🚀 <b>ДОБРО ПОЖАЛОВАТЬ В CRASH!</b>\n\n💰 Введите сумму ставки:", parse_mode="HTML")
    await state.set_state(CrashGame.bet)

@router.message(CrashGame.bet)
async def process_bet(message: Message, state: FSMContext):
    try:
        bet = int(message.text)
        user_id = message.from_user.id
        user_data = db_get_user(user_id)
        balance = user_data[0]

        if bet <= 0:
            await message.answer("Ставка должна быть больше нуля.")
            return
        if bet > balance:
            await message.answer("Недостаточно средств.")
            return

        await state.update_data(bet=bet)
        await message.answer(f"Ваша ставка: {bet}\n\nОжидайте начала игры...")
        await asyncio.sleep(2)
        await run_crash_game(message, state)
    except ValueError:
        await message.answer("Пожалуйста, введите число.")

async def run_crash_game(message: Message, state: FSMContext):
    data = await state.get_data()
    bet = data.get("bet")
    user_id = message.from_user.id

    db_update_stats(user_id, bet=bet)

    multiplier = 1.0
    rig = db_get_rig(user_id)
    if rig == "win":
        crash_point = random.uniform(8.0, 15.0)
    elif rig == "lose":
        crash_point = random.uniform(1.0, 1.3)
    else:
        crash_point = random.uniform(1.0, 10.0)
    game_id = f"{user_id}_{int(asyncio.get_event_loop().time())}"
    
    active_games[game_id] = {
        'user_id': user_id,
        'bet': bet,
        'multiplier': multiplier,
        'crashed': False,
        'message_id': None
    }

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Забрать деньги", callback_data=f"cashout_{game_id}")]
    ])
    
    msg = await message.answer("🚀 Игра началась!", reply_markup=keyboard)
    active_games[game_id]['message_id'] = msg.message_id

    try:
        for i in range(1, 101):
            multiplier += 0.15  # Увеличил шаг для более динамичной игры
            await asyncio.sleep(0.4)  # Уменьшил задержку для быстрого роста
            
            text = f"🚀 Множитель: {multiplier:.2f}x"
            
            if i % 2 == 0:
                text += "📈"
            else:
                text += "📉"

            if not active_games[game_id]['crashed']:
                # Обновляем множитель в словаре
                active_games[game_id]['multiplier'] = multiplier
                try:
                    await msg.edit_text(text, reply_markup=keyboard)
                except TelegramBadRequest as e:
                    logger.warning(f"Timeout в CRASH: {e}")

            if multiplier >= crash_point:
                break

        if not active_games[game_id]['crashed']:
            if multiplier >= crash_point:
                # Краш произошел
                try:
                    await msg.edit_text(f"💥 <b>CRASH! Множитель: {multiplier:.2f}x</b>", reply_markup=None, parse_mode="HTML")
                except TelegramBadRequest as e:
                    logger.warning(f"Timeout при краше: {e}")
                await message.answer("❌ <b>Вы проиграли.</b>", parse_mode="HTML")
            else:
                # Игрок долетел до максимума
                win_amount = int(bet * multiplier)
                db_update_stats(user_id, 0, win_amount)
                try:
                    await msg.edit_text(f"🚀 Множитель: {multiplier:.2f}x\n🎉 <b>Автовывод!</b>", reply_markup=None, parse_mode="HTML")
                except TelegramBadRequest as e:
                    logger.warning(f"Timeout при автовывода: {e}")
                await message.answer(f"🎉 Вы долетели до максимума! Выигрыш: {win_amount:,} 💎", parse_mode="HTML")
        
    except Exception as e:
        print(f"Ошибка в игре: {e}")
    finally:
        if game_id in active_games:
            del active_games[game_id]
        await state.clear()

@router.callback_query(F.data.startswith("cashout_"))
async def cashout_handler(callback: CallbackQuery):
    try:
        game_id = callback.data.replace("cashout_", "")
        user_id = callback.from_user.id
        
        if game_id not in active_games:
            return await callback.answer("🚫 Игра уже завершена или не найдена.", show_alert=True)

        crash_point = active_games[game_id].get('crash_point', 999999)
        
        if active_games[game_id]['user_id'] != user_id:
            return await callback.answer("🚫 Это не ваша игра!", show_alert=True)
        
        if active_games[game_id]['crashed']:
            return await callback.answer("🚫 Игра уже завершена.", show_alert=True)
        
        # Дополнительная проверка: не крашнулось ли уже
        if active_games[game_id]['multiplier'] >= crash_point:
             return await callback.answer("⏰ Слишком поздно! Краш уже произошел.", show_alert=True)

        active_games[game_id]['crashed'] = True
        bet = active_games[game_id]['bet']
        multiplier = active_games[game_id]['multiplier']
        
        win_amount = int(bet * multiplier)
        db_update_stats(user_id, 0, win_amount)
        
        try:
            await callback.message.edit_text(
                f"🎉 <b>Вы забрали деньги!</b>\n"
                f"💰 Выигрыш: {win_amount:,} 💎\n"
                f"📈 Множитель: {multiplier:.2f}x",
                parse_mode="HTML"
            )
        except TelegramBadRequest as e:
            logger.warning(f"Timeout при выводе: {e}")
        
        await callback.answer(f"✅ Вы забрали {win_amount:,} 💎!", show_alert=True)
    except Exception as e:
        logger.error(f"Ошибка в cashout_handler: {e}")
        await callback.answer("❌ Произошла ошибка!", show_alert=True)
    
    if game_id in active_games:
        del active_games[game_id]