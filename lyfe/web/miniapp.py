"""LYFE Mini App — the guest side, inside Telegram.

A second adapter over the same services the bot uses. Nothing here decides
anything: limits, deduplication, points and prices all live in core/services,
so the bot and the Mini App can never disagree about the rules.

Every request carries Telegram's signed initData in a header; that signature is
the only thing that says who the guest is.
"""
import hashlib
import io
import logging
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import segno
from fastapi import APIRouter, Body, Depends, Header, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lyfe.config import get_settings
from lyfe.core import pass_token, telegram_auth, track_resolver
from lyfe.core.services import (
    event_service,
    request_service,
    reward_service,
    season_service,
    user_service,
)
from lyfe.core.services.request_service import AddResult
from lyfe.db import SessionFactory
from lyfe.models import (
    Attendance,
    Event,
    EventTrack,
    PointTransaction,
    RequestSource,
    Reward,
    RewardKind,
    TrackRequest,
    TrackStatus,
    User,
)

logger = logging.getLogger(__name__)
settings = get_settings()

PAGE = Path(__file__).parent / "static" / "app" / "index.html"


def _asset_version() -> str:
    """A short hash of every Mini App file. Asset URLs carry it, so a new
    deploy always reaches phones whose webview cached the previous files."""
    digest = hashlib.sha256()
    for path in sorted(PAGE.parent.rglob("*")):
        if path.is_file():
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:10]


ASSET_VERSION = _asset_version()
TOP_PAGE_SIZE = 30
MAX_QUERY_LENGTH = 200
HISTORY_LIMIT = 30

router = APIRouter()


async def get_session() -> AsyncSession:
    async with SessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def current_user(
    x_telegram_init_data: str = Header(""),
    session: AsyncSession = Depends(get_session),
) -> User:
    tg_user = telegram_auth.verify_init_data(x_telegram_init_data, settings.bot_token)
    if tg_user is None:
        raise HTTPException(status_code=401, detail="open LYFE from Telegram")

    user, _ = await user_service.get_or_create(
        session,
        tg_user_id=tg_user.id,
        username=tg_user.username,
        first_name=tg_user.first_name,
        language_code=tg_user.language_code,
    )
    if user.is_blocked or user.deleted_at is not None:
        raise HTTPException(status_code=403, detail="blocked")
    return user


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------


@router.get("/app", include_in_schema=False)
async def page():
    # The page is small and changes with every release; never let Telegram's
    # webview hold on to an old copy.
    html = (
        PAGE.read_text(encoding="utf-8")
        .replace("__BOT_USERNAME__", settings.bot_username)
        .replace("__ASSET_V__", ASSET_VERSION)
    )
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _tz(event: Event) -> ZoneInfo | timezone:
    try:
        return ZoneInfo(event.city.timezone)
    except Exception:  # noqa: BLE001
        return timezone.utc


def _event_json(event: Event | None) -> dict | None:
    if event is None:
        return None
    tz = _tz(event)
    local_start = event.starts_at.astimezone(tz)
    days = (local_start.date() - datetime.now(tz).date()).days
    return {
        "id": event.id,
        "title": event.title,
        "status": event.status,
        "date": local_start.strftime("%d.%m"),
        "time": local_start.strftime("%H:%M"),
        "venue": event.venue.name if event.venue else None,
        "city": event.city.name if event.city else None,
        "days": max(days, 0),
        "ticket_url": event.ticket_url,
        "accepts_requests": event.accepts_requests(datetime.now(timezone.utc)),
    }


def _candidate_json(resolved: track_resolver.ResolvedTrack) -> dict:
    return {
        "artist_name": resolved.artist_name,
        "title": resolved.title,
        "album_name": resolved.album_name,
        "cover_url": resolved.cover_url,
        "external_url": resolved.external_url,
        "duration_ms": resolved.duration_ms,
        "provider": resolved.provider,
        "provider_track_id": resolved.provider_track_id,
    }


async def _require_event(session: AsyncSession) -> Event:
    event = await event_service.get_next_event(session)
    if event is None:
        raise HTTPException(status_code=409, detail="no_event")
    return event


