"""LYFE REQUEST: the user adds a track to the current event.

Flow:
    press "Добавить трек"  ->  prompt
    types text or a link   ->  catalogue search
    picks a button         ->  request created, points awarded
    nothing found          ->  manual entry, flagged for review

Search results are kept in FSM state and referenced by index, so callback data
stays tiny and no track metadata ever travels through a button payload.
"""
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from lyfe.bot.keyboards import button_texts, main_menu
from lyfe.core import track_resolver
from lyfe.core.services import event_service, request_service
from lyfe.core.services.request_service import AddResult
from lyfe.i18n import people_phrase, t
from lyfe.models import Event, RequestSource, User

logger = logging.getLogger(__name__)
router = Router(name="request")

MAX_QUERY_LENGTH = 200


class RequestFlow(StatesGroup):
    waiting_for_query = State()
    waiting_for_manual = State()


def _event_date(event: Event) -> str:
    try:
        tz = ZoneInfo(event.city.timezone)
    except Exception:  # noqa: BLE001
        tz = timezone.utc
    return event.starts_at.astimezone(tz).strftime("%d.%m")


def _cancel_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t("btn_cancel", lang), callback_data="req:cancel")]
        ]
    )


@router.message(F.text.in_(button_texts("btn_request")))
async def start_request(message: Message, user: User, session: AsyncSession, state: FSMContext):
    lang = user.language
    event = await event_service.get_next_event(session)

    if event is None:
        await state.clear()
        await message.answer(t("request_no_event", lang), reply_markup=main_menu(lang))
        return

    if not event.accepts_requests(datetime.now(timezone.utc)):
        await state.clear()
        await message.answer(t("request_event_closed", lang), reply_markup=main_menu(lang))
        return

    await state.set_state(RequestFlow.waiting_for_query)
    await state.update_data(event_id=event.id)
    await message.answer(
        t("request_prompt", lang, date=_event_date(event)),
        reply_markup=_cancel_keyboard(lang),
    )


@router.message(RequestFlow.waiting_for_query, F.audio)
async def handle_audio(message: Message, user: User, session: AsyncSession, state: FSMContext):
    """Someone forwarded a track from another chat. The tags are right there,
    so there is nothing to search for."""
    audio = message.audio
    artist = (audio.performer or "").strip()
    title = (audio.title or audio.file_name or "").strip()
    if title.lower().endswith((".mp3", ".m4a", ".wav", ".flac", ".ogg")):
        title = title.rsplit(".", 1)[0]

    query = f"{artist} {title}".strip()
    if not query:
        await message.answer(t("request_not_found", user.language), reply_markup=_cancel_keyboard(user.language))
        await state.set_state(RequestFlow.waiting_for_manual)
        return

    searching = await message.answer(t("request_searching", user.language))
    results = await track_resolver.resolve(query)
    try:
        await searching.delete()
    except Exception:  # noqa: BLE001
        pass

    if results:
        await _offer_candidates(message, user, state, results, query)
        return

    resolved = track_resolver.ResolvedTrack(
        artist_name=artist, title=title or query, provider="manual"
    )
    await _finish(
        message, user=user, session=session, state=state,
        resolved=resolved, source=RequestSource.LINK, raw_input=query,
    )


@router.message(RequestFlow.waiting_for_query, F.text)
async def handle_query(message: Message, user: User, session: AsyncSession, state: FSMContext):
    lang = user.language
    query = (message.text or "").strip()[:MAX_QUERY_LENGTH]

    # A menu button while in the flow means the user changed their mind.
    if any(query in button_texts(key) for key in ("btn_top", "btn_my_lyfe", "btn_next_event")):
        await state.clear()
        return

    searching = await message.answer(t("request_searching", lang))
    results = await track_resolver.resolve(query)

    try:
        await searching.delete()
    except Exception:  # noqa: BLE001 - deleting is cosmetic
        pass

    if not results:
        await state.set_state(RequestFlow.waiting_for_manual)
        await state.update_data(raw_input=query)
        await message.answer(t("request_not_found", lang), reply_markup=_cancel_keyboard(lang))
        return

    await _offer_candidates(message, user, state, results, query)


