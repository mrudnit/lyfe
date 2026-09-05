"""TOP REQUESTS - the live chart, and the voting system at the same time.

There is deliberately no separate poll feature. A like on an existing request
is the vote: one screen, one entity, no editorial work before each event, and
the numbers reflect real demand rather than a curated shortlist.

The chart is paginated. A person who added a track and cannot see it assumes it
was lost, so their own tracks are always listed with their position, however far
down the chart they are.
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

PAGE_SIZE = 10
BUTTONS_PER_ROW = 5
MAX_OWN_TRACKS_SHOWN = 3


def _event_date(event: Event) -> str:
    try:
        tz = ZoneInfo(event.city.timezone)
    except Exception:  # noqa: BLE001
        tz = timezone.utc
    return event.starts_at.astimezone(tz).strftime("%d.%m")


async def _render(
    session: AsyncSession, user: User, event: Event, offset: int = 0
) -> tuple[str, InlineKeyboardMarkup | None]:
    lang = user.language
    total = await request_service.top_count(session, event_id=event.id)

    if not total:
        return t("top_empty", lang), None

    offset = max(0, min(offset, max(0, (total - 1) // PAGE_SIZE * PAGE_SIZE)))
    rows = await request_service.top_requests(
        session, event_id=event.id, limit=PAGE_SIZE, offset=offset
    )
    requested, voted = await request_service.user_interactions(
        session, user_id=user.id, event_track_ids=[r.id for r in rows]
    )

    lines = [t("top_header", lang, event=event.title.upper(), date=_event_date(event)), ""]
    buttons: list[InlineKeyboardButton] = []

    for index, event_track in enumerate(rows, start=offset + 1):
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
            InlineKeyboardButton(text=f"{index}", callback_data=f"top:vote:{event_track.id}:{offset}")
        )

    if total > PAGE_SIZE:
        lines.append("")
        lines.append(t("top_page", lang, shown=f"{offset + 1}-{offset + len(rows)}", total=total))

    # Own tracks, wherever they are in the chart.
    own = await request_service.user_track_positions(
        session, user_id=user.id, event_id=event.id
    )
    off_page = [(pos, name) for pos, name in own if not (offset < pos <= offset + PAGE_SIZE)]
    if off_page:
        lines.append("")
        lines.append(t("top_your_tracks", lang))
        for position, name in off_page[:MAX_OWN_TRACKS_SHOWN]:
            lines.append(f"{position:02d}  {name}")

    lines.append("")
    lines.append(t("top_hint", lang))

    keyboard = [
        buttons[i : i + BUTTONS_PER_ROW] for i in range(0, len(buttons), BUTTONS_PER_ROW)
    ]

    nav: list[InlineKeyboardButton] = []
    if offset > 0:
        nav.append(
            InlineKeyboardButton(
                text=t("btn_top_back", lang), callback_data=f"top:page:{max(0, offset - PAGE_SIZE)}"
            )
        )
    if offset + PAGE_SIZE < total:
        nav.append(
            InlineKeyboardButton(
                text=t("btn_more", lang), callback_data=f"top:page:{offset + PAGE_SIZE}"
            )
        )
    if nav:
        keyboard.append(nav)

    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=keyboard)


@router.message(F.text.in_(button_texts("btn_top")))
async def show_top(message: Message, user: User, session: AsyncSession):
    event = await event_service.get_next_event(session)
    if event is None:
        await message.answer(t("top_no_event", user.language), reply_markup=main_menu(user.language))
        return

    text, keyboard = await _render(session, user, event)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("top:page:"))
async def turn_page(callback: CallbackQuery, user: User, session: AsyncSession):
    await callback.answer()
    event = await event_service.get_next_event(session)
    if event is None:
        return

    try:
        offset = int(callback.data.split(":")[2])
    except (ValueError, IndexError):
        offset = 0

    text, keyboard = await _render(session, user, event, offset=offset)
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest:
        pass


@router.callback_query(F.data.startswith("top:vote:"))
async def vote(callback: CallbackQuery, user: User, session: AsyncSession):
    lang = user.language
    parts = callback.data.split(":")
    try:
        event_track_id = int(parts[2])
        offset = int(parts[3]) if len(parts) > 3 else 0
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

    text, keyboard = await _render(session, user, event, offset=offset)
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest:
        # Nothing changed visibly, or the message is too old to edit.
        pass
