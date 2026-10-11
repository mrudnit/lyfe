"""Seasonal fun: the pumpkin hunt and PUMPKIN RUSH (top 5 win free entry).

PUMPKIN RUSH is scored by the server, not the phone. The server picks a seed,
derives every pumpkin from it (when it appears, where, for how long, what it
is worth) and hands the schedule to the page. The page reports which pumpkins
were tapped and when; the server recomputes the score from its own copy and
drops any tap that could not have happened. A modified page can still play
perfectly, but it cannot invent pumpkins or points.
"""
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lyfe.core.services import points_service
from lyfe.models import Event, EventStatus, GameSession, PointsReason, PointTransaction, Ticket, TicketProvider, User

# --------------------------------------------------------------------------
# Pumpkin hunt
# --------------------------------------------------------------------------

# One pumpkin hidden on each screen. The ids are where they sit; the page only
# draws the ones not found yet.
PUMPKINS = ("home", "add", "top", "me", "points")
POINTS_PER_PUMPKIN = 2
ALL_PUMPKINS_BONUS = 5


def _pumpkin_key(event_id: int, user_id: int, pumpkin: str) -> str:
    return f"pumpkin:{event_id}:{user_id}:{pumpkin}"


async def pumpkins_found(session: AsyncSession, *, user_id: int, event_id: int) -> list[str]:
    rows = await session.execute(
        select(PointTransaction.idempotency_key).where(
            PointTransaction.user_id == user_id,
            PointTransaction.idempotency_key.like(f"pumpkin:{event_id}:{user_id}:%"),
        )
    )
    found = [key.rsplit(":", 1)[1] for key in rows.scalars()]
    return [p for p in PUMPKINS if p in found]


@dataclass
class PumpkinOutcome:
    status: str          # FOUND, ALREADY, UNKNOWN
    found: list[str]
    gained: int = 0
    bonus: int = 0


async def find_pumpkin(
    session: AsyncSession, *, user: User, event: Event, pumpkin: str
) -> PumpkinOutcome:
    if pumpkin not in PUMPKINS:
        return PumpkinOutcome(status="UNKNOWN", found=[])

    from lyfe.core.services import user_service

    await user_service.lock_user(session, user.id)

    tx = await points_service.award(
        session,
        user_id=user.id,
        delta=POINTS_PER_PUMPKIN,
        reason_code=PointsReason.PUMPKIN,
        idempotency_key=_pumpkin_key(event.id, user.id, pumpkin),
        event_id=event.id,
        ref_type="pumpkin",
    )
    found = await pumpkins_found(session, user_id=user.id, event_id=event.id)
    if tx is None:
        return PumpkinOutcome(status="ALREADY", found=found)

    bonus = 0
    if len(found) == len(PUMPKINS):
        bonus_tx = await points_service.award(
            session,
            user_id=user.id,
            delta=ALL_PUMPKINS_BONUS,
            reason_code=PointsReason.PUMPKIN,
            idempotency_key=f"pumpkin_all:{event.id}:{user.id}",
            event_id=event.id,
            ref_type="pumpkin",
        )
        bonus = ALL_PUMPKINS_BONUS if bonus_tx else 0
    return PumpkinOutcome(status="FOUND", found=found, gained=POINTS_PER_PUMPKIN, bonus=bonus)


# --------------------------------------------------------------------------
# PUMPKIN RUSH
# --------------------------------------------------------------------------

GAME_KIND = "pumpkin_rush"
GAME_SECONDS = 20.0
ATTEMPTS_PER_EVENT = 2
# The five best players get in free. The board freezes a day before the
# party so the winners know in time; scripts/award_game.py hands out entries.
FREE_ENTRY_PLACES = 5
CLOSES_BEFORE = timedelta(hours=24)
# Time a tap may arrive after the pumpkin vanished: finger and network lag.
TAP_GRACE = 0.25
# Scoring: a streak of good taps multiplies points (x2 from 5 in a row, up to
# x5); a missed pumpkin or a ghost breaks the streak. A fast tap (in the first
# 40% of the pumpkin's life) earns +1 before the multiplier.
STREAK_STEP = 5
MAX_MULT = 5
FAST_SHARE = 0.4
GHOST_PENALTY = 3


