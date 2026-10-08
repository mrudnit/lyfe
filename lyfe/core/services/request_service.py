"""Adding a track request to an event.

All the rules live here, not in the bot handlers:
  - the event must be open for requests
  - one person cannot ask for the same track twice
  - a person is capped at N tracks per event
  - identical tracks from different people collapse into one row for the DJ,
    and so do near-identical ones ("Макс Корж" from iTunes, "Max Korzh" from
    Deezer, a hand-typed "korzh malyy povzroslel")
  - points are awarded through the ledger, once, idempotently
"""
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lyfe.config import get_settings
from lyfe.core.services import points_service
from lyfe.core.track_resolver import SAME_TRACK_THRESHOLD, ResolvedTrack, similarity
from lyfe.models import (
    Event,
    EventTrack,
    PointsReason,
    PointTransaction,
    RequestSource,
    Track,
    TrackRequest,
    TrackStatus,
    TrackVote,
    User,
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


async def find_in_event(
    session: AsyncSession, *, event_id: int, resolved: ResolvedTrack
) -> EventTrack | None:
    """The row this track already has in the event's list, if any.

    The exact key catches the same song from the same catalogue. Similarity
    catches the rest: two catalogues spelling an artist differently, a link
    whose page title differs from the catalogue, a hand-typed entry.
    """
    return (await match_in_event(session, event_id=event_id, candidates=[resolved]))[0]


async def match_in_event(
    session: AsyncSession, *, event_id: int, candidates: list[ResolvedTrack]
) -> list[EventTrack | None]:
    """find_in_event for a whole list of search results, reading the event once."""
    rows = (
        await session.execute(
            select(EventTrack, Track)
            .join(Track, Track.id == EventTrack.track_id)
            .where(EventTrack.event_id == event_id)
        )
    ).all()
    by_key = {track.normalized_key: event_track for event_track, track in rows}

    matches: list[EventTrack | None] = []
    for resolved in candidates:
        exact = by_key.get(resolved.normalized_key)
        if exact is not None:
            matches.append(exact)
            continue
        best, best_score = None, 0.0
        for event_track, track in rows:
            score = similarity(
                resolved.artist_name, resolved.title, track.artist_name, track.title
            )
            if score > best_score:
                best, best_score = event_track, score
        matches.append(best if best_score >= SAME_TRACK_THRESHOLD else None)
    return matches


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
    try:
        async with session.begin_nested():
            session.add(track)
            await session.flush()
    except IntegrityError:
        # Another guest created the same track a millisecond earlier.
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
    try:
        async with session.begin_nested():
            session.add(event_track)
            await session.flush()
    except IntegrityError:
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

    from lyfe.core.services import user_service

    # One guest's adds run one at a time, so two quick taps cannot both slip
    # under the three-track limit.
    await user_service.lock_user(session, user_id)
    used = await count_user_requests(session, user_id=user_id, event_id=event.id)

    event_track = await find_in_event(session, event_id=event.id, resolved=resolved)
    if event_track is not None:
        track = await session.get(Track, event_track.track_id)
    else:
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


def score_expression():
    return EventTrack.requests_count + EventTrack.votes_count + EventTrack.boost_points


def _top_ordering():
    return (
        EventTrack.is_priority.desc(),
        score_expression().desc(),
        EventTrack.id.asc(),
    )


async def top_requests(
    session: AsyncSession, *, event_id: int, limit: int = 10, offset: int = 0
):
    """One page of the chart, ordered by demand."""
    rows = await session.execute(
        select(EventTrack)
        .where(
            EventTrack.event_id == event_id,
            EventTrack.status != TrackStatus.REJECTED,
        )
        .order_by(*_top_ordering())
        .offset(offset)
        .limit(limit)
    )
    return list(rows.scalars().unique())


async def top_count(session: AsyncSession, *, event_id: int) -> int:
    return int(
        await session.scalar(
            select(func.count(EventTrack.id)).where(
                EventTrack.event_id == event_id,
                EventTrack.status != TrackStatus.REJECTED,
            )
        )
        or 0
    )


async def user_track_positions(
    session: AsyncSession, *, user_id: int, event_id: int
) -> list[tuple[int, str]]:
    """Where this person's own tracks sit in the chart.

    Someone who added a track and cannot find it on the first page assumes it
    was lost, so the position is shown explicitly however far down it is.
    """
    ranked = await session.execute(
        select(
            EventTrack.id,
            func.row_number().over(order_by=_top_ordering()).label("position"),
        ).where(
            EventTrack.event_id == event_id,
            EventTrack.status != TrackStatus.REJECTED,
        )
    )
    positions = {row.id: row.position for row in ranked.all()}
    if not positions:
        return []

    mine = await session.execute(
        select(EventTrack.id, Track.artist_name, Track.title)
        .join(Track, Track.id == EventTrack.track_id)
        .join(TrackRequest, TrackRequest.event_track_id == EventTrack.id)
        .where(
            TrackRequest.user_id == user_id,
            EventTrack.event_id == event_id,
            EventTrack.status != TrackStatus.REJECTED,
        )
    )
    result = [
        (positions[row.id], f"{row.artist_name} - {row.title}")
        for row in mine.all()
        if row.id in positions
    ]
    return sorted(result)


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

    from lyfe.core.services import user_service

    await user_service.lock_user(session, user_id)
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
    try:
        async with session.begin_nested():
            session.add(vote)
            await session.flush()
    except IntegrityError:
        return VoteResult.ALREADY_VOTED
    event_track.votes_count += 1

    # Points for the first few likes only.
    paid_votes = await session.scalar(
        select(func.count(PointTransaction.id)).where(
            PointTransaction.user_id == user_id,
            PointTransaction.event_id == event.id,
            PointTransaction.reason_code == PointsReason.VOTE,
        )
    )
    if (paid_votes or 0) < settings.max_paid_votes_per_event:
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


class BoostResult:
    BOOSTED = "BOOSTED"
    NOT_ENOUGH_POINTS = "NOT_ENOUGH_POINTS"
    LIMIT_REACHED = "LIMIT_REACHED"
    EVENT_CLOSED = "EVENT_CLOSED"
    NOT_FOUND = "NOT_FOUND"
    PLAYED = "PLAYED"


@dataclass
class BoostOutcome:
    status: str
    balance: int = 0
    used: int = 0
    score: int = 0


async def boosts_used(session: AsyncSession, *, user_id: int, event_id: int) -> int:
    return int(
        await session.scalar(
            select(func.count(PointTransaction.id)).where(
                PointTransaction.user_id == user_id,
                PointTransaction.event_id == event_id,
                PointTransaction.reason_code == PointsReason.BOOST,
            )
        )
        or 0
    )


async def boost(session: AsyncSession, *, user_id: int, event_track_id: int) -> BoostOutcome:
    """Spend points to lift a track: cost_boost points become cost_boost score.

    Works on any track, own or someone else's — backing a track you love is the
    point. Unlike a guaranteed play it promises nothing, so it is never refunded.
    """
    from lyfe.core.services import user_service

    event_track = await session.get(EventTrack, event_track_id)
    if event_track is None or event_track.status == TrackStatus.REJECTED:
        return BoostOutcome(status=BoostResult.NOT_FOUND)
    if event_track.status == TrackStatus.PLAYED:
        return BoostOutcome(status=BoostResult.PLAYED)

    event = await session.get(Event, event_track.event_id)
    if event is None or not event.accepts_requests(datetime.now(timezone.utc)):
        return BoostOutcome(status=BoostResult.EVENT_CLOSED)

    # Serialise everything this person does with their balance, same as rewards.
    await session.execute(select(User.id).where(User.id == user_id).with_for_update())

    balance = await user_service.get_points_balance(session, user_id)
    used = await boosts_used(session, user_id=user_id, event_id=event.id)
    if used >= settings.max_boosts_per_event:
        return BoostOutcome(status=BoostResult.LIMIT_REACHED, balance=balance, used=used)
    if balance < settings.cost_boost:
        return BoostOutcome(status=BoostResult.NOT_ENOUGH_POINTS, balance=balance, used=used)

    await points_service.award(
        session,
        user_id=user_id,
        delta=-settings.cost_boost,
        reason_code=PointsReason.BOOST,
        idempotency_key=f"boost:{event.id}:{user_id}:{used + 1}",
        event_id=event.id,
        ref_type="event_track",
        ref_id=event_track.id,
    )
    event_track.boost_points += settings.cost_boost
    await session.flush()

    return BoostOutcome(
        status=BoostResult.BOOSTED,
        balance=balance - settings.cost_boost,
        used=used + 1,
        score=event_track.score,
    )
