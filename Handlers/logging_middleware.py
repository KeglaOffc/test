import logging
from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery

logger = logging.getLogger(__name__)

class LoggingMiddleware(BaseMiddleware):
    """
    Middleware для логирования входящих событий.
    """
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        user = None
        try:
            if isinstance(event, Message):
                user = event.from_user
                logger.info(f"Message from {user.id} ({user.username}): {event.text}")
            elif isinstance(event, CallbackQuery):
                user = event.from_user
                logger.info(f"Callback from {user.id} ({user.username}): {event.data}")
        except Exception as e:
            logger.warning(f"Error logging event: {e}")
            
        try:
            return await handler(event, data)
        except Exception as e:
            logger.error(f"Error in handler for user {user.id if user else 'unknown'}: {e}")
            # Re-raise the exception to be handled by error middleware
            raise