async def _offer_candidates(message, user, state, results, query) -> None:
    lang = user.language
    await state.set_state(RequestFlow.waiting_for_query)
    await state.update_data(
        candidates=[
            {
                "artist_name": r.artist_name,
                "title": r.title,
                "album_name": r.album_name,
                "cover_url": r.cover_url,
                "external_url": r.external_url,
                "duration_ms": r.duration_ms,
                "provider": r.provider,
                "provider_track_id": r.provider_track_id,
            }
            for r in results
        ],
        raw_input=query,
    )

    buttons = [
        [InlineKeyboardButton(text=r.display[:60], callback_data=f"req:pick:{i}")]
        for i, r in enumerate(results)
    ]
    buttons.append([InlineKeyboardButton(text=t("btn_manual", lang), callback_data="req:manual")])
    buttons.append([InlineKeyboardButton(text=t("btn_cancel", lang), callback_data="req:cancel")])

    await message.answer(
        t("request_pick", lang), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data.startswith("req:pick:"))
async def pick_candidate(
    callback: CallbackQuery, user: User, session: AsyncSession, state: FSMContext
):
    lang = user.language
    data = await state.get_data()
    candidates = data.get("candidates") or []

    try:
        index = int(callback.data.split(":")[2])
        payload = candidates[index]
    except (ValueError, IndexError):
        await callback.answer()
        await state.clear()
        await callback.message.answer(t("error", lang), reply_markup=main_menu(lang))
        return

    resolved = track_resolver.ResolvedTrack(**payload)
    await callback.answer()
    await _finish(
        callback.message,
        user=user,
        session=session,
        state=state,
        resolved=resolved,
        source=RequestSource.SEARCH,
        raw_input=data.get("raw_input"),
    )


@router.callback_query(F.data == "req:manual")
async def ask_manual(callback: CallbackQuery, user: User, state: FSMContext):
    await callback.answer()
    await state.set_state(RequestFlow.waiting_for_manual)
    await callback.message.answer(
        t("request_not_found", user.language), reply_markup=_cancel_keyboard(user.language)
    )


@router.message(RequestFlow.waiting_for_manual, F.text)
async def handle_manual(message: Message, user: User, session: AsyncSession, state: FSMContext):
    text = (message.text or "").strip()[:MAX_QUERY_LENGTH]
    resolved = track_resolver.manual_track(text)
    await _finish(
        message,
        user=user,
        session=session,
        state=state,
        resolved=resolved,
        source=RequestSource.MANUAL,
        raw_input=text,
    )


@router.callback_query(F.data == "req:cancel")
async def cancel(callback: CallbackQuery, user: User, state: FSMContext):
    await state.clear()
    await callback.answer()
    await callback.message.answer(
        t("request_cancelled", user.language), reply_markup=main_menu(user.language)
    )


async def _finish(
    message: Message,
    *,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    resolved: track_resolver.ResolvedTrack,
    source: str,
    raw_input: str | None,
) -> None:
    lang = user.language
    data = await state.get_data()
    await state.clear()

    event = await event_service.get_next_event(session)
    if event is None or event.id != data.get("event_id"):
        # The event changed while the user was typing.
        await message.answer(t("request_event_closed", lang), reply_markup=main_menu(lang))
        return

    outcome = await request_service.add_request(
        session,
        user_id=user.id,
        event=event,
        resolved=resolved,
        source=source,
        raw_input=raw_input,
    )

    if outcome.status == AddResult.EVENT_CLOSED:
        await message.answer(t("request_event_closed", lang), reply_markup=main_menu(lang))
        return

    if outcome.status == AddResult.LIMIT_REACHED:
        await message.answer(t("request_limit", lang), reply_markup=main_menu(lang))
        return

    if outcome.status == AddResult.ALREADY_REQUESTED:
        await message.answer(
            t(
                "request_already",
                lang,
                track=outcome.track.display,
                n=people_phrase(outcome.requests_count, lang),
            ),
            reply_markup=main_menu(lang),
        )
        return

    position = (
        t("request_position_first", lang)
        if outcome.requests_count <= 1
        else t("request_position_nth", lang, n=outcome.requests_count)
    )
    await message.answer(
        t(
            "request_added",
            lang,
            track=outcome.track.display,
            date=_event_date(event),
            position=position,
        ),
        reply_markup=main_menu(lang),
    )
