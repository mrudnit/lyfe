"""Банда: create, join by invite code, leave, and the gang rating.

Rules (docs/lyfe-gta-style.md):
  * up to settings.max_gang_size people (5); roles are handed out in order:
    лидер, водитель, хакер, громила, наводчик;
  * one gang per person per party;
  * after settings.gang_changes_until nobody creates, joins or leaves;
  * a gang's loot is the sum of its members' best «Взлом» runs (hack_service);
  * the top settings.gang_free_entry_places gangs get in free.

Every change takes the person's row lock first, then the gang's, always in
that order, so two taps (or two friends opening the same link) cannot squeeze
a sixth member in or put one person in two gangs. The unique constraints on
gang_members are the last line if anything races anyway.
"""
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lyfe.config import get_settings
from lyfe.models import Event, Gang, GangLeave, GangMember, GangRole, Ticket, TicketProvider, User

settings = get_settings()

NAME_MIN, NAME_MAX = 2, 24
# letters of any alphabet, digits, spaces and a few joiners; no links, no @handles
_NAME_OK = re.compile(r"^[\w\s\-'’.!]+$", re.UNICODE)
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O, 1/I


class GangResult:
    CREATED = "CREATED"
    JOINED = "JOINED"
    LEFT = "LEFT"
    ALREADY_IN_GANG = "ALREADY_IN_GANG"   # in another gang already
    ALREADY_HERE = "ALREADY_HERE"         # opened their own gang's link
    NOT_IN_GANG = "NOT_IN_GANG"
    FULL = "FULL"
    NOT_FOUND = "NOT_FOUND"
    LOCKED = "LOCKED"                     # past gang_changes_until
    NO_EVENT = "NO_EVENT"
    BAD_NAME = "BAD_NAME"
    NAME_TAKEN = "NAME_TAKEN"
    NOT_LEADER = "NOT_LEADER"             # only the leader opens or closes the gang
    NONE_OPEN = "NONE_OPEN"               # «Найти банду»: no open gang has room
    MOVE_USED = "MOVE_USED"               # already changed gang once this party
    OPENED = "OPENED"
    CLOSED = "CLOSED"


@dataclass
class GangOutcome:
    status: str
    gang: Gang | None = None


def changes_until() -> datetime:
    return datetime.fromisoformat(settings.gang_changes_until)


def is_locked(now: datetime | None = None) -> bool:
    return (now or datetime.now(timezone.utc)) >= changes_until()


def clean_name(raw: str) -> str | None:
    name = " ".join((raw or "").split())
    if not (NAME_MIN <= len(name) <= NAME_MAX) or not _NAME_OK.match(name):
        return None
    if re.search(r"https?:|www\.|\.(com|ru|sk|ua|net|org)\b|t\.me", name, re.IGNORECASE):
        return None
    return name


def _key(name: str) -> str:
    return name.casefold()


def _new_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))


def invite_link(gang: Gang) -> str:
    """t.me/<bot>?start=gang_<code>: the bot answers with a button that opens
    the app on this gang. Works without a Main Mini App set in BotFather,
    unlike ?startapp=, which then only opens the chat."""
    return f"https://t.me/{settings.bot_username}?start=gang_{gang.invite_code}"


async def membership(session: AsyncSession, *, user_id: int, event_id: int) -> GangMember | None:
    return await session.scalar(
        select(GangMember).where(GangMember.user_id == user_id, GangMember.event_id == event_id)
    )


async def members(session: AsyncSession, *, gang_id: int) -> list[tuple[GangMember, User]]:
    rows = await session.execute(
        select(GangMember, User)
        .join(User, User.id == GangMember.user_id)
        .where(GangMember.gang_id == gang_id)
        .order_by(GangMember.joined_at.asc(), GangMember.id.asc())
    )
    return list(rows.all())


async def _lock_user(session: AsyncSession, user_id: int) -> None:
    from lyfe.core.services import user_service

    await user_service.lock_user(session, user_id)


async def create_gang(session: AsyncSession, *, user: User, event: Event | None, name: str) -> GangOutcome:
    if event is None:
        return GangOutcome(GangResult.NO_EVENT)
    if is_locked():
        return GangOutcome(GangResult.LOCKED)
    clean = clean_name(name)
    if clean is None:
        return GangOutcome(GangResult.BAD_NAME)
    await _lock_user(session, user.id)
    if await membership(session, user_id=user.id, event_id=event.id) is not None:
        return GangOutcome(GangResult.ALREADY_IN_GANG)
    taken = await session.scalar(
        select(Gang.id).where(Gang.event_id == event.id, Gang.name_key == _key(clean))
    )
    if taken is not None:
        return GangOutcome(GangResult.NAME_TAKEN)

    now = datetime.now(timezone.utc)
    try:
        async with session.begin_nested():
            gang = Gang(event_id=event.id, name=clean, name_key=_key(clean), invite_code=_new_code())
            session.add(gang)
            await session.flush()
            session.add(GangMember(gang_id=gang.id, event_id=event.id, user_id=user.id,
                                   role=GangRole.LEADER, joined_at=now))
            await session.flush()
    except IntegrityError:
        # a gang of that name was made a moment ago, or this person joined one in parallel
        if await membership(session, user_id=user.id, event_id=event.id) is not None:
            return GangOutcome(GangResult.ALREADY_IN_GANG)
        return GangOutcome(GangResult.NAME_TAKEN)
    return GangOutcome(GangResult.CREATED, gang)


