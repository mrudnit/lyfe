"""LYFE PASS — the QR a guest shows at the door.

Rendered as a PNG and sent into the chat. Once the message has arrived it stays
cached in Telegram, so it opens with no signal at all, which is the whole point:
the guest is standing in a queue in a basement.
"""
import io
import logging

import segno
from aiogram import F, Router
from aiogram.types import BufferedInputFile, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lyfe.bot.keyboards import button_texts
from lyfe.config import get_settings
from lyfe.core import pass_token
from lyfe.core.services import user_service
from lyfe.i18n import t
from lyfe.models import Attendance, User

logger = logging.getLogger(__name__)
router = Router(name="lyfe_pass")
settings = get_settings()


def render_qr(payload: str) -> bytes:
    """Black-on-white PNG. High contrast beats branding when a camera is trying
    to read it across a dark doorway."""
    qr = segno.make(payload, error="h")
    buffer = io.BytesIO()
    qr.save(buffer, kind="png", scale=10, border=3, dark="#000000", light="#ffffff")
    return buffer.getvalue()


@router.message(F.text.in_(button_texts("btn_pass")))
async def show_pass(message: Message, user: User, session: AsyncSession):
    lang = user.language

    points = await user_service.get_points_balance(session, user.id)
    nights = await session.scalar(
        select(func.count(Attendance.id)).where(Attendance.user_id == user.id)
    )

    payload = pass_token.build(user.id, settings.admin_secret_key)
    image = render_qr(payload)

    await message.answer_photo(
        BufferedInputFile(image, filename=f"lyfe-{user.lyfe_id}.png"),
        caption=t(
            "lyfe_pass",
            lang,
            name=user.name.upper(),
            lyfe_id=user.lyfe_id,
            points=points,
            nights=nights or 0,
        ),
    )
