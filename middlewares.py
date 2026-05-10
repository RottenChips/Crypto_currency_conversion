from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from config import ADMIN_ID

class AccessMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        user = data.get('event_from_user')

        if user and ADMIN_ID and user.id != ADMIN_ID:
            if isinstance(event, Message):
                await event.answer('⛔ Access denied for non-admin users.')
            elif isinstance(event, CallbackQuery):
                await event.answer('⛔ Access denied. You are not an admin.', show_alert=True)
            return

        return await handler(event, data)
