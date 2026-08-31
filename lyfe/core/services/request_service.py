"""Adding a track request to an event.

All the rules live here, not in the bot handlers:
  - the event must be open for requests
  - one person cannot ask for the same track twice
  - a person is capped at N tracks per event
  - identical tracks from different people collapse into one row for the DJ
  - points are awarded through the ledger, once, idempotently
"""
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lyfe.config import get_settings
from lyfe.core.services import points_service
from lyfe.core.track_resolver import ResolvedTrack
from lyfe.models import (
    Event,
    EventTrack,
    PointsReason,
    RequestSource,
    Track,
    TrackRequest,
    TrackStatus,
    TrackVote,
)

settings = get_settings()


class AddResult:
    ADDED = "ADDED"
    ALREADY_REQUESTED = "ALREADY_REQUESTED"
    LIMIT_REACHED = "LIMIT_REACHED"
    EVENT_CLOSED = "EVENT_CLOSED"


@dataclass
class AddOutcome:
    status: str
    track: Track | None = None
    event_track: EventTrack | None = None
    requests_count: int = 0
    user_request_count: int = 0


async def count_user_requests(session: AsyncSession, *, user_id: int, event_id: int) -> int:
    return int(
        await session.scalar(
            select(func.count(TrackRequest.id))
            .join(EventTrack, EventTrack.id == TrackRequest.event_track_id)
            .where(TrackRequest.user_id == user_id, EventTrack.event_id == event_id)
        )
        or 0
    )


async def _get_or_create_track(session: AsyncSession, resolved: ResolvedTrack) -> Track:
    key = resolved.normalized_key
    track = await session.scalar(select(Track).where(Track.normalized_key == key))
    if track is not None:
        # Enrich a previously manual entry if we now have catalogue data.
        if resolved.provider != "manual" and track.provider == "manual":
            track.artist_name = resolved.artist_name or track.artist_name
            track.title = resolved.title or track.title
            track.album_name = resolved.album_name
            track.cover_url = resolved.cover_url
            track.external_url = resolved.external_url
            track.duration_ms = resolved.duration_ms
            track.provider = resolved.provider
            track.provider_track_id = resolved.provider_track_id
            track.needs_review = False
        return track

    track = Track(
        artist_name=resolved.artist_name or "—",
        title=resolved.title,
        album_name=resolved.album_name,
        cover_url=resolved.cover_url,
        external_url=resolved.external_url,
        duration_ms=resolved.duration_ms,
        provider=resolved.provider,
        provider_track_id=resolved.provider_track_id,
        normalized_key=key,
        needs_review=resolved.provider == "manual",
    )
    session.add(track)
    try:
        await session.flush()
    except IntegrityError:
        # Another request created the same track a millisecond earlier.
        await session.rollback()
        track = await session.scalar(select(Track).where(Track.normalized_key == key))
        if track is None:
            raise
    return track


async def _get_or_create_event_track(
    session: AsyncSession, *, event_id: int, track_id: int
) -> EventTrack:
    event_track = await session.scalar(
        select(EventTrack).where(
            EventTrack.event_id == event_id, EventTrack.track_id == track_id
        )
    )
    if event_track is not None:
        return event_track

    event_track = EventTrack(event_id=event_id, track_id=track_id, status=TrackStatus.NEW)
    session.add(event_track)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        event_track = await session.scalar(
            select(EventTrack).where(
                EventTrack.event_id == event_id, EventTrack.track_id == track_id
            )
        )
        if event_track is None:
            raise
    return event_track


