"""Step 1 handlers: /start, NEXT EVENT, MY LYFE, fallback."""
import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lyfe.bot.keyboards import button_texts, main_menu
from lyfe.core.services import event_service, user_service
from lyfe.i18n import days_word, t
from lyfe.models import Attendance, EventTrack, TrackRequest, TrackStatus, User

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, user: User, is_new_user: bool, session: AsyncSession):
    lang = user.language

    if is_new_user:
        await message.answer(t("start_new", lang), reply_markup=main_menu(lang))
        # Small pause so the LYFE ID lands as its own moment, not as noise.
        await asyncio.sleep(1.2)
        await message.answer(t("lyfe_id_assigned", lang, lyfe_id=user.lyfe_id))
    else:
        await message.answer(
            t("start_returning", lang, name=user.name, lyfe_id=user.lyfe_id),
            reply_markup=main_menu(lang),
        )

    await _send_next_event(message, user, session)


@router.message(F.text.in_(button_texts("btn_next_event")))
async def show_next_event(message: Message, user: User, session: AsyncSession):
    await _send_next_event(message, user, session)


async def _send_next_event(message: Message, user: User, session: AsyncSession) -> None:
    lang = user.language
    event = await event_service.get_next_event(session)

    if event is None:
        await message.answer(t("next_event_none", lang))
        return

    # Parties run past midnight, so the date MUST be rendered in the venue's
    # timezone. Comparing UTC dates would show yesterday for a 00:30 start.
    try:
        tz = ZoneInfo(event.city.timezone)
    except Exception:
        tz = timezone.utc

    local_start = event.starts_at.astimezone(tz)
    local_now = datetime.now(tz)

    days = (local_start.date() - local_now.date()).days
    if days <= 0:
        countdown = t("countdown_today", lang)
    elif days == 1:
        countdown = t("countdown_tomorrow", lang)
    else:
        countdown = t("countdown_days", lang, days=days, days_word=days_word(days, lang))

    text = t(
        "next_event_card",
        lang,
        title=event.title.upper(),
        date=local_start.strftime("%d.%m"),
        venue=event.venue.name.upper(),
        city=event.city.name.upper(),
        countdown=countdown,
    )

    keyboard = None
    if event.ticket_url:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=t("btn_ticket", lang), url=event.ticket_url)]]
        )

    await message.answer(text, reply_markup=keyboard)


@router.message(F.text.in_(button_texts("btn_my_lyfe")))
async def show_my_lyfe(message: Message, user: User, session: AsyncSession):
    lang = user.language

    requests = await session.scalar(
        select(func.count(TrackRequest.id)).where(TrackRequest.user_id == user.id)
    )
    played = await session.scalar(
        select(func.count(TrackRequest.id))
        .join(EventTrack, EventTrack.id == TrackRequest.event_track_id)
        .where(TrackRequest.user_id == user.id, EventTrack.status == TrackStatus.PLAYED)
    )
    nights = await session.scalar(
        select(func.count(Attendance.id)).where(Attendance.user_id == user.id)
    )
    points = await user_service.get_points_balance(session, user.id)

    await message.answer(
        t(
            "my_lyfe",
            lang,
            name=user.name.upper(),
            lyfe_id=user.lyfe_id,
            requests=requests or 0,
            played=played or 0,
            nights=nights or 0,
            points=points,
        )
    )


@router.message(F.text)
async def fallback(message: Message, user: User):
    # In step 2 this becomes the track search entry point.
    await message.answer(t("unknown_input", user.language), reply_markup=main_menu(user.language))