# --------------------------------------------------------------------------
# Me
# --------------------------------------------------------------------------


@router.get("/api/app/me")
async def me(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    event = await event_service.get_next_event(session)

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

    tonight = None
    if event is not None:
        tonight = {
            "requests_used": await request_service.count_user_requests(
                session, user_id=user.id, event_id=event.id
            ),
            "boosts_used": await request_service.boosts_used(
                session, user_id=user.id, event_id=event.id
            ),
            "own": [
                {"position": position, "name": name}
                for position, name in await request_service.user_track_positions(
                    session, user_id=user.id, event_id=event.id
                )
            ],
        }

    return {
        "user": {
            "name": user.name,
            "lyfe_id": user.lyfe_id,
            "language": user.language,
            "points": await user_service.get_points_balance(session, user.id),
            "requests": requests or 0,
            "played": played or 0,
            "nights": nights or 0,
        },
        "event": _event_json(event),
        "tonight": tonight,
        "season": await _season_json(session, user, event),
        "ticket": await _ticket_json(session, user, event),
        "rules": {
            "requests_max": settings.max_requests_per_user_per_event,
            "boosts_max": settings.max_boosts_per_event,
            "cost_boost": settings.cost_boost,
            "cost_priority": settings.cost_priority_track,
            "points_request": settings.points_music_request,
            "points_vote": settings.points_vote,
            "points_attendance": settings.points_attendance,
        },
    }


def _qr_svg(payload: str, scale: int = 8) -> str:
    qr = segno.make(payload, error="m")
    buffer = io.BytesIO()
    # Black on white whatever the theme: a camera in a dark doorway needs contrast.
    qr.save(buffer, kind="svg", scale=scale, border=3, dark="#000000", light="#ffffff", xmldecl=False)
    return buffer.getvalue().decode()


@router.get("/api/app/pass")
async def lyfe_pass(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    event = await event_service.get_next_event(session)
    ticket = None
    held = []
    if event is not None:
        found = await season_service.ticket_for(session, user_id=user.id, event_id=event.id)
        if found is not None:
            ticket = {"code": found.code, "svg": _qr_svg(found.code, scale=6)}
        held = [
            {"name": r.reward.name, "code": r.code}
            for r in await reward_service.held_by_user(session, user_id=user.id, event_id=event.id)
        ]
    return {
        "svg": _qr_svg(pass_token.build(user.id, settings.admin_secret_key)),
        "lyfe_id": user.lyfe_id,
        "name": user.name,
        "ticket": ticket,
        "held": held,
    }


@router.get("/api/app/history")
async def history(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = await session.execute(
        select(PointTransaction)
        .where(PointTransaction.user_id == user.id)
        .order_by(PointTransaction.id.desc())
        .limit(HISTORY_LIMIT)
    )
    return {
        "items": [
            {"delta": tx.delta, "reason": tx.reason_code, "at": tx.created_at.isoformat()}
            for tx in rows.scalars()
        ]
    }


# --------------------------------------------------------------------------
# TOP REQUESTS
# --------------------------------------------------------------------------


@router.get("/api/app/top")
async def top(
    offset: int = 0,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    event = await event_service.get_next_event(session)
    if event is None:
        return {"event": None, "items": [], "total": 0}

    total = await request_service.top_count(session, event_id=event.id)
    offset = max(0, offset)
    rows = await request_service.top_requests(
        session, event_id=event.id, limit=TOP_PAGE_SIZE, offset=offset
    )
    requested, voted = await request_service.user_interactions(
        session, user_id=user.id, event_track_ids=[r.id for r in rows]
    )

    items = [
        {
            "id": row.id,
            "position": offset + index,
            "artist": row.track.artist_name,
            "title": row.track.title,
            "cover": row.track.cover_url,
            "score": row.score,
            "requests": row.requests_count,
            "votes": row.votes_count,
            "boosts": row.boost_points,
            "status": row.status,
            "priority": row.is_priority,
            "mine": row.id in requested,
            "voted": row.id in voted,
        }
        for index, row in enumerate(rows, start=1)
    ]
    return {
        "event": _event_json(event),
        "items": items,
        "total": total,
        "offset": offset,
        "page_size": TOP_PAGE_SIZE,
    }


@router.post("/api/app/vote/{event_track_id}")
async def vote(
    event_track_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    result = await request_service.add_vote(session, user_id=user.id, event_track_id=event_track_id)
    return {
        "status": result,
        "points": await user_service.get_points_balance(session, user.id),
    }


@router.post("/api/app/boost/{event_track_id}")
async def boost(
    event_track_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    outcome = await request_service.boost(session, user_id=user.id, event_track_id=event_track_id)
    return {
        "status": outcome.status,
        "points": outcome.balance,
        "boosts_used": outcome.used,
        "score": outcome.score,
    }


# --------------------------------------------------------------------------
# Adding a track
# --------------------------------------------------------------------------


@router.post("/api/app/search")
async def search(
    payload: dict = Body(...),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    query = str(payload.get("q") or "").strip()[:MAX_QUERY_LENGTH]
    if len(query) < 2:
        return {"status": "empty", "candidates": []}

    resolution = await track_resolver.resolve_detailed(query)

    if resolution.link_unreadable:
        return {"status": "link_unreadable", "candidates": []}
    if not resolution.candidates:
        return {
            "status": "link_no_match" if resolution.link else "not_found",
            "link_text": resolution.link_text,
            "candidates": [],
        }

    event = await event_service.get_next_event(session)
    matches: list[EventTrack | None] = [None] * len(resolution.candidates)
    mine: set[int] = set()
    if event is not None:
        matches = await request_service.match_in_event(
            session, event_id=event.id, candidates=resolution.candidates
        )
        mine, _ = await request_service.user_interactions(
            session, user_id=user.id, event_track_ids=[m.id for m in matches if m]
        )

    # A link names one recording. When the first result is clearly it, the page
    # shows that one and tucks covers and remixes away.
    exact_first = False
    if resolution.link_text:
        parsed = track_resolver.split_artist_title(resolution.link_text)
        first = resolution.candidates[0]
        if parsed:
            exact_first = (
                track_resolver.similarity(parsed[0], parsed[1], first.artist_name, first.title)
                >= track_resolver.SAME_TRACK_THRESHOLD
            )

    candidates = []
    seen_rows: set[int] = set()
    for resolved, match in zip(resolution.candidates, matches):
        # Two results that both land on one row in tonight's list are one song.
        if match is not None:
            if match.id in seen_rows:
                continue
            seen_rows.add(match.id)
        candidates.append(
            {
                "token": telegram_auth.sign_payload(
                    _candidate_json(resolved), settings.admin_secret_key
                ),
                "artist": resolved.artist_name,
                "title": resolved.title,
                "album": resolved.album_name,
                "cover": resolved.cover_url,
                "in_event": (
                    {"id": match.id, "score": match.score, "status": match.status}
                    if match is not None
                    else None
                ),
                "mine": match is not None and match.id in mine,
            }
        )

    return {
        "status": "ok",
        "link_text": resolution.link_text,
        "exact_first": exact_first,
        "candidates": candidates,
    }


@router.post("/api/app/request")
async def add_request(
    payload: dict = Body(...),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    event = await _require_event(session)

    token = payload.get("token")
    manual = str(payload.get("manual") or "").strip()[:MAX_QUERY_LENGTH]

    if token:
        data = telegram_auth.read_payload(str(token), settings.admin_secret_key)
        if data is None:
            raise HTTPException(status_code=400, detail="bad token")
        resolved = track_resolver.ResolvedTrack(**data)
        source = RequestSource.SEARCH
        raw_input = str(payload.get("q") or "")[:500] or None
    elif manual:
        if track_resolver.find_url(manual):
            return {"status": "MANUAL_IS_LINK"}
        if not track_resolver.split_artist_title(manual):
            return {"status": "MANUAL_FORMAT"}
        resolved = track_resolver.manual_track(manual)
        source = RequestSource.MANUAL
        raw_input = manual
    else:
        raise HTTPException(status_code=400, detail="nothing to add")

    outcome = await request_service.add_request(
        session,
        user_id=user.id,
        event=event,
        resolved=resolved,
        source=source,
        raw_input=raw_input,
    )

    response = {
        "status": outcome.status,
        "requests_used": outcome.user_request_count,
        "points": await user_service.get_points_balance(session, user.id),
    }
    if outcome.track is not None:
        response["track"] = {"artist": outcome.track.artist_name, "title": outcome.track.title}
    if outcome.status in (AddResult.ADDED, AddResult.ALREADY_REQUESTED):
        response["requests_count"] = outcome.requests_count
        response["event_track_id"] = outcome.event_track.id if outcome.event_track else None
    return response


# --------------------------------------------------------------------------
# Guaranteed play
# --------------------------------------------------------------------------


async def _priority_reward(session: AsyncSession, event: Event) -> Reward | None:
    for reward in await reward_service.available_rewards(session, event=event):
        if reward.kind == RewardKind.PRIORITY_TRACK:
            return reward
    return None


@router.get("/api/app/priority")
async def priority_options(
    user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    event = await event_service.get_next_event(session)
    if event is None:
        return {"available": False}
    reward = await _priority_reward(session, event)
    if reward is None:
        return {"available": False}

    pinned = await session.scalar(
        select(func.count(EventTrack.id)).where(
            EventTrack.event_id == event.id, EventTrack.is_priority.is_(True)
        )
    )
    tracks = await reward_service.user_requests_for_event(
        session, user_id=user.id, event_id=event.id
    )
    already = await session.scalar(
        select(func.count(EventTrack.id))
        .join(TrackRequest, TrackRequest.event_track_id == EventTrack.id)
        .where(
            TrackRequest.user_id == user.id,
            EventTrack.event_id == event.id,
            EventTrack.is_priority.is_(True),
        )
    )
    return {
        "available": True,
        "reward_id": reward.id,
        "cost": reward.cost_points,
        "left": max(0, reward_service.MAX_PRIORITY_PER_EVENT - (pinned or 0)),
        "has_one": bool(already),
        "tracks": [
            {"id": et.id, "artist": et.track.artist_name, "title": et.track.title}
            for et in tracks
        ],
    }


@router.post("/api/app/priority/{event_track_id}")
async def buy_priority(
    event_track_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    event = await _require_event(session)
    reward = await _priority_reward(session, event)
    if reward is None:
        return {"status": "UNAVAILABLE"}

    # Only on a track this person asked for — the guarantee is for your own pick.
    own = await session.scalar(
        select(TrackRequest.id).where(
            TrackRequest.event_track_id == event_track_id, TrackRequest.user_id == user.id
        )
    )
    if own is None:
        return {"status": "NO_TRACK"}

    outcome = await reward_service.purchase(
        session,
        user=user,
        reward=reward,
        event=event,
        payload={"event_track_id": event_track_id},
    )
    return {"status": outcome.status, "points": outcome.balance}


# --------------------------------------------------------------------------
# Season: pumpkin hunt and PUMPKIN RUSH
# --------------------------------------------------------------------------


async def _season_json(session: AsyncSession, user: User, event: Event | None) -> dict | None:
    if not settings.season or event is None:
        return None
    best = await season_service.best_score(session, user_id=user.id, event_id=event.id)
    return {
        "name": settings.season,
        "pumpkins": list(season_service.PUMPKINS),
        "found": await season_service.pumpkins_found(session, user_id=user.id, event_id=event.id),
        "pumpkin_points": season_service.POINTS_PER_PUMPKIN,
        "pumpkin_bonus": season_service.ALL_PUMPKINS_BONUS,
        "game": {
            "attempts_left": max(
                0,
                season_service.ATTEMPTS_PER_EVENT
                - await season_service.attempts_used(session, user_id=user.id, event_id=event.id),
            ),
            "attempts": season_service.ATTEMPTS_PER_EVENT,
            "best": best,
            "prizes": list(season_service.PRIZES),
            "seconds": season_service.GAME_SECONDS,
        },
    }


@router.post("/api/app/pumpkin/{pumpkin}")
async def pumpkin(
    pumpkin: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    event = await _require_event(session)
    if not settings.season:
        return {"status": "OFF"}
    outcome = await season_service.find_pumpkin(session, user=user, event=event, pumpkin=pumpkin)
    return {
        "status": outcome.status,
        "found": outcome.found,
        "gained": outcome.gained,
        "bonus": outcome.bonus,
        "points": await user_service.get_points_balance(session, user.id),
    }


@router.get("/api/app/game")
async def game_board(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    event = await event_service.get_next_event(session)
    if event is None or not settings.season:
        return {"available": False}
    board = await season_service.leaderboard(session, event_id=event.id)
    return {
        "available": True,
        "season": await _season_json(session, user, event),
        "board": [
            {"name": row["name"], "lyfe_id": row["lyfe_id"], "score": row["score"], "me": row["user_id"] == user.id}
            for row in board
        ],
    }


@router.post("/api/app/game/start")
async def game_start(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    event = await _require_event(session)
    if not settings.season:
        return {"status": "OFF"}
    game = await season_service.start_game(session, user=user, event=event)
    if game is None:
        return {"status": "NO_ATTEMPTS"}
    return {
        "status": "OK",
        "id": game.id,
        "seconds": season_service.GAME_SECONDS,
        "pieces": [piece.__dict__ for piece in season_service.schedule(game.seed)],
    }


@router.post("/api/app/game/{game_id}/finish")
async def game_finish(
    game_id: int,
    payload: dict = Body(...),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    hits = payload.get("hits") if isinstance(payload.get("hits"), list) else []
    game = await season_service.finish_game(session, user=user, game_id=game_id, hits=hits)
    if game is None:
        return {"status": "UNKNOWN"}
    event = await session.get(Event, game.event_id)
    board = await season_service.leaderboard(session, event_id=event.id, limit=50)
    place = next((i + 1 for i, row in enumerate(board) if row["user_id"] == user.id), None)
    return {
        "status": "OK",
        "score": game.score,
        "best": await season_service.best_score(session, user_id=user.id, event_id=event.id),
        "place": place,
        "attempts_left": max(
            0,
            season_service.ATTEMPTS_PER_EVENT
            - await season_service.attempts_used(session, user_id=user.id, event_id=event.id),
        ),
    }


# --------------------------------------------------------------------------
# Tickets (GoOut)
# --------------------------------------------------------------------------


async def _ticket_json(session: AsyncSession, user: User, event: Event | None) -> dict | None:
    if event is None:
        return None
    ticket = await season_service.ticket_for(session, user_id=user.id, event_id=event.id)
    return {"code": ticket.code} if ticket else None


@router.post("/api/app/ticket")
async def ticket_attach(
    payload: dict = Body(...),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    event = await _require_event(session)
    status = await season_service.attach_ticket(
        session, user=user, event=event, code=str(payload.get("code") or "")[:200]
    )
    return {"status": status}


@router.delete("/api/app/ticket")
async def ticket_detach(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    event = await _require_event(session)
    await season_service.detach_ticket(session, user=user, event=event)
    return {"status": "OK"}


# --------------------------------------------------------------------------
# Door rewards: bought here, handed over by whoever scans the LYFE PASS
# --------------------------------------------------------------------------


@router.get("/api/app/rewards")
async def rewards(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    event = await event_service.get_next_event(session)
    if event is None:
        return {"items": [], "held": []}
    held = await reward_service.held_by_user(session, user_id=user.id, event_id=event.id)
    held_ids = {r.reward_id for r in held}
    return {
        "items": [
            {
                "id": r.id,
                "name": r.name,
                "description": r.description,
                "cost": r.cost_points,
                "held": r.id in held_ids,
            }
            for r in await reward_service.available_rewards(session, event=event)
            if r.kind == RewardKind.DOOR
        ],
        "held": [{"name": r.reward.name, "code": r.code} for r in held],
    }


@router.post("/api/app/rewards/{reward_id}/buy")
async def reward_buy(
    reward_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    event = await _require_event(session)
    reward = await session.get(Reward, reward_id)
    if reward is None or reward.kind != RewardKind.DOOR:
        return {"status": "UNAVAILABLE"}
    outcome = await reward_service.purchase(session, user=user, reward=reward, event=event)
    return {
        "status": outcome.status,
        "points": outcome.balance,
        "code": outcome.redemption.code if outcome.redemption else None,
    }
