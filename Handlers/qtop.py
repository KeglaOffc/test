from aiogram import Router, types
from aiogram.filters import Command
# Импортируем cursor для запросов и db_get_user для проверки бана
from database import cursor, db_get_user

router = Router()

# Вспомогательная функция проверки на бан
async def is_banned(user_id: int):
    data = db_get_user(user_id)
    # В db_get_user мы возвращаем список, где индекс 2 — это banned
    if data and data[2] == 1: 
        return True
    return False

@router.message(Command("top", "qtop"))
async def cmd_top(message: types.Message):
    # 1. Проверка на бан
    if await is_banned(message.from_user.id):
        return await message.answer("🚫 Вы заблокированы администрацией.")

    try:
        # 2. Получаем Топ богачей (баланс) - исключаем невидимок
        cursor.execute("SELECT custom_id, balance FROM users WHERE incognito_mode = 0 ORDER BY balance DESC LIMIT 10")
        top_bal = cursor.fetchall()
        
        # 3. Получаем Топ дня по профиту (из таблицы daily_stats) - тоже исключаем невидимок
        # Мы явно указываем колонки, чтобы не было ошибки no such column
        cursor.execute("""
            SELECT u.custom_id, d.profit 
            FROM daily_stats d 
            JOIN users u ON d.user_id = u.id 
            WHERE d.profit > 0 AND u.incognito_mode = 0
            ORDER BY d.profit DESC LIMIT 5
        """)
        top_daily = cursor.fetchall()
        
        # 4. Формируем текст сообщения
        text = "🏆 **ГЛОБАЛЬНЫЙ РЕЙТИНГ ИГРОКОВ**\n\n"
        
        # Секция: Топ богачей
        text += "💰 **ТОП БОГАЧЕЙ:**\n"
        if not top_bal:
            text += "Список пуст...\n"
        else:
            for i, user in enumerate(top_bal, 1):
                name = user[0] if user[0] else "Игрок"
                text += f"{i}. `{name}` — {user[1]:,} 💎\n"
        
        # Секция: Лидеры дня
        text += "\n🔥 **ЛИДЕРЫ ДНЯ (ПРОФИТ):**\n"
        if not top_daily:
            text += "Пока пусто... Будь первым!\n"
        else:
            for i, user in enumerate(top_daily, 1):
                name = user[0] if user[0] else "Игрок"
                text += f"{i}⭐ `{name}` — +{user[1]:,} 💎\n"
                
        text += "\n📈 *Обновляется в реальном времени*"
        
        await message.answer(text, parse_mode="Markdown")

    except Exception as e:
        print(f"❌ Ошибка в qtop.py: {e}")
        await message.answer("⚠️ Произошла ошибка при загрузке рейтинга.")