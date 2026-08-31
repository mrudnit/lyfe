"""Bot entry point. Long polling for development; switch to webhooks for
production once the domain and Caddy are in place."""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from lyfe.bot.handlers import router
from lyfe.bot.middlewares import DatabaseMiddleware
from lyfe.config import get_settings

logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.update.middleware(DatabaseMiddleware())
    dp.include_router(router)

    me = await bot.get_me()
    logger.info("LYFE bot starting as @%s", me.username)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