@dataclass(frozen=True)
class Piece:
    id: int
    at: float      # seconds after start
    ttl: float     # how long it stays
    x: float       # 0..1 across the field
    y: float       # 0..1 down the field
    kind: str      # pumpkin, gold, ghost
    value: int


def schedule(seed: int) -> list[Piece]:
    """Every piece of one round, derived from the seed alone. It speeds up:
    shorter life, shorter gaps, more ghosts, and later two at once."""
    rng = random.Random(seed)
    pieces: list[Piece] = []
    t, i = 0.5, 0
    while t < GAME_SECONDS - 0.4:
        progress = t / GAME_SECONDS
        burst = 2 if progress > 0.4 and rng.random() < 0.15 + 0.3 * progress else 1
        for _ in range(burst):
            roll = rng.random()
            if roll < 0.08:
                kind, value = "gold", 3
            elif roll < 0.08 + 0.14 + 0.22 * progress:
                kind, value = "ghost", -GHOST_PENALTY
            else:
                kind, value = "pumpkin", 1
            ttl = 1.35 - 0.8 * progress + rng.uniform(-0.08, 0.08)
            if kind == "ghost":
                ttl += 0.3                 # ghosts linger to bait a tap
            pieces.append(
                Piece(
                    id=i,
                    at=round(t, 3),
                    ttl=round(max(0.5, ttl), 3),
                    x=round(rng.uniform(0.12, 0.88), 3),
                    y=round(rng.uniform(0.14, 0.86), 3),
                    kind=kind,
                    value=value,
                )
            )
            i += 1
        t += max(0.2, 0.62 - 0.38 * progress + rng.uniform(-0.1, 0.1))
    return pieces