async def add_request(
    session: AsyncSession,
    *,
    user_id: int,
    event: Event,
    resolved: ResolvedTrack,
    source: str = RequestSource.SEARCH,
    raw_input: str | None = None,
) -> AddOutcome:
    now = datetime.now(timezone.utc)

    if not event.accepts_requests(now):
        return AddOutcome(status=AddResult.EVENT_CLOSED)

    used = await count_user_requests(session, user_id=user_id, event_id=event.id)

    track = await _get_or_create_track(session, resolved)
    event_track = await _get_or_create_event_track(
        session, event_id=event.id, track_id=track.id
    )

    existing = await session.scalar(
        select(TrackRequest).where(
            TrackRequest.event_track_id == event_track.id,
            TrackRequest.user_id == user_id,
        )
    )
    if existing is not None:
        return AddOutcome(
            status=AddResult.ALREADY_REQUESTED,
            track=track,
            event_track=event_track,
            requests_count=event_track.requests_count,
            user_request_count=used,
        )

    if used >= settings.max_requests_per_user_per_event:
        return AddOutcome(
            status=AddResult.LIMIT_REACHED,
            track=track,
            user_request_count=used,
        )

    request = TrackRequest(
        event_track_id=event_track.id,
        user_id=user_id,
        source=source,
        raw_input=(raw_input or "")[:500] or None,
    )
    session.add(request)
    event_track.requests_count += 1
    await session.flush()

    await points_service.award(
        session,
        user_id=user_id,
        delta=settings.points_music_request,
        reason_code=PointsReason.MUSIC_REQUEST,
        idempotency_key=f"request:{request.id}",
        event_id=event.id,
        ref_type="track_request",
        ref_id=request.id,
    )

    return AddOutcome(
        status=AddResult.ADDED,
        track=track,
        event_track=event_track,
        requests_count=event_track.requests_count,
        user_request_count=used + 1,
    )


async def top_requests(session: AsyncSession, *, event_id: int, limit: int = 10):
    """Ordered list of (EventTrack, Track) for an event."""
    rows = await session.execute(
        select(EventTrack)
        .where(
            EventTrack.event_id == event_id,
            EventTrack.status != TrackStatus.REJECTED,
        )
        .order_by(
            (EventTrack.requests_count + EventTrack.votes_count).desc(),
            EventTrack.id.asc(),
        )
        .limit(limit)
    )
    return list(rows.scalars().unique())


class VoteResult:
    VOTED = "VOTED"
    ALREADY_VOTED = "ALREADY_VOTED"
    OWN_TRACK = "OWN_TRACK"
    EVENT_CLOSED = "EVENT_CLOSED"
    NOT_FOUND = "NOT_FOUND"


async def add_vote(session: AsyncSession, *, user_id: int, event_track_id: int) -> str:
    """A like on someone else's request. This IS the voting system —
    there is no separate poll to build or moderate."""
    event_track = await session.get(EventTrack, event_track_id)
    if event_track is None:
        return VoteResult.NOT_FOUND

    event = await session.get(Event, event_track.event_id)
    if event is None or not event.accepts_requests(datetime.now(timezone.utc)):
        return VoteResult.EVENT_CLOSED

    own = await session.scalar(
        select(TrackRequest.id).where(
            TrackRequest.event_track_id == event_track_id,
            TrackRequest.user_id == user_id,
        )
    )
    if own is not None:
        # Requesting already counts as one voice. Letting people also like their
        # own track would let them count twice.
        return VoteResult.OWN_TRACK

    existing = await session.scalar(
        select(TrackVote.id).where(
            TrackVote.event_track_id == event_track_id, TrackVote.user_id == user_id
        )
    )
    if existing is not None:
        return VoteResult.ALREADY_VOTED

    vote = TrackVote(event_track_id=event_track_id, user_id=user_id)
    session.add(vote)
    event_track.votes_count += 1
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return VoteResult.ALREADY_VOTED

    await points_service.award(
        session,
        user_id=user_id,
        delta=settings.points_vote,
        reason_code=PointsReason.VOTE,
        idempotency_key=f"vote:{vote.id}",
        event_id=event.id,
        ref_type="track_vote",
        ref_id=vote.id,
    )
    return VoteResult.VOTED


async def user_interactions(
    session: AsyncSession, *, user_id: int, event_track_ids: list[int]
) -> tuple[set[int], set[int]]:
    """Which of these tracks the user requested, and which they voted for."""
    if not event_track_ids:
        return set(), set()

    requested = await session.execute(
        select(TrackRequest.event_track_id).where(
            TrackRequest.user_id == user_id,
            TrackRequest.event_track_id.in_(event_track_ids),
        )
    )
    voted = await session.execute(
        select(TrackVote.event_track_id).where(
            TrackVote.user_id == user_id,
            TrackVote.event_track_id.in_(event_track_ids),
        )
    )
    return set(requested.scalars()), set(voted.scalars())
