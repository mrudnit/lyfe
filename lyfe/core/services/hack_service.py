"""«Взлом»: a needle runs round a lock, tap while it is in the green zone.

Ten locks, each one narrower and faster. A miss is WASTED and the run ends.
A person's best run counts for their gang.

Loot per opened lock n (see lock_loot):
  * BASE × n for opening it;
  * up to AIM × n for hitting the middle of the zone (falls off linearly to
    nothing at the zone's edge);
  * FAST × n for a tap on the needle's first pass through the zone,
    half of that on the second pass, nothing later.
So two players who open the same locks almost never get the same sum, and
the gang board does not end in a pile of equal scores.

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
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lyfe.config import get_settings
from lyfe.models import Event, GameSession, User

settings = get_settings()

KIND = "hack"
LEVELS = 10
BASE, AIM, FAST = 100, 100, 40          # $ per lock number, see lock_loot
LOOT_STEP = BASE                         # kept for older pages
WIDTH_FIRST, WIDTH_LAST = 60.0, 12.0     # degrees of green
SPEED_FIRST, SPEED_LAST = 150.0, 540.0   # degrees per second
SPEED_JITTER = 0.08                      # each lock ±8 %, so no two runs feel the same
GRACE_DEG = 3.0                          # finger and frame lag
MIN_TAP, MAX_TAP = 0.12, 15.0            # seconds; no tap in 15 s is a miss
REACT = 0.35                             # a pass that starts sooner than this is too quick for anyone
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
        speed = round((SPEED_FIRST + (SPEED_LAST - SPEED_FIRST) * k) * rng.uniform(1 - SPEED_JITTER, 1 + SPEED_JITTER), 2)
        # keep the zone well away from the needle's start so the first moment is never a free hit
        start = round(rng.uniform(40.0, 320.0 - width), 2)
        out.append(Lock(n=n, start=start, width=width, speed=speed, dir=1 if rng.random() < 0.5 else -1))
    return out


def needle(lock: Lock, t: float) -> float:
    return (lock.dir * lock.speed * t) % 360.0


def in_zone(lock: Lock, angle: float) -> bool:
    d = (angle - lock.start) % 360.0
    return d <= lock.width + GRACE_DEG or d >= 360.0 - GRACE_DEG


def aim(lock: Lock, angle: float) -> float:
    """1.0 in the middle of the zone, 0.0 at its edge (and in the grace band)."""
    pos = (angle - lock.start) % 360.0
    if pos > 180.0:
        pos -= 360.0                     # just before the zone, inside the grace band
    half = lock.width / 2
    return max(0.0, 1.0 - abs(pos - half) / half)


def lap(lock: Lock, t: float) -> int:
    """0 if the tap came on the needle's first catchable pass through the zone
    (one that starts after REACT seconds), 1 on the next, and so on."""
    edge = lock.start if lock.dir == 1 else 360.0 - lock.start - lock.width
    turn = 360.0 / lock.speed
    first = (edge - GRACE_DEG) / lock.speed
    while first < REACT:
        first += turn
    return max(0, int((t - first) // turn))


def lock_loot(lock: Lock, t: float) -> int:
    n = lock.n
    fast = FAST * n if lap(lock, t) == 0 else FAST * n // 2 if lap(lock, t) == 1 else 0
    return BASE * n + round(AIM * n * aim(lock, needle(lock, t))) + fast


def loot_for(levels: int) -> int:
    """The base part only: what opening that many locks is worth at the least."""
    return BASE * levels * (levels + 1) // 2


def replay(seed: int, taps: list) -> tuple[int, float, int]:
    """(locks opened, seconds the taps took, loot). Stops at the first bad tap."""
    opened, spent, loot = 0, 0.0, 0
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
        loot += lock_loot(lock, t)
    return opened, spent, loot


# --------------------------------------------------------------------------


def is_open(event: Event | None) -> bool:
    from lyfe.core.services import season_service

    return event is not None and season_service.is_open(event)


def closes_at(event: Event | None) -> datetime | None:
    from lyfe.core.services import season_service

    return season_service.closes_at(event) if event is not None else None


CLUB_TZ = ZoneInfo("Europe/Bratislava")


def day_start(now: datetime | None = None) -> datetime:
    """Midnight of today in the club's time zone: the daily runs reset then."""
    local = (now or datetime.now(timezone.utc)).astimezone(CLUB_TZ)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


async def _runs(session: AsyncSession, *, user_id: int, event_id: int, since: datetime | None = None) -> int:
    q = select(func.count(GameSession.id)).where(
        GameSession.user_id == user_id, GameSession.event_id == event_id, GameSession.kind == KIND
    )
    if since is not None:
        q = q.where(GameSession.started_at >= since)
    return int(await session.scalar(q) or 0)


async def attempts_today(session: AsyncSession, *, user_id: int, event_id: int) -> int:
    return await _runs(session, user_id=user_id, event_id=event_id, since=day_start())


async def attempts_left(session: AsyncSession, *, user_id: int, event_id: int) -> tuple[int, int]:
    """(runs left today, runs left for the whole party). Today never exceeds the total."""
    total = max(0, settings.hack_attempts_total - await _runs(session, user_id=user_id, event_id=event_id))
    today = max(0, settings.hack_attempts_per_day - await attempts_today(session, user_id=user_id, event_id=event_id))
    return min(today, total), total


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
    """Per person: their best loot and when they first reached it (for ties)."""
    best = (
        select(GameSession.user_id, func.max(GameSession.score).label("score"))
        .where(GameSession.event_id == event_id, GameSession.kind == KIND, GameSession.score > 0)
        .group_by(GameSession.user_id)
        .subquery()
    )
    return (
        select(best.c.user_id, best.c.score, func.min(GameSession.finished_at).label("reached_at"))
        .join(GameSession, (GameSession.user_id == best.c.user_id) & (GameSession.score == best.c.score))
        .where(GameSession.event_id == event_id, GameSession.kind == KIND)
        .group_by(best.c.user_id, best.c.score)
        .subquery()
    )


async def start(session: AsyncSession, *, user: User, event: Event | None) -> GameSession | str:
    """A new run, or why not: "CLOSED", "NO_GANG", "NO_ATTEMPTS" (none left
    today) or "NO_ATTEMPTS_LEFT" (all runs for the party used).
    Only people in a gang play: the loot only counts for a gang."""
    if not is_open(event):
        return "CLOSED"
    from lyfe.core.services import gang_service

    if await gang_service.membership(session, user_id=user.id, event_id=event.id) is None:
        return "NO_GANG"
    await session.execute(select(User.id).where(User.id == user.id).with_for_update())
    today, total = await attempts_left(session, user_id=user.id, event_id=event.id)
    if total <= 0:
        return "NO_ATTEMPTS_LEFT"
    if today <= 0:
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
    opened, spent, loot = replay(game.seed, taps if isinstance(taps, list) else [])
    elapsed = (now - game.started_at).total_seconds()
    # a run cannot end before its own taps could have happened, nor turn up much later
    if elapsed + 0.5 < spent or now - game.started_at > MAX_RUN:
        opened, loot = 0, 0
    game.finished_at = now
    game.score = loot
    await session.flush()
    return Finish("DONE", levels=opened, score=game.score,
                  best=await best(session, user_id=user.id, event_id=game.event_id))
