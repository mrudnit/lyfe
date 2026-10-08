"""Seasonal fun: the pumpkin hunt, PUMPKIN RUSH, and GoOut tickets.

PUMPKIN RUSH is scored by the server, not the phone. The server picks a seed,
derives every pumpkin from it (when it appears, where, for how long, what it
is worth) and hands the schedule to the page. The page reports which pumpkins
were tapped and when; the server recomputes the score from its own copy and
drops any tap that could not have happened. A modified page can still play
perfectly, but it cannot invent pumpkins or points.
"""
import random
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lyfe.core.services import points_service
from lyfe.models import Event, GameSession, PointsReason, PointTransaction, Ticket, TicketProvider, User

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
# Paid once the event is over, by scripts/award_game.py.
PRIZES = (30, 20, 10)
# Time a tap may arrive after the pumpkin vanished: finger and network lag.
TAP_GRACE = 0.25


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
    """Every piece of one round, derived from the seed alone."""
    rng = random.Random(seed)
    pieces: list[Piece] = []
    t, i = 0.6, 0
    while t < GAME_SECONDS - 0.4:
        progress = t / GAME_SECONDS
        # it gets faster: shorter gaps, shorter life
        ttl = round(1.45 - 0.6 * progress + rng.uniform(-0.1, 0.1), 3)
        roll = rng.random()
        if roll < 0.10:
            kind, value = "gold", 3
        elif roll < 0.24:
            kind, value = "ghost", -2
        else:
            kind, value = "pumpkin", 1
        pieces.append(
            Piece(
                id=i,
                at=round(t, 3),
                ttl=max(0.55, ttl),
                x=round(rng.uniform(0.12, 0.88), 3),
                y=round(rng.uniform(0.14, 0.86), 3),
                kind=kind,
                value=value,
            )
        )
        i += 1
        t += 0.78 - 0.4 * progress + rng.uniform(-0.12, 0.12)
    return pieces


def score_hits(seed: int, hits: list[dict]) -> int:
    by_id = {p.id: p for p in schedule(seed)}
    seen: set[int] = set()
    score = 0
    for hit in hits[:200]:
        try:
            piece = by_id[int(hit["id"])]
            t = float(hit["t"])
        except (KeyError, TypeError, ValueError):
            continue
        if piece.id in seen:
            continue
        if piece.at - 0.05 <= t <= piece.at + piece.ttl + TAP_GRACE:
            seen.add(piece.id)
            score += piece.value
    return max(0, score)


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


async def start_game(session: AsyncSession, *, user: User, event: Event) -> GameSession | None:
    # Serialise this person's attempts so two taps cannot open a third round.
    await session.execute(select(User.id).where(User.id == user.id).with_for_update())
    if await attempts_used(session, user_id=user.id, event_id=event.id) >= ATTEMPTS_PER_EVENT:
        return None
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


async def award_prizes(session: AsyncSession, *, event: Event) -> list[tuple[User, int, int]]:
    """Top places get points, once. Ties on score go to whoever was first."""
    paid = []
    for place, row in enumerate(await leaderboard(session, event_id=event.id, limit=len(PRIZES))):
        prize = PRIZES[place]
        tx = await points_service.award(
            session,
            user_id=row["user_id"],
            delta=prize,
            reason_code=PointsReason.GAME_PRIZE,
            idempotency_key=f"game_prize:{event.id}:{row['user_id']}",
            event_id=event.id,
            ref_type="game",
        )
        if tx is not None:
            paid.append((await session.get(User, row["user_id"]), place + 1, prize))
    return paid


# --------------------------------------------------------------------------
# Tickets
# --------------------------------------------------------------------------

_TICKET_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_/.:]{3,127}$")


async def ticket_for(session: AsyncSession, *, user_id: int, event_id: int) -> Ticket | None:
    return await session.scalar(
        select(Ticket).where(Ticket.user_id == user_id, Ticket.event_id == event_id)
    )


async def attach_ticket(session: AsyncSession, *, user: User, event: Event, code: str) -> str:
    """OK, FORMAT or TAKEN."""
    code = "".join((code or "").split())
    if not _TICKET_CODE.match(code):
        return "FORMAT"

    other = await session.scalar(
        select(Ticket).where(Ticket.provider == TicketProvider.GOOUT, Ticket.code == code)
    )
    if other is not None and other.user_id != user.id:
        return "TAKEN"

    ticket = await ticket_for(session, user_id=user.id, event_id=event.id)
    if ticket is None:
        ticket = Ticket(event_id=event.id, user_id=user.id, provider=TicketProvider.GOOUT, code=code)
        session.add(ticket)
    else:
        ticket.code = code
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return "TAKEN"
    return "OK"


async def detach_ticket(session: AsyncSession, *, user: User, event: Event) -> None:
    ticket = await ticket_for(session, user_id=user.id, event_id=event.id)
    if ticket is not None:
        await session.delete(ticket)

