from aiogram import Router

from lyfe.bot.handlers import lyfe_pass, request, rewards, start, top

router = Router(name="root")
# Order matters: start.py ends with a catch-all text handler, so every
# specific router must be registered before it.
router.include_router(request.router)
router.include_router(top.router)
router.include_router(lyfe_pass.router)
router.include_router(rewards.router)
router.include_router(start.router)

__all__ = ["router"]
