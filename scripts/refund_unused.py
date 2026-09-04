"""Return points for rewards nobody collected.

Run after an event is over:
    PYTHONPATH=. .venv/bin/python scripts/refund_unused.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from lyfe.core.services import reward_service  # noqa: E402
from lyfe.db import SessionFactory  # noqa: E402
from lyfe.models import Event, EventStatus  # noqa: E402


async def main() -> None:
    async with SessionFactory() as session:
        events = await session.execute(
            select(Event).where(Event.status == EventStatus.ENDED)
        )
        total = 0
        for event in events.scalars():
            count = await reward_service.refund_unused(session, event=event)
            if count:
                print(f"{event.title}: refunded {count}")
            total += count
        await session.commit()
        print(f"Total refunded: {total}")


if __name__ == "__main__":
    asyncio.run(main())
