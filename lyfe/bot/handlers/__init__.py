from aiogram import Router

from lyfe.bot.handlers import start

router = Router(name="root")
router.include_router(start.router)

__all__ = ["router"]
