"""Банда / «Взлом»: everyone in the top 2 gangs gets free entry to the party.

The game closes 24 h before the party starts (season_service.CLOSES_BEFORE).
Run this after that: each member of a winning gang gets a FREE ENTRY mark on
their LYFE PASS, and the door scanner shows it. Safe to run twice — nobody is
marked again. A gang with no loot wins nothing.

    python scripts/award_game.py                     # the upcoming party, plan only
    python scripts/award_game.py --apply --notify    # mark winners and message them in the bot
    python scripts/award_game.py --event-id 3 --apply
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lyfe.config import get_settings  # noqa: E402
from lyfe.core.services import event_service, gang_service, hack_service  # noqa: E402
from lyfe.db import SessionFactory  # noqa: E402
from lyfe.models import Event  # noqa: E402

settings = get_settings()


async def main(event_id: int | None, apply: bool, notify: bool, force: bool) -> None:
    won = []
    async with SessionFactory() as session:
        event = await session.get(Event, event_id) if event_id else await event_service.get_season_anchor(session)
        if event is None:
            print("No event.")
            return

        closes = hack_service.closes_at(event)
        board = await gang_service.ranking(session, event_id=event.id, limit=10)
        print(f"{event.title} — рейтинг банд (Взлом закрывается {closes:%d.%m %H:%M} UTC)" if closes else event.title)
        for row in board:
            win = row["place"] <= settings.gang_free_entry_places and row["loot"] > 0
            print(f"  {row['place']:>2}. {row['name']:<24} {row['size']} чел.  $ {row['loot']:>6}" + ("   FREE ENTRY" if win else ""))
        if not apply:
            print("Plan only. Run with --apply to mark the winners.")
            return
        if hack_service.is_open(event) and not force:
            print("The game is still open — the top can still change. Wait until it closes, or add --force.")
            return

        won = await gang_service.award_free_entries(session, event=event)
        await session.commit()
        print(f"Marked {len(won)} people.")

    if notify and won:
        from lyfe.web.notifier import close, get_bot

        bot = get_bot()
        try:
            for user, gang_name, place in won:
                try:
                    await bot.send_message(
                        user.tg_user_id,
                        f"Банда «{gang_name}»: {place} место во Взломе.\n\n"
                        f"Вход на {event.title} для всей банды бесплатный.\n"
                        f"Покажи LYFE PASS на входе.",
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