async def join_gang(session: AsyncSession, *, user: User, code: str = "", gang_id: int | None = None) -> GangOutcome:
    """Join by invite code, or by id when the gang is open to anyone."""
    if gang_id is not None:
        gang = await session.get(Gang, gang_id)
        if gang is None or not gang.is_public:
            return GangOutcome(GangResult.NOT_FOUND)
    else:
        code = (code or "").strip().upper().removeprefix("GANG_")
        if not code or len(code) > 16:
            return GangOutcome(GangResult.NOT_FOUND)
        gang = await session.scalar(select(Gang).where(Gang.invite_code == code))
        if gang is None:
            return GangOutcome(GangResult.NOT_FOUND)
    if is_locked():
        return GangOutcome(GangResult.LOCKED, gang)

    await _lock_user(session, user.id)
    mine = await membership(session, user_id=user.id, event_id=gang.event_id)
    if mine is not None:
        return GangOutcome(GangResult.ALREADY_HERE if mine.gang_id == gang.id else GangResult.ALREADY_IN_GANG, gang)

    # the gang row lock serialises everyone joining this gang
    await session.execute(select(Gang.id).where(Gang.id == gang.id).with_for_update())
    taken = set(
        (await session.execute(select(GangMember.role).where(GangMember.gang_id == gang.id))).scalars()
    )
    free = [r for r in GangRole.ORDER[: settings.max_gang_size] if r not in taken]
    if len(taken) >= settings.max_gang_size or not free:
        return GangOutcome(GangResult.FULL, gang)
    try:
        async with session.begin_nested():
            session.add(GangMember(gang_id=gang.id, event_id=gang.event_id, user_id=user.id,
                                   role=free[0], joined_at=datetime.now(timezone.utc)))
            await session.flush()
    except IntegrityError:
        return GangOutcome(GangResult.ALREADY_IN_GANG, gang)
    return GangOutcome(GangResult.JOINED, gang)


async def moves_used(session: AsyncSession, *, user_id: int, event_id: int) -> int:
    return int(await session.scalar(
        select(func.count(GangLeave.id)).where(GangLeave.user_id == user_id, GangLeave.event_id == event_id)
    ) or 0)


async def leave_gang(session: AsyncSession, *, user: User, event: Event | None) -> GangOutcome:
    if event is None:
        return GangOutcome(GangResult.NO_EVENT)
    if is_locked():
        return GangOutcome(GangResult.LOCKED)
    await _lock_user(session, user.id)
    mine = await membership(session, user_id=user.id, event_id=event.id)
    if mine is None:
        return GangOutcome(GangResult.NOT_IN_GANG)
    if await moves_used(session, user_id=user.id, event_id=event.id) >= settings.gang_moves_max:
        return GangOutcome(GangResult.MOVE_USED)
    gang = await session.get(Gang, mine.gang_id, with_for_update=True)
    session.add(GangLeave(event_id=event.id, user_id=user.id, gang_name=gang.name))
    was_leader = mine.role == GangRole.LEADER
    await session.delete(mine)
    await session.flush()
    rest = await members(session, gang_id=gang.id)
    if not rest:
        await session.delete(gang)
        await session.flush()
        return GangOutcome(GangResult.LEFT)
    if was_leader:
        # the one who joined first after the leader takes over; their old role frees up
        rest[0][0].role = GangRole.LEADER
        await session.flush()
    return GangOutcome(GangResult.LEFT, gang)


async def open_gangs(session: AsyncSession, *, event_id: int, limit: int = 8) -> list[dict]:
    """Open gangs with room, fullest first: a stranger finishes a crew before starting a new one."""
    size = func.count(GangMember.id)
    rows = (await session.execute(
        select(Gang.id, Gang.name, size.label("size"))
        .join(GangMember, GangMember.gang_id == Gang.id)
        .where(Gang.event_id == event_id, Gang.is_public.is_(True))
        .group_by(Gang.id)
        .having(size < settings.max_gang_size)
        .order_by(size.desc(), Gang.created_at.asc())
        .limit(limit)
    )).all()
    return [{"id": r.id, "name": r.name, "size": int(r.size)} for r in rows]


