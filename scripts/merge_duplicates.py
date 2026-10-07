"""Merge duplicate tracks that slipped into an event's list.

Before the matcher learned about guest artists, transliteration and fuzzy
spelling, one song could reach the DJ as two or three rows: "Макс Корж" from
iTunes, "Max Korzh" from Deezer, a YouTube title typed in by hand. This finds
those groups and folds each into its strongest row.

What moves: requests and likes (a person who is on both rows counts once),
boosts, the guaranteed-play pin. Points already paid stay where they are.

Prints the plan by default; nothing is written without --apply.

    python scripts/merge_duplicates.py                 # all events, plan only
    python scripts/merge_duplicates.py --event-id 3    # one event
    python scripts/merge_duplicates.py --apply
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, func, select  # noqa: E402

from lyfe.core.track_resolver import (  # noqa: E402
    SAME_TRACK_THRESHOLD,
    build_normalized_key,
    similarity,
)
from lyfe.db import SessionFactory  # noqa: E402
from lyfe.models import Event, EventTrack, Track, TrackRequest, TrackStatus, TrackVote  # noqa: E402


def _same(a: Track, b: Track) -> bool:
    if build_normalized_key(a.artist_name, a.title) == build_normalized_key(b.artist_name, b.title):
        return True
    return similarity(a.artist_name, a.title, b.artist_name, b.title) >= SAME_TRACK_THRESHOLD


def _strength(row: tuple[EventTrack, Track]) -> tuple:
    event_track, track = row
    # Prefer a catalogue entry (cover, clean name) over a hand-typed one, then demand.
    return (track.provider != "manual", event_track.score, -event_track.id)


async def merge_event(session, event: Event, apply: bool) -> int:
    rows = (
        await session.execute(
            select(EventTrack, Track)
            .join(Track, Track.id == EventTrack.track_id)
            .where(EventTrack.event_id == event.id)
        )
    ).all()
    rows.sort(key=_strength, reverse=True)

    groups: list[list[tuple[EventTrack, Track]]] = []
    for row in rows:
        for group in groups:
            if _same(group[0][1], row[1]):
                group.append(row)
                break
        else:
            groups.append([row])

    merged = 0
    for group in groups:
        if len(group) < 2:
            continue
        keeper, keeper_track = group[0]
        print(f"\n[{event.title}] keep  #{keeper.id}  {keeper_track.display}  ({keeper.score})")
        for loser, loser_track in group[1:]:
            print(f"           merge #{loser.id}  {loser_track.display}  ({loser.score})")
            if apply:
                await _fold(session, keeper, loser)
            merged += 1
        if apply:
            await _recount(session, keeper)
    return merged


async def _fold(session, keeper: EventTrack, loser: EventTrack) -> None:
    keeper_requesters = set(
        (
            await session.execute(
                select(TrackRequest.user_id).where(TrackRequest.event_track_id == keeper.id)
            )
        ).scalars()
    )
    for request in (
        await session.execute(select(TrackRequest).where(TrackRequest.event_track_id == loser.id))
    ).scalars():
        if request.user_id in keeper_requesters:
            await session.delete(request)
        else:
            request.event_track_id = keeper.id
            keeper_requesters.add(request.user_id)
    await session.flush()

    keeper_voters = set(
        (
            await session.execute(
                select(TrackVote.user_id).where(TrackVote.event_track_id == keeper.id)
            )
        ).scalars()
    )
    for vote in (
        await session.execute(select(TrackVote).where(TrackVote.event_track_id == loser.id))
    ).scalars():
        # Someone who asked for the song already counts once; a like on top would
        # make them count twice.
        if vote.user_id in keeper_voters or vote.user_id in keeper_requesters:
            await session.delete(vote)
        else:
            vote.event_track_id = keeper.id
            keeper_voters.add(vote.user_id)
    await session.flush()

    keeper.boost_points += loser.boost_points
    if loser.is_priority and not keeper.is_priority:
        keeper.is_priority = True
        keeper.priority_at = loser.priority_at
    if loser.status == TrackStatus.PLAYED and keeper.status != TrackStatus.PLAYED:
        keeper.status = TrackStatus.PLAYED
        keeper.played_at = loser.played_at
        keeper.played_by_admin_id = loser.played_by_admin_id

    await session.execute(delete(EventTrack).where(EventTrack.id == loser.id))
    await session.flush()


async def _recount(session, keeper: EventTrack) -> None:
    keeper.requests_count = int(
        await session.scalar(
            select(func.count(TrackRequest.id)).where(TrackRequest.event_track_id == keeper.id)
        )
        or 0
    )
    keeper.votes_count = int(
        await session.scalar(
            select(func.count(TrackVote.id)).where(TrackVote.event_track_id == keeper.id)
        )
        or 0
    )


async def rekey_tracks(session, apply: bool) -> int:
    """Bring stored keys in line with the current normaliser, where that does
    not collide with another track."""
    tracks = list((await session.execute(select(Track))).scalars())
    taken = {track.normalized_key for track in tracks}
    changed = 0
    for track in tracks:
        key = build_normalized_key(track.artist_name, track.title)
        if key == track.normalized_key or key in taken:
            continue
        if apply:
            taken.discard(track.normalized_key)
            track.normalized_key = key
        taken.add(key)
        changed += 1
    return changed


async def main(event_id: int | None, apply: bool) -> None:
    async with SessionFactory() as session:
        query = select(Event).order_by(Event.starts_at)
        if event_id:
            query = query.where(Event.id == event_id)
        events = list((await session.execute(query)).scalars())

        total = 0
        for event in events:
            total += await merge_event(session, event, apply)
        rekeyed = await rekey_tracks(session, apply)

        print(f"\nDuplicates: {total} · track keys to update: {rekeyed}")
        if apply:
            await session.commit()
            print("Applied.")
        else:
            print("Plan only. Run with --apply to write.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--event-id", type=int)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.event_id, args.apply))
