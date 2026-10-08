"""Pay PUMPKIN RUSH prizes for an event: top 3 get 30 / 20 / 10 LYFE POINTS.

Run once the night is over. Safe to run twice: each prize has its own
idempotency key, so nobody is paid again.

    python scripts/award_game.py                 # the current / latest event, plan only
    python scripts/award_game.py --apply
    python scripts/award_game.py --event-id 3 --apply --notify
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from lyfe.core.services import season_service  # noqa: E402
from lyfe.db import SessionFactory  # noqa: E402
from lyfe.models import Event  # noqa: E402


async def main(event_id: int | None, apply: bool, notify: bool) -> None:
    async with SessionFactory() as session:
        if event_id:
            event = await session.get(Event, event_id)
        else:
            event = await session.scalar(select(Event).order_by(Event.starts_at.desc()).limit(1))
        if event is None:
            print("No event.")
            return

        board = await season_service.leaderboard(session, event_id=event.id, limit=10)
        print(f"{event.title} — PUMPKIN RUSH")
        for place, row in enumerate(board, start=1):
            prize = season_service.PRIZES[place - 1] if place <= len(season_service.PRIZES) else 0
            print(f"  {place:>2}. LYFE #{row['lyfe_id']}  {row['name']:<24} {row['score']:>3}"
                  + (f"   +{prize}" if prize else ""))
        if not apply:
            print("Plan only. Run with --apply to pay.")
            return

        paid = await season_service.award_prizes(session, event=event)
        await session.commit()
        print(f"Paid {len(paid)} prizes.")

    if notify and paid:
        from lyfe.web.notifier import close, get_bot

        bot = get_bot()
        try:
            for user, place, prize in paid:
                try:
                    await bot.send_message(
                        user.tg_user_id,
                        f"🎃 PUMPKIN RUSH\n\n{place} место.\n+{prize} LYFE POINTS\n\nFEEL THE LYFE",
                    )
                except Exception as exc:  # noqa: BLE001
                    print(f"  push to LYFE #{user.lyfe_id} failed: {exc}")
        finally:
            await close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--event-id", type=int)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--notify", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.event_id, args.apply, args.notify))
