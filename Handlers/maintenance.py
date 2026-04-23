from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from typing import Callable, Dict, Any, Awaitable
import os
from database import get_maintenance_mode

ADMIN_ID = int(os.getenv("ADMIN_ID", 5030561581))

class MaintenanceMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message | CallbackQuery, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any]
    ) -> Any:
        
        if get_maintenance_mode():
            user_id = event.from_user.id
            if user_id != ADMIN_ID:
                if isinstance(event, Message):
                    await event.answer("⚠️ <b>ТЕХНИЧЕСКИЕ РАБОТЫ</b>\n\nБот временно недоступен. Попробуйте позже.", parse_mode="HTML")
                elif isinstance(event, CallbackQuery):
                    await event.answer("⚠️ Технические работы! Бот недоступен.", show_alert=True)
                return
        
        return await handler(event, data)
