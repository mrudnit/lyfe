"""Middleware that opens a DB session and resolves the current user for every
update. Handlers receive `session` and `user` ready to use."""
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User as TgUser

from lyfe.core.services import user_service
from lyfe.db import SessionFactory


class DatabaseMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user: TgUser | None = data.get("event_from_user")
        if tg_user is None or tg_user.is_bot:
            return await handler(event, data)

        async with SessionFactory() as session:
            try:
                user, created = await user_service.get_or_create(
                    session,
                    tg_user_id=tg_user.id,
                    username=tg_user.username,
                    first_name=tg_user.first_name,
                    language_code=tg_user.language_code,
                )
                data["session"] = session
                data["user"] = user
                data["is_new_user"] = created
                result = await handler(event, data)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise
