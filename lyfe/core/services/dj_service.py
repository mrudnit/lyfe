"""The DJ live screen: what to show, and what happens on PLAYED.

Marking a track played is the single most important action in the product.
Everything else — requests, deduplication, votes, points — exists so that this
one button can send the right message to the right people at the right moment.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lyfe.models import (
    AdminAction,
    Event,
    EventStatus,
    EventTrack,
    Track,
    TrackRequest,
    TrackStatus,
    User,
)

logger = logging.getLogger(__name__)

NEW_WINDOW_MINUTES = 20


@dataclass
class TrackRow:
    id: int
    artist: str
    title: str
    requests: int
    votes: int
    score: int
    status: str
    is_new: bool
    is_priority: bool
    cover_url: str | None
    created_at: str


async def current_event(session: AsyncSession) -> Event | None:
    """LIVE first, otherwise the nearest upcoming event."""
    live = await session.scalar(
        select(Event).where(Event.status == EventStatus.LIVE).order_by(Event.starts_at).limit(1)
    )
    if live is not None:
        return live
    return await session.scalar(
        select(Event)
        .where(Event.status.in_((EventStatus.UPCOMING, EventStatus.LIVE)))
        .order_by(Event.starts_at)
        .limit(1)
    )


async def board(session: AsyncSession, *, event_id: int, limit: int = 60) -> list[TrackRow]:
    now = datetime.now(timezone.utc)
    fresh_after = now - timedelta(minutes=NEW_WINDOW_MINUTES)

    rows = await session.execute(
        select(EventTrack, Track)
        .join(Track, Track.id == EventTrack.track_id)
        .where(EventTrack.event_id == event_id)
        .order_by(
            # Guaranteed plays sit on top — that is what was paid for.
            EventTrack.is_priority.desc(),
            (EventTrack.requests_count + EventTrack.votes_count).desc(),
            EventTrack.id.asc(),
        )
        .limit(limit)
    )

    board_rows = []
    for event_track, track in rows.all():
        board_rows.append(
            TrackRow(
                id=event_track.id,
                artist=track.artist_name,
                title=track.title,
                requests=event_track.requests_count,
                votes=event_track.votes_count,
                score=event_track.requests_count + event_track.votes_count,
                status=event_track.status,
                is_new=event_track.created_at > fresh_after,
                is_priority=event_track.is_priority,
                cover_url=track.cover_url,
                created_at=event_track.created_at.isoformat(),
            )
        )
    return board_rows


async def _log(
    session: AsyncSession, *, admin_id: int, action: str, event_track: EventTrack, old: str
) -> None:
    session.add(
        AdminAction(
            admin_id=admin_id,
            action=action,
            target_type="event_track",
            target_id=event_track.id,
            old_value={"status": old},
            new_value={"status": event_track.status},
        )
    )


async def mark_played(
    session: AsyncSession, *, event_track_id: int, admin_id: int
) -> tuple[bool, list[int]]:
    """Returns (changed, telegram ids to notify)."""
    event_track = await session.get(EventTrack, event_track_id)
    if event_track is None or event_track.status == TrackStatus.PLAYED:
        return False, []

    old_status = event_track.status
    event_track.status = TrackStatus.PLAYED
    event_track.played_at = datetime.now(timezone.utc)
    event_track.played_by_admin_id = admin_id
    await _log(session, admin_id=admin_id, action="MARK_PLAYED", event_track=event_track, old=old_status)

    rows = await session.execute(
        select(User.tg_user_id)
        .join(TrackRequest, TrackRequest.user_id == User.id)
        .where(
            TrackRequest.event_track_id == event_track_id,
            User.is_bot_blocked.is_(False),
            User.deleted_at.is_(None),
        )
    )
    return True, [int(x) for x in rows.scalars()]


async def undo_played(session: AsyncSession, *, event_track_id: int, admin_id: int) -> bool:
    event_track = await session.get(EventTrack, event_track_id)
    if event_track is None or event_track.status != TrackStatus.PLAYED:
        return False

    event_track.status = TrackStatus.NEW
    event_track.played_at = None
    event_track.played_by_admin_id = None
    await _log(session, admin_id=admin_id, action="UNDO_PLAYED", event_track=event_track, old=TrackStatus.PLAYED)
    return True


async def reject(session: AsyncSession, *, event_track_id: int, admin_id: int) -> bool:
    event_track = await session.get(EventTrack, event_track_id)
    if event_track is None:
        return False
    old_status = event_track.status
    event_track.status = (
        TrackStatus.NEW if event_track.status == TrackStatus.REJECTED else TrackStatus.REJECTED
    )
    await _log(session, admin_id=admin_id, action="TOGGLE_REJECT", event_track=event_track, old=old_status)
    return True


async def mark_notified(session: AsyncSession, *, event_track_id: int) -> None:
    now = datetime.now(timezone.utc)
    requests = await session.execute(
        select(TrackRequest).where(
            TrackRequest.event_track_id == event_track_id,
            TrackRequest.notified_played_at.is_(None),
        )
    )
    for request in requests.scalars():
        request.notified_played_at = now