async def find_gang(session: AsyncSession, *, user: User, event: Event | None) -> GangOutcome:
    """«Найти банду»: put this person in the fullest open gang that still has room."""
    if event is None:
        return GangOutcome(GangResult.NO_EVENT)
    if is_locked():
        return GangOutcome(GangResult.LOCKED)
    if await membership(session, user_id=user.id, event_id=event.id) is not None:
        return GangOutcome(GangResult.ALREADY_IN_GANG)
    for row in await open_gangs(session, event_id=event.id, limit=20):
        out = await join_gang(session, user=user, gang_id=row["id"])
        if out.status != GangResult.FULL:      # filled up a moment ago: try the next one
            return out
    return GangOutcome(GangResult.NONE_OPEN)


async def set_public(session: AsyncSession, *, user: User, event: Event | None, public: bool) -> GangOutcome:
    if event is None:
        return GangOutcome(GangResult.NO_EVENT)
    mine = await membership(session, user_id=user.id, event_id=event.id)
    if mine is None:
        return GangOutcome(GangResult.NOT_IN_GANG)
    if mine.role != GangRole.LEADER:
        return GangOutcome(GangResult.NOT_LEADER)
    gang = await session.get(Gang, mine.gang_id, with_for_update=True)
    gang.is_public = bool(public)
    await session.flush()
    return GangOutcome(GangResult.OPENED if gang.is_public else GangResult.CLOSED, gang)


async def member_names(session: AsyncSession, *, gang_ids: list[int]) -> dict[int, list[str]]:
    if not gang_ids:
        return {}
    rows = await session.execute(
        select(GangMember.gang_id, User)
        .join(User, User.id == GangMember.user_id)
        .where(GangMember.gang_id.in_(gang_ids))
        .order_by(GangMember.joined_at.asc(), GangMember.id.asc())
    )
    out: dict[int, list[str]] = {}
    for gid, person in rows.all():
        out.setdefault(gid, []).append(person.name or "?")
    return out


async def ranking(session: AsyncSession, *, event_id: int, limit: int | None = 10) -> list[dict]:
    """Gangs by loot (sum of members' best «Взлом» runs). Equal loot: the gang
    that got there first wins, then the older gang."""
    from lyfe.core.services import hack_service

    best = hack_service.best_runs_subquery(event_id)
    loot = func.coalesce(func.sum(best.c.score), 0)
    reached = func.max(best.c.reached_at)
    q = (
        select(Gang.id, Gang.name, Gang.created_at, func.count(GangMember.id).label("size"), loot.label("loot"))
        .join(GangMember, GangMember.gang_id == Gang.id)
        .outerjoin(best, (best.c.user_id == GangMember.user_id) & (best.c.gang_id == GangMember.gang_id))
        .where(Gang.event_id == event_id)
        .group_by(Gang.id)
        .order_by(loot.desc(), reached.asc().nulls_last(), Gang.created_at.asc(), Gang.id.asc())
    )
    if limit:
        q = q.limit(limit)
    rows = (await session.execute(q)).all()
    return [
        {"id": r.id, "name": r.name, "size": int(r.size), "loot": int(r.loot), "place": i}
        for i, r in enumerate(rows, start=1)
    ]


async def gang_count(session: AsyncSession, *, event_id: int) -> int:
    return int(await session.scalar(select(func.count(Gang.id)).where(Gang.event_id == event_id)) or 0)


async def award_free_entries(session: AsyncSession, *, event: Event) -> list[tuple[User, str, int]]:
    """Everyone in the top gangs gets free entry, once: a PRIZE ticket on their
    LYFE PASS for this event. A gang with no loot wins nothing."""
    from lyfe.core.services import season_service

    won = []
    for row in await ranking(session, event_id=event.id, limit=settings.gang_free_entry_places):
        if row["loot"] <= 0:
            continue
        for member, user in await members(session, gang_id=row["id"]):
            # ticket codes are unique per provider: the person and the party make it theirs
            code = f"Банда «{row['name']}» #{row['place']} · LYFE {user.lyfe_id}-{event.id}"[:128]
            ticket = await season_service.ticket_for(session, user_id=user.id, event_id=event.id)
            if ticket is not None and ticket.provider == TicketProvider.PRIZE:
                continue
            if ticket is None:
                session.add(Ticket(event_id=event.id, user_id=user.id, provider=TicketProvider.PRIZE, code=code))
            else:                      # an old GoOut code on file — the prize replaces it
                ticket.provider, ticket.code = TicketProvider.PRIZE, code
            await session.flush()
            won.append((user, row["name"], row["place"]))
    return won
