"""Event administration.

The point of this module is that nobody should ever open psql to change a date
two hours before doors. Editing the schedule by hand at 8pm is how events get
broken in ways nobody notices until people are already queueing.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lyfe.models import AdminAction, City, Event, EventStatus, Venue


@dataclass
class EventForm:
    title: str
    starts_at_local: str          # "2026-09-22T21:00"
    status: str
    venue_id: int
    ticket_url: str | None = None
    request_hours_before: int = 24 * 14
    request_hours_after: int = 4
    checkin_hours_before: int = 2
    checkin_hours_after: int = 8


async def list_events(session: AsyncSession) -> list[Event]:
    rows = await session.execute(select(Event).order_by(Event.starts_at.desc()))
    return list(rows.scalars().unique())


async def list_venues(session: AsyncSession) -> list[Venue]:
    rows = await session.execute(select(Venue).order_by(Venue.name))
    return list(rows.scalars().unique())


def _tz_for(venue: Venue, city: City | None) -> ZoneInfo:
    try:
        return ZoneInfo(city.timezone if city else "Europe/Bratislava")
    except Exception:  # noqa: BLE001
        return ZoneInfo("Europe/Bratislava")


def local_value(moment: datetime | None, tz: ZoneInfo) -> str:
    """Format for an <input type="datetime-local">."""
    if moment is None:
        return ""
    return moment.astimezone(tz).strftime("%Y-%m-%dT%H:%M")


async def apply_form(
    session: AsyncSession, *, event: Event, form: EventForm, admin_id: int
) -> None:
    venue = await session.get(Venue, form.venue_id)
    city = await session.get(City, venue.city_id) if venue else None
    tz = _tz_for(venue, city)

    before = {
        "title": event.title,
        "status": event.status,
        "starts_at": event.starts_at.isoformat() if event.starts_at else None,
    }

    # The form speaks club time; the database always stores UTC.
    starts_local = datetime.fromisoformat(form.starts_at_local).replace(tzinfo=tz)
    starts_at = starts_local.astimezone(timezone.utc)

    event.title = form.title.strip()
    event.status = form.status
    event.venue_id = venue.id
    event.city_id = venue.city_id
    event.starts_at = starts_at
    event.ends_at = starts_at + timedelta(hours=max(form.checkin_hours_after, 6))
    event.ticket_url = (form.ticket_url or "").strip() or None

    event.requests_open_from = starts_at - timedelta(hours=form.request_hours_before)
    event.requests_open_until = starts_at + timedelta(hours=form.request_hours_after)
    event.checkin_open_from = starts_at - timedelta(hours=form.checkin_hours_before)
    event.checkin_open_until = starts_at + timedelta(hours=form.checkin_hours_after)

    session.add(
        AdminAction(
            admin_id=admin_id,
            action="EVENT_UPDATED",
            target_type="event",
            target_id=event.id,
            old_value=before,
            new_value={
                "title": event.title,
                "status": event.status,
                "starts_at": event.starts_at.isoformat(),
            },
        )
    )


async def create_event(
    session: AsyncSession, *, form: EventForm, admin_id: int
) -> Event:
    venue = await session.get(Venue, form.venue_id)
    slug_base = form.title.lower().replace(" ", "-")[:40] or "lyfeparty"
    slug = f"{slug_base}-{form.starts_at_local[:10]}"

    event = Event(
        slug=slug,
        title=form.title.strip(),
        city_id=venue.city_id,
        venue_id=venue.id,
        status=form.status,
        starts_at=datetime.now(timezone.utc),
    )
    session.add(event)
    await session.flush()
    await apply_form(session, event=event, form=form, admin_id=admin_id)
    return event


async def set_status(
    session: AsyncSession, *, event: Event, status: str, admin_id: int
) -> None:
    if status not in EventStatus.ALL:
        return
    old = event.status
    event.status = status
    session.add(
        AdminAction(
            admin_id=admin_id,
            action="EVENT_STATUS",
            target_type="event",
            target_id=event.id,
            old_value={"status": old},
            new_value={"status": status},
        )
    )
