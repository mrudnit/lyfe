"""User registration and lookup.

All business logic lives in services like this one. The bot handlers and the
future Mini App API are thin adapters that call in here. This is what makes it
possible to add the Mini App in Phase 2 without rewriting anything.
"""
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lyfe.core.lyfe_id import next_lyfe_id
from lyfe.i18n import resolve_language
from lyfe.models import PointTransaction, User


async def get_by_telegram_id(session: AsyncSession, tg_user_id: int) -> User | None:
    result = await session.execute(select(User).where(User.tg_user_id == tg_user_id))
    return result.scalar_one_or_none()


async def get_or_create(
    session: AsyncSession,
    *,
    tg_user_id: int,
    username: str | None,
    first_name: str | None,
    language_code: str | None,
) -> tuple[User, bool]:
    """Returns (user, created). Registration is silent — we never ask for a name
    before the user has received any value."""
    user = await get_by_telegram_id(session, tg_user_id)
    now = datetime.now(timezone.utc)

    if user is not None:
        # Keep Telegram fields fresh; people change usernames.
        user.tg_username = username
        user.first_name = first_name or user.first_name
        user.last_seen_at = now
        user.is_bot_blocked = False
        return user, False

    user = User(
        tg_user_id=tg_user_id,
        tg_username=username,
        first_name=first_name,
        lyfe_id=await next_lyfe_id(session),
        language=resolve_language(language_code),
        last_seen_at=now,
    )
    try:
        # A brand-new guest often arrives twice at once (bot + Mini App).
        async with session.begin_nested():
            session.add(user)
            await session.flush()
    except IntegrityError:
        existing = await get_by_telegram_id(session, tg_user_id)
        if existing is None:
            raise
        return existing, False
    return user, True


async def lock_user(session: AsyncSession, user_id: int) -> None:
    """Make everything one guest does with points run one at a time.

    Without it, two taps that arrive together both pass "is there room left?"
    before either has written anything. The lock is a row lock on the guest,
    held until the transaction ends."""
    await session.execute(select(User.id).where(User.id == user_id).with_for_update())


async def get_points_balance(session: AsyncSession, user_id: int) -> int:
    """Balance is always derived from the ledger. Never stored as a number."""
    result = await session.execute(
        select(func.coalesce(func.sum(PointTransaction.delta), 0)).where(
            PointTransaction.user_id == user_id
        )
    )
    return int(result.scalar_one())


async def set_language(session: AsyncSession, user: User, language: str) -> None:
    user.language = language
