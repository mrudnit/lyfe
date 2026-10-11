"""PUMPKIN RUSH: the top 5 get free entry to the party.

The board freezes 24 h before the party starts (season_service.CLOSES_BEFORE).
Run this after that: each winner gets a FREE ENTRY mark on their LYFE PASS,
and the door scanner shows it. Safe to run twice — nobody is marked again.

    python scripts/award_game.py                     # the upcoming party, plan only
    python scripts/award_game.py --apply --notify    # mark winners and message them in the bot
    python scripts/award_game.py --event-id 3 --apply
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lyfe.core.services import event_service, season_service  # noqa: E402
from lyfe.db import SessionFactory  # noqa: E402
from lyfe.models import Event  # noqa: E402


async def main(event_id: int | None, apply: bool, notify: bool, force: bool) -> None:
    async with SessionFactory() as session:
        event = await session.get(Event, event_id) if event_id else await event_service.get_season_anchor(session)
        if event is None:
            print("No event.")
            return

        closes = season_service.closes_at(event)
        board = await season_service.leaderboard(session, event_id=event.id, limit=10)
        print(f"{event.title} — PUMPKIN RUSH (board closes {closes:%d.%m %H:%M} UTC)" if closes else event.title)
        for place, row in enumerate(board, start=1):
            win = place <= season_service.FREE_ENTRY_PLACES
            print(f"  {place:>2}. LYFE #{row['lyfe_id']}  {row['name']:<24} {row['score']:>4}" + ("   FREE ENTRY" if win else ""))
        if not apply:
            print("Plan only. Run with --apply to mark the winners.")
            return
        if season_service.is_open(event) and not force:
            print("The game is still open — the top 5 can still change. Wait until it closes, or add --force.")
            return

        won = await season_service.award_free_entries(session, event=event)
        await session.commit()
        print(f"Marked {len(won)} winners.")

    if notify and won:
        from lyfe.web.notifier import close, get_bot

        bot = get_bot()
        try:
            for user, place in won:
                try:
                    await bot.send_message(
                        user.tg_user_id,
                        f"🎃 PUMPKIN RUSH — {place} место\n\n"
                        f"Ты в топ-5: вход на {event.title} бесплатный.\n"
                        f"Просто покажи LYFE PASS на входе.\n\nFEEL THE LYFE",
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
    parser.add_argument("--force", action="store_true", help="mark winners even though the game is still open")
    args = parser.parse_args()
    asyncio.run(main(args.event_id, args.apply, args.notify, args.force))
