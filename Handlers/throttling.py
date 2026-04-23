import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from aiogram.exceptions import TelegramRetryAfter

logger = logging.getLogger(__name__)

class flood_middleware(BaseMiddleware):
    """
    Middleware для автоматической обработки ошибки TelegramRetryAfter (Flood Control).
    Если бот ловит флуд, он просто ждет и пробует снова.
    """
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        try:
            return await handler(event, data)
        except TelegramRetryAfter as e:
            logger.warning(f"Flood limit hit! Waiting {e.retry_after} seconds...")
            # Ждем сколько просит Телеграм
            await asyncio.sleep(e.retry_after)
            # Пробуем выполнить действие еще раз после паузы
            try:
                return await handler(event, data)
            except Exception as retry_e:
                logger.error(f"Failed after retry: {retry_e}")
                raise
        except Exception as e:
            # Логируем другие ошибки, но не пытаемся повторить
            logger.error(f"Error in throttling middleware: {e}")
            raise