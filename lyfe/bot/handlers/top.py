"""TOP REQUESTS — the live ranking, and the voting system at the same time.

There is deliberately no separate poll feature. A like on an existing request
is the vote: one screen, one entity, no editorial work before each event, and
the numbers reflect real demand rather than a curated shortlist.
"""
import logging
from datetime import timezone
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from lyfe.bot.keyboards import button_texts, main_menu
from lyfe.core.services import event_service, request_service
from lyfe.core.services.request_service import VoteResult
from lyfe.i18n import t
from lyfe.models import Event, User

logger = logging.getLogger(__name__)
router = Router(name="top")

TOP_LIMIT = 10
BUTTONS_PER_ROW = 5


def _event_date(event: Event) -> str:
    try:
        tz = ZoneInfo(event.city.timezone)
    except Exception:  # noqa: BLE001
        tz = timezone.utc
    return event.starts_at.astimezone(tz).strftime("%d.%m")


async def _render(
    session: AsyncSession, user: User, event: Event
) -> tuple[str, InlineKeyboardMarkup | None]:
    lang = user.language
    rows = await request_service.top_requests(session, event_id=event.id, limit=TOP_LIMIT)

    if not rows:
        return t("top_empty", lang), None

    requested, voted = await request_service.user_interactions(
        session, user_id=user.id, event_track_ids=[r.id for r in rows]
    )

    lines = [t("top_header", lang, event=event.title.upper(), date=_event_date(event)), ""]
    buttons: list[InlineKeyboardButton] = []

    for index, event_track in enumerate(rows, start=1):
        if event_track.id in requested:
            mark = "🎵"
        elif event_track.id in voted:
            mark = "❤️"
        else:
            mark = ""
        lines.append(
            f"{index:02d}  {event_track.track.display}  {event_track.score} {mark}".rstrip()
        )
        buttons.append(
            InlineKeyboardButton(
                text=f"{index}", callback_data=f"top:vote:{event_track.id}"
            )
        )

    lines.append("")
    lines.append(t("top_hint", lang))

    keyboard = [
        buttons[i : i + BUTTONS_PER_ROW] for i in range(0, len(buttons), BUTTONS_PER_ROW)
    ]
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=keyboard)


@router.message(F.text.in_(button_texts("btn_top")))
async def show_top(message: Message, user: User, session: AsyncSession):
    event = await event_service.get_next_event(session)
    if event is None:
        await message.answer(t("top_no_event", user.language), reply_markup=main_menu(user.language))
        return

    text, keyboard = await _render(session, user, event)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("top:vote:"))
async def vote(callback: CallbackQuery, user: User, session: AsyncSession):
    lang = user.language
    try:
        event_track_id = int(callback.data.split(":")[2])
    except (ValueError, IndexError):
        await callback.answer()
        return

    result = await request_service.add_vote(
        session, user_id=user.id, event_track_id=event_track_id
    )

    notices = {
        VoteResult.VOTED: t("vote_done", lang),
        VoteResult.ALREADY_VOTED: t("vote_already", lang),
        VoteResult.OWN_TRACK: t("vote_own", lang),
        VoteResult.EVENT_CLOSED: t("vote_closed", lang),
        VoteResult.NOT_FOUND: t("error", lang),
    }
    await callback.answer(notices.get(result, ""), show_alert=False)

    if result != VoteResult.VOTED:
        return

    event = await event_service.get_next_event(session)
    if event is None:
        return

    text, keyboard = await _render(session, user, event)
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest:
        # Nothing changed visibly, or the message is too old to edit.
        pass