def tap_points(piece: Piece, t: float, streak: int) -> int:
    """What a good tap is worth: (value + fast bonus) × streak multiplier."""
    fast = 1 if t - piece.at <= FAST_SHARE * piece.ttl else 0
    mult = min(MAX_MULT, 1 + streak // STREAK_STEP)
    return (piece.value + fast) * mult


def score_hits(seed: int, hits: list[dict]) -> int:
    """Replay the round on the server. Taps that could not have happened are
    dropped; pumpkins nobody tapped break the streak when they vanish."""
    pieces = schedule(seed)
    by_id = {p.id: p for p in pieces}
    taps: dict[int, float] = {}
    for hit in hits[:300]:
        try:
            piece = by_id[int(hit["id"])]
            t = float(hit["t"])
        except (KeyError, TypeError, ValueError):
            continue
        if piece.id in taps:
            continue
        if piece.at - 0.05 <= t <= piece.at + piece.ttl + TAP_GRACE:
            taps[piece.id] = min(t, piece.at + piece.ttl)
    events = [(t, 0, by_id[pid]) for pid, t in taps.items()]
    events += [(p.at + p.ttl, 1, p) for p in pieces if p.value > 0 and p.id not in taps]
    events.sort(key=lambda e: (e[0], e[1]))
    score = streak = 0
    for t, missed, piece in events:
        if missed:
            streak = 0
        elif piece.value < 0:
            score = max(0, score + piece.value)
            streak = 0
        else:
            score += tap_points(piece, t, streak)
            streak += 1
    return score


def closes_at(event: Event) -> datetime | None:
    return event.starts_at - CLOSES_BEFORE if event.starts_at else None


def is_waiting(event: Event, now: datetime | None = None) -> bool:
    """The anchor is a party that is over or already under way — the game
    waits for the next one to be announced."""
    now = now or datetime.now(timezone.utc)
    return event.status == EventStatus.ENDED or bool(event.starts_at and event.starts_at <= now)


def is_open(event: Event, now: datetime | None = None) -> bool:
    if is_waiting(event, now):
        return False
    end = closes_at(event)
    return end is None or (now or datetime.now(timezone.utc)) < end


async def attempts_used(session: AsyncSession, *, user_id: int, event_id: int) -> int:
    return int(
        await session.scalar(
            select(func.count(GameSession.id)).where(
                GameSession.user_id == user_id,
                GameSession.event_id == event_id,
                GameSession.kind == GAME_KIND,
            )
        )
        or 0
    )


async def best_score(session: AsyncSession, *, user_id: int, event_id: int) -> int | None:
    return await session.scalar(
        select(func.max(GameSession.score)).where(
            GameSession.user_id == user_id,
            GameSession.event_id == event_id,
            GameSession.kind == GAME_KIND,
        )
    )


async def start_game(session: AsyncSession, *, user: User, event: Event) -> GameSession | str:
    """A new round, or why not: "CLOSED" (board frozen) or "NO_ATTEMPTS"."""
    if not is_open(event):
        return "CLOSED"
    # Serialise this person's attempts so two taps cannot open a third round.
    await session.execute(select(User.id).where(User.id == user.id).with_for_update())
    if await attempts_used(session, user_id=user.id, event_id=event.id) >= ATTEMPTS_PER_EVENT:
        return "NO_ATTEMPTS"
    game = GameSession(
        event_id=event.id,
        user_id=user.id,
        kind=GAME_KIND,
        seed=random.SystemRandom().randrange(1, 2**31 - 1),
        started_at=datetime.now(timezone.utc),
    )
    session.add(game)
    await session.flush()
    return game


async def finish_game(
    session: AsyncSession, *, user: User, game_id: int, hits: list[dict]
) -> GameSession | None:
    game = await session.get(GameSession, game_id, with_for_update=True)
    if game is None or game.user_id != user.id or game.finished_at is not None:
        return None
    now = datetime.now(timezone.utc)
    elapsed = (now - game.started_at).total_seconds()
    # A round cannot be finished before it could have been played, and a
    # result that turns up an hour later is not this round's.
    if elapsed < GAME_SECONDS - 2 or elapsed > GAME_SECONDS + 600:
        game.finished_at = now
        game.score = 0
    else:
        game.finished_at = now
        game.score = score_hits(game.seed, hits)
    await session.flush()
    return game


async def leaderboard(session: AsyncSession, *, event_id: int, limit: int = 10) -> list[dict]:
    """Each player's best round. Equal scores: whoever got there first ranks higher."""
    best = (
        select(GameSession.user_id, GameSession.score, GameSession.finished_at)
        .where(
            GameSession.event_id == event_id,
            GameSession.kind == GAME_KIND,
            GameSession.score > 0,
        )
        .order_by(GameSession.user_id, GameSession.score.desc(), GameSession.finished_at.asc())
        .distinct(GameSession.user_id)
        .subquery()
    )
    rows = await session.execute(
        select(User, best.c.score)
        .join(best, best.c.user_id == User.id)
        .order_by(best.c.score.desc(), best.c.finished_at.asc())
        .limit(limit)
    )
    return [
        {"user_id": user.id, "name": user.name, "lyfe_id": user.lyfe_id, "score": int(score)}
        for user, score in rows.all()
    ]


async def award_free_entries(session: AsyncSession, *, event: Event) -> list[tuple[User, int]]:
    """Top five get free entry, once: a PRIZE ticket on their LYFE PASS for
    this event. Ties on score go to whoever was first."""
    won = []
    for place, row in enumerate(await leaderboard(session, event_id=event.id, limit=FREE_ENTRY_PLACES), start=1):
        code = f"PUMPKIN RUSH #{place}"
        ticket = await ticket_for(session, user_id=row["user_id"], event_id=event.id)
        if ticket is not None and ticket.provider == TicketProvider.PRIZE:
            continue
        if ticket is None:
            session.add(Ticket(event_id=event.id, user_id=row["user_id"], provider=TicketProvider.PRIZE, code=code))
        else:                          # an old GoOut code on file — the prize replaces it
            ticket.provider, ticket.code = TicketProvider.PRIZE, code
        await session.flush()
        won.append((await session.get(User, row["user_id"]), place))
    return won


# --------------------------------------------------------------------------
# Free entry (PUMPKIN RUSH prize)
# --------------------------------------------------------------------------


async def ticket_for(session: AsyncSession, *, user_id: int, event_id: int) -> Ticket | None:
    return await session.scalar(
        select(Ticket).where(Ticket.user_id == user_id, Ticket.event_id == event_id)
    )


async def free_entry_for(session: AsyncSession, *, user_id: int, event_id: int) -> str | None:
    """"PUMPKIN RUSH #2" if this guest won free entry, else None."""
    ticket = await ticket_for(session, user_id=user_id, event_id=event_id)
    return ticket.code if ticket is not None and ticket.provider == TicketProvider.PRIZE else None
