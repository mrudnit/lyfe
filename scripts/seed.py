"""Seed one city, one venue and one event so the bot has something to show.

Run once:  docker compose run --rm bot python scripts/seed.py
Edit the values below to match your real event before running.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from lyfe.db import SessionFactory
from lyfe.models import City, Event, EventStatus, Venue

CITY_NAME = "Nitra"
VENUE_NAME = "Luna Club"
EVENT_SLUG = "back-to-lyfe-2026-09-22"
EVENT_TITLE = "Back to LYFE"
LOCAL_TZ = ZoneInfo("Europe/Bratislava")
# Local club time, not UTC. 22.09 at 21:00 in Nitra.
EVENT_STARTS_AT = datetime(2026, 9, 22, 21, 0, tzinfo=LOCAL_TZ)
TICKET_URL = None  # put your GoOut / ticket link here


async def main() -> None:
    async with SessionFactory() as session:
        city = await session.scalar(select(City).where(City.name == CITY_NAME))
        if city is None:
            city = City(name=CITY_NAME, country_code="SK", timezone="Europe/Bratislava")
            session.add(city)
            await session.flush()

        venue = await session.scalar(select(Venue).where(Venue.name == VENUE_NAME))
        if venue is None:
            venue = Venue(city_id=city.id, name=VENUE_NAME)
            session.add(venue)
            await session.flush()

        event = await session.scalar(select(Event).where(Event.slug == EVENT_SLUG))
        if event is None:
            event = Event(
                slug=EVENT_SLUG,
                title=EVENT_TITLE,
                city_id=city.id,
                venue_id=venue.id,
                status=EventStatus.UPCOMING,
                starts_at=EVENT_STARTS_AT,
                ends_at=EVENT_STARTS_AT + timedelta(hours=6),
                requests_open_from=datetime.now(timezone.utc),
                requests_open_until=EVENT_STARTS_AT + timedelta(hours=4),
                checkin_open_from=EVENT_STARTS_AT - timedelta(hours=2),
                checkin_open_until=EVENT_STARTS_AT + timedelta(hours=6),
                ticket_url=TICKET_URL,
            )
            session.add(event)

        await session.commit()
        print(f"Seeded: {CITY_NAME} / {VENUE_NAME} / {EVENT_TITLE}")


if __name__ == "__main__":
    asyncio.run(main())
