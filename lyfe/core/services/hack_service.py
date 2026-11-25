"""«Взлом»: a needle runs round a lock, tap while it is in the green zone.

Ten locks, each one narrower and faster. A miss is WASTED and the run ends;
the loot is what the cleared locks were worth (lock n pays LOOT_STEP × n, so
all ten pay 5 500). A person's best run counts for their gang.

Scored by the server, like PUMPKIN RUSH: the server picks a seed, derives
every lock from it (zone, width, speed, direction) and gives the page the
same numbers so it can draw them. The page reports how long after each lock
appeared the tap came; the server replays the needle from its own copy and
stops at the first tap that was not in the zone. A modified page can still
play perfectly, but it cannot claim a lock it did not open, and a run cannot
be finished faster than its own taps.
"""
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lyfe.config import get_settings
from lyfe.models import Event, GameSession, User

settings = get_settings()

KIND = "hack"
LEVELS = 10
LOOT_STEP = 100
WIDTH_FIRST, WIDTH_LAST = 64.0, 16.0     # degrees of green
SPEED_FIRST, SPEED_LAST = 150.0, 480.0   # degrees per second
GRACE_DEG = 3.0                          # finger and frame lag
MIN_TAP, MAX_TAP = 0.12, 15.0            # seconds; no tap in 15 s is a miss
MAX_RUN = timedelta(minutes=30)


@dataclass(frozen=True)
class Lock:
    n: int
    start: float     # where the green zone begins, degrees clockwise from 12 o'clock
    width: float
    speed: float
    dir: int         # 1 clockwise, -1 counter-clockwise; the needle starts at 0°


def locks(seed: int) -> list[Lock]:
    out = []
    for n in range(1, LEVELS + 1):
        rng = random.Random(seed * 31 + n)
        k = (n - 1) / (LEVELS - 1)
        width = round(WIDTH_FIRST + (WIDTH_LAST - WIDTH_FIRST) * k, 2)
        speed = round(SPEED_FIRST + (SPEED_LAST - SPEED_FIRST) * k, 2)
        # keep the zone well away from the needle's start so the first moment is never a free hit
        start = round(rng.uniform(40.0, 320.0 - width), 2)
        out.append(Lock(n=n, start=start, width=width, speed=speed, dir=1 if rng.random() < 0.5 else -1))
    return out


def needle(lock: Lock, t: float) -> float:
    return (lock.dir * lock.speed * t) % 360.0


def in_zone(lock: Lock, angle: float) -> bool:
    d = (angle - lock.start) % 360.0
    return d <= lock.width + GRACE_DEG or d >= 360.0 - GRACE_DEG


def loot_for(levels: int) -> int:
    return LOOT_STEP * levels * (levels + 1) // 2


def replay(seed: int, taps: list) -> tuple[int, float]:
    """(locks opened, seconds the taps took). Stops at the first bad tap."""
    opened, spent = 0, 0.0
    for lock, raw in zip(locks(seed), taps[:LEVELS]):
        try:
            t = float(raw)
        except (TypeError, ValueError):
            break
        if not (MIN_TAP <= t <= MAX_TAP):
            break
        spent += t
        if not in_zone(lock, needle(lock, t)):
            break
        opened += 1
    return opened, spent


# --------------------------------------------------------------------------


def is_open(event: Event | None) -> bool:
    from lyfe.core.services import season_service

    return event is not None and season_service.is_open(event)


def closes_at(event: Event | None) -> datetime | None:
    from lyfe.core.services import season_service

    return season_service.closes_at(event) if event is not None else None


async def attempts_today(session: AsyncSession, *, user_id: int) -> int:
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    return int(
        await session.scalar(
            select(func.count(GameSession.id)).where(
                GameSession.user_id == user_id, GameSession.kind == KIND, GameSession.started_at >= since
            )
        )
        or 0
    )


async def best(session: AsyncSession, *, user_id: int, event_id: int) -> int:
    return int(
        await session.scalar(
            select(func.max(GameSession.score)).where(
                GameSession.user_id == user_id, GameSession.event_id == event_id, GameSession.kind == KIND
            )
        )
        or 0
    )


def best_runs_subquery(event_id: int):
    return (
        select(GameSession.user_id, func.max(GameSession.score).label("score"))
        .where(GameSession.event_id == event_id, GameSession.kind == KIND, GameSession.score > 0)
        .group_by(GameSession.user_id)
        .subquery()
    )


async def start(session: AsyncSession, *, user: User, event: Event | None) -> GameSession | str:
    """A new run, or why not: "CLOSED" or "NO_ATTEMPTS"."""
    if not is_open(event):
        return "CLOSED"
    await session.execute(select(User.id).where(User.id == user.id).with_for_update())
    if await attempts_today(session, user_id=user.id) >= settings.hack_attempts_per_day:
        return "NO_ATTEMPTS"
    game = GameSession(
        event_id=event.id,
        user_id=user.id,
        kind=KIND,
        seed=random.SystemRandom().randrange(1, 2**31 - 1),
        started_at=datetime.now(timezone.utc),
    )
    session.add(game)
    await session.flush()
    return game


@dataclass
class Finish:
    status: str          # DONE, NOT_FOUND
    levels: int = 0
    score: int = 0
    best: int = 0


async def finish(session: AsyncSession, *, user: User, game_id: int, taps: list) -> Finish:
    game = await session.get(GameSession, game_id, with_for_update=True)
    if game is None or game.user_id != user.id or game.kind != KIND or game.finished_at is not None:
        return Finish("NOT_FOUND")
    now = datetime.now(timezone.utc)
    opened, spent = replay(game.seed, taps if isinstance(taps, list) else [])
    elapsed = (now - game.started_at).total_seconds()
    # a run cannot end before its own taps could have happened, nor turn up much later
    if elapsed + 0.5 < spent or now - game.started_at > MAX_RUN:
        opened = 0
    game.finished_at = now
    game.score = loot_for(opened)
    await session.flush()
    return Finish("DONE", levels=opened, score=game.score,
                  best=await best(session, user_id=user.id, event_id=game.event_id))
