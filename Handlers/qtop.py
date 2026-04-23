"""Команда /top — глобальный рейтинг игроков."""
import logging

from aiogram import Router, types
from aiogram.filters import Command

from database import cursor, db_get_user

logger = logging.getLogger(__name__)
router = Router()


async def is_banned(user_id: int) -> bool:
    data = db_get_user(user_id)
    return bool(data and data[2] == 1)


@router.message(Command("top", "qtop"))
async def cmd_top(message: types.Message):
    if await is_banned(message.from_user.id):
        return await message.answer("🚫 Вы заблокированы администрацией.")

    try:
        cursor.execute(
            "SELECT custom_id, balance FROM users "
            "WHERE incognito_mode = 0 ORDER BY balance DESC LIMIT 10"
        )
        top_bal = cursor.fetchall()

        cursor.execute(
            """
            SELECT u.custom_id, d.profit
            FROM daily_stats d
            JOIN users u ON d.user_id = u.id
            WHERE d.profit > 0 AND u.incognito_mode = 0
            ORDER BY d.profit DESC LIMIT 5
            """
        )
        top_daily = cursor.fetchall()

        lines = ["🏆 **ГЛОБАЛЬНЫЙ РЕЙТИНГ ИГРОКОВ**", "", "💰 **ТОП БОГАЧЕЙ:**"]
        if not top_bal:
            lines.append("Список пуст…")
        else:
            for i, (name, balance) in enumerate(top_bal, 1):
                lines.append(f"{i}. `{name or 'Игрок'}` — {balance:,} 💎")

        lines.append("")
        lines.append("🔥 **ЛИДЕРЫ ДНЯ (ПРОФИТ):**")
        if not top_daily:
            lines.append("Пока пусто… Будь первым!")
        else:
            for i, (name, profit) in enumerate(top_daily, 1):
                lines.append(f"{i}⭐ `{name or 'Игрок'}` — +{profit:,} 💎")

        lines.append("")
        lines.append("📈 *Обновляется в реальном времени*")

        await message.answer("\n".join(lines), parse_mode="Markdown")

    except Exception as e:
        logger.error("Ошибка в /top: %s", e, exc_info=True)
        await message.answer("⚠️ Произошла ошибка при загрузке рейтинга.")
