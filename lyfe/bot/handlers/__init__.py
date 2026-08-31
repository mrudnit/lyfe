from aiogram import Router

from lyfe.bot.handlers import request, start, top

router = Router(name="root")
# Order matters: start.py ends with a catch-all text handler, so every
# specific router must be registered before it.
router.include_router(request.router)
router.include_router(top.router)
router.include_router(start.router)

__all__ = ["router"]
