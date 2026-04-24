"""Личные inline-меню.

Когда бот отправляет сообщение в ответ на действие игрока, мы
автоматически запоминаем пару ``(chat_id, message_id) → user_id``.
Callback-middleware пропускает только владельца; остальных отшивает
с alert «это меню вызвал другой игрок».

Реализация:

1. ``UserContextMiddleware`` кладёт id текущего игрока в ContextVar
   на время обработки любого апдейта.
2. Monkey-patch ``Message.answer`` / ``Message.reply`` / ``Message.edit_text``:
   после каждого вызова, если сообщение содержит inline-клавиатуру и мы
   в контексте игрока — регистрируем владельца.
3. ``OwnershipMiddleware`` на callback'ах: сверяет владельца с
   ``call.from_user.id``.

Хранилище — in-memory словарь с грубым LRU.
"""
from __future__ import annotations

import contextvars
import logging
from collections import OrderedDict
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, TelegramObject

logger = logging.getLogger(__name__)

MAX = 10_000

_OWNERS: "OrderedDict[Tuple[int, int], int]" = OrderedDict()

_current_user: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    "casino_current_user", default=None
)


def remember(message: Optional[Message], user_id: Optional[int]) -> None:
    """Регистрирует сообщение как принадлежащее заданному игроку."""
    if message is None or user_id is None:
        return
    try:
        key = (message.chat.id, message.message_id)
    except AttributeError:
        return
    _OWNERS[key] = user_id
    _OWNERS.move_to_end(key)
    while len(_OWNERS) > MAX:
        _OWNERS.popitem(last=False)


def forget(message: Optional[Message]) -> None:
    if message is None:
        return
    try:
        key = (message.chat.id, message.message_id)
    except AttributeError:
        return
    _OWNERS.pop(key, None)


def owner_of(message: Optional[Message]) -> Optional[int]:
    if message is None:
        return None
    try:
        key = (message.chat.id, message.message_id)
    except AttributeError:
        return None
    owner = _OWNERS.get(key)
    if owner is not None:
        return owner
    reply = getattr(message, "reply_to_message", None)
    if reply and getattr(reply, "from_user", None) and not reply.from_user.is_bot:
        return reply.from_user.id
    return None


# ─────────── middleware ───────────


class UserContextMiddleware(BaseMiddleware):
    """Кладёт id текущего игрока в contextvar, чтобы monkey-patch мог его читать."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        uid: Optional[int] = None
        user = getattr(event, "from_user", None)
        if user is not None:
            uid = user.id
        token = _current_user.set(uid)
        try:
            return await handler(event, data)
        finally:
            _current_user.reset(token)


class OwnershipMiddleware(BaseMiddleware):
    """Отшивает callback'и от чужих игроков."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if isinstance(event, CallbackQuery):
            owner = owner_of(event.message)
            if owner is not None and owner != event.from_user.id:
                try:
                    await event.answer(
                        "Это меню вызвал другой игрок.", show_alert=True
                    )
                except Exception:
                    pass
                return None
        return await handler(event, data)


# ─────────── monkey-patch исходящих сообщений ───────────

_patched = False


def _has_inline_markup(sent: Any, kwargs: Dict[str, Any]) -> bool:
    rm = kwargs.get("reply_markup")
    if isinstance(rm, InlineKeyboardMarkup):
        return True
    sent_rm = getattr(sent, "reply_markup", None)
    return isinstance(sent_rm, InlineKeyboardMarkup)


def install_patches() -> None:
    """Вешает auto-remember на Message.answer/reply/edit_text.

    Безопасно вызывать многократно — патч ставится один раз.
    """
    global _patched
    if _patched:
        return
    _patched = True

    orig_answer = Message.answer
    orig_reply = Message.reply
    orig_edit = Message.edit_text

    async def patched_answer(self: Message, *args: Any, **kwargs: Any):
        sent = await orig_answer(self, *args, **kwargs)
        uid = _current_user.get()
        if uid is not None and _has_inline_markup(sent, kwargs):
            remember(sent, uid)
        return sent

    async def patched_reply(self: Message, *args: Any, **kwargs: Any):
        sent = await orig_reply(self, *args, **kwargs)
        uid = _current_user.get()
        if uid is not None and _has_inline_markup(sent, kwargs):
            remember(sent, uid)
        return sent

    async def patched_edit(self: Message, *args: Any, **kwargs: Any):
        res = await orig_edit(self, *args, **kwargs)
        uid = _current_user.get()
        if uid is not None and _has_inline_markup(res, kwargs):
            remember(self, uid)
        return res

    Message.answer = patched_answer
    Message.reply = patched_reply
    Message.edit_text = patched_edit
