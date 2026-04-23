"""
Утилиты для безопасной работы с Telegram API
"""
import asyncio
import logging
from typing import Optional
from aiogram import Bot
from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter, TelegramBadRequest

logger = logging.getLogger(__name__)
network_logger = logging.getLogger('network')

async def safe_send_message(
    bot: Bot,
    chat_id: int,
    text: str,
    parse_mode: Optional[str] = None,
    max_retries: int = 3,
    retry_delay: float = 1.0
) -> bool:
    """
    Безопасная отправка сообщений с повторными попытками при сетевых ошибках.
    
    Args:
        bot: Экземпляр бота
        chat_id: ID чата для отправки
        text: Текст сообщения
        parse_mode: Режим парсинга (Markdown, HTML и т.д.)
        max_retries: Максимальное количество попыток
        retry_delay: Задержка между попытками в секундах
        
    Returns:
        True если сообщение отправлено успешно, False в противном случае
    """
    for attempt in range(max_retries):
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode
            )
            return True
            
        except TelegramRetryAfter as e:
            # Ожидаем время, указанное Telegram
            wait_time = e.retry_after + retry_delay
            logger.warning(f"Flood control for {chat_id}, waiting {wait_time}s (attempt {attempt + 1})")
            await asyncio.sleep(wait_time)
            
        except TelegramNetworkError as e:
            # Сетевая ошибка - ждем и повторяем
            network_logger.warning(f"Network error sending to {chat_id}: {e} (attempt {attempt + 1})")
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay * (attempt + 1))  # Экспоненциальная задержка
            
        except TelegramBadRequest as e:
            # Ошибка формата сообщения - логируем и пропускаем
            logger.error(f"Bad request sending to {chat_id}: {e}")
            return False
            
        except Exception as e:
            # Другие ошибки - логируем и пробуем еще раз
            logger.error(f"Unexpected error sending to {chat_id}: {e} (attempt {attempt + 1})")
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)
    
    # Все попытки исчерпаны
    network_logger.error(f"Failed to send message to {chat_id} after {max_retries} attempts")
    return False


async def safe_reply_message(
    message,
    text: str,
    parse_mode: Optional[str] = None,
    max_retries: int = 2
) -> bool:
    """
    Безопасный ответ на сообщение с fallback на обычное сообщение.
    
    Args:
        message: Объект сообщения для ответа
        text: Текст ответа
        parse_mode: Режим парсинга
        max_retries: Максимальное количество попыток
        
    Returns:
        True если ответ отправлен успешно, False в противном случае
    """
    try:
        await message.reply(text, parse_mode=parse_mode)
        return True
    except Exception as e:
        logger.warning(f"Failed to reply to message, trying to send as new message: {e}")
        try:
            await message.answer(text, parse_mode=parse_mode)
            return True
        except Exception as e2:
            logger.error(f"Failed to send message as fallback: {e2}")
            return False


async def safe_edit_message(
    call,
    text: str,
    parse_mode: Optional[str] = None,
    max_retries: int = 2
) -> bool:
    """
    Безопасное редактирование сообщения.
    
    Args:
        call: Объект callback query
        text: Новый текст сообщения
        parse_mode: Режим парсинга
        max_retries: Максимальное количество попыток
        
    Returns:
        True если сообщение отредактировано успешно, False в противном случае
    """
    try:
        await call.message.edit_text(text, parse_mode=parse_mode)
        return True
    except Exception as e:
        logger.warning(f"Failed to edit message: {e}")
        # Пробуем отправить новое сообщение как fallback
        try:
            await call.message.answer(text, parse_mode=parse_mode)
            return True
        except Exception as e2:
            logger.error(f"Failed to send new message as fallback: {e2}")
            return False