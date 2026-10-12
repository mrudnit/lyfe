"""Create (or update) a party the same way the admin form does.

Defaults are the Halloween party: Lyfeparty: Halloween Edition, Fri 30.10.2026
22:00, Luna Club Nitra, tickets on GoOut. Run again to update it — the party
is found by its date, never duplicated.

    python scripts/create_event.py                    # show what would be created
    python scripts/create_event.py --apply
    python scripts/create_event.py --title "Halloween Edition" --start 2026-10-30T22:00 \
        --venue "Luna" --tickets https://goout.net/... --requests-days 20 --apply
"""
import argparse
import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select  # noqa: E402

from lyfe.core.services import admin_event_service  # noqa: E402
from lyfe.db import SessionFactory  # noqa: E402
from lyfe.models import AdminRole, AdminUser, City, Event, EventStatus, Venue  # noqa: E402

DEFAULTS = {
    "title": "Halloween Edition",
    "start": "2026-10-30T22:00",
    "venue": "Luna",
    "tickets": "https://goout.net/sk/lyfeparty-halloween-edition/szwcpny/",
    # track requests open this many days before the start (admin default is 14);
    # 20 lets everyone test and request now, before the announcement
    "requests_days": 20,
}


async def main(a: argparse.Namespace) -> None:
    async with SessionFactory() as session:
        venues = list((await session.execute(select(Venue).order_by(Venue.name))).scalars())
        venue = next((v for v in venues if a.venue.lower() in v.name.lower()), None)
        if venue is None:
            print(f"No venue matching {a.venue!r}. Venues: " + ", ".join(v.name for v in venues))
            return
        admin = await session.scalar(
            select(AdminUser).where(AdminUser.role == AdminRole.SUPER_ADMIN).order_by(AdminUser.id).limit(1)
        ) or await session.scalar(select(AdminUser).order_by(AdminUser.id).limit(1))
        if admin is None:
            print("No admin user to sign the change.")
            return
        city = await session.get(City, venue.city_id)
        tz = admin_event_service._tz_for(venue, city)
        start_local = datetime.fromisoformat(a.start).replace(tzinfo=tz)

        # the same party = the same calendar day in club time
        same_day = await session.scalar(
            select(Event).where(func.date(func.timezone(tz.key, Event.starts_at)) == start_local.date())
        )
        form = admin_event_service.EventForm(
            title=a.title,
            starts_at_local=a.start,
            status=EventStatus.UPCOMING,
            venue_id=venue.id,
            ticket_url=a.tickets,
            request_hours_before=a.requests_days * 24,
        )
        verb = "Update" if same_day else "Create"
        opens = start_local - timedelta(days=a.requests_days)
        print(f"{verb}: {a.title} · {start_local:%a %d.%m.%Y %H:%M} · {venue.name}\n"
              f"  track requests from {opens:%d.%m %H:%M} · game board closes {start_local - timedelta(hours=24):%d.%m %H:%M}\n"
              f"  tickets: {a.tickets}")
        if not a.apply:
            print("Plan only. Run with --apply.")
            return
        if same_day:
            await admin_event_service.apply_form(session, event=same_day, form=form, admin_id=admin.id)
            event = same_day
        else:
            event = await admin_event_service.create_event(session, form=form, admin_id=admin.id)
        await session.commit()
        print(f"Done: event #{event.id} ({event.slug}), status {event.status}.")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--title", default=DEFAULTS["title"])
    p.add_argument("--start", default=DEFAULTS["start"], help="club time, e.g. 2026-10-30T22:00")
    p.add_argument("--venue", default=DEFAULTS["venue"], help="part of the venue name")
    p.add_argument("--tickets", default=DEFAULTS["tickets"])
    p.add_argument("--requests-days", type=int, default=DEFAULTS["requests_days"])
    p.add_argument("--apply", action="store_true")
    asyncio.run(main(p.parse_args()))
