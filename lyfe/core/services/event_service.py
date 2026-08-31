"""Event lookup."""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from lyfe.models import Event, EventStatus


async def get_next_event(session: AsyncSession) -> Event | None:
    """The event the bot currently points at: LIVE first, otherwise the nearest
    UPCOMING one."""
    now = datetime.now(timezone.utc)

    live = await session.execute(
        select(Event)
        .options(joinedload(Event.venue), joinedload(Event.city))
        .where(Event.status == EventStatus.LIVE)
        .order_by(Event.starts_at)
        .limit(1)
    )
    event = live.scalar_one_or_none()
    if event is not None:
        return event

    upcoming = await session.execute(
        select(Event)
        .options(joinedload(Event.venue), joinedload(Event.city))
        .where(Event.status == EventStatus.UPCOMING, Event.starts_at >= now)
        .order_by(Event.starts_at)
        .limit(1)
    )
    return upcoming.scalar_one_or_none()
