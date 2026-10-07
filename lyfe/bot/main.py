"""Bot entry point. Long polling for development; switch to webhooks for
production once the domain and Caddy are in place."""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from aiogram.types import MenuButtonWebApp, WebAppInfo

from lyfe.bot.handlers import router
from lyfe.bot.keyboards import webapp_url
from lyfe.bot.middlewares import DatabaseMiddleware
from lyfe.config import get_settings
from lyfe.core import track_resolver

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

    url = webapp_url()
    if url:
        # The button left of the message field opens the Mini App in every chat.
        # A bad URL must cost us this button, never the whole bot.
        try:
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(text="LYFE", web_app=WebAppInfo(url=url))
            )
            logger.info("Mini App at %s", url)
        except Exception as exc:  # noqa: BLE001
            logger.error("Mini App menu button not set (WEBAPP_URL=%r): %s", url, exc)

    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await track_resolver.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
