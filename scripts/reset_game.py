"""PUMPKIN RUSH: wipe every round played for the upcoming party (test runs before launch).

Deletes the rounds (so attempts are back to 2 and the board is empty) and any
FREE ENTRY already handed out for that party. Points, the pumpkin hunt and
everything else stay as they are.

    python scripts/reset_game.py             # show what would be deleted
    python scripts/reset_game.py --apply
    python scripts/reset_game.py --event-id 3 --apply
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, func, select  # noqa: E402

from lyfe.core.services import event_service, season_service  # noqa: E402
from lyfe.db import SessionFactory  # noqa: E402
from lyfe.models import Event, GameSession, Ticket, TicketProvider  # noqa: E402


async def main(event_id: int | None, apply: bool) -> None:
    async with SessionFactory() as session:
        event = await session.get(Event, event_id) if event_id else await event_service.get_season_anchor(session)
        if event is None:
            print("No event.")
            return
        rounds = select(GameSession).where(GameSession.event_id == event.id, GameSession.kind == season_service.GAME_KIND)
        prizes = select(Ticket).where(Ticket.event_id == event.id, Ticket.provider == TicketProvider.PRIZE)
        n_rounds = await session.scalar(select(func.count()).select_from(rounds.subquery()))
        n_players = await session.scalar(select(func.count(func.distinct(GameSession.user_id))).where(
            GameSession.event_id == event.id, GameSession.kind == season_service.GAME_KIND))
        n_prizes = await session.scalar(select(func.count()).select_from(prizes.subquery()))
        print(f"{event.title}: {n_rounds} rounds by {n_players} players, {n_prizes} free entries")
        if not apply:
            print("Plan only. Run with --apply to delete.")
            return
        await session.execute(delete(GameSession).where(
            GameSession.event_id == event.id, GameSession.kind == season_service.GAME_KIND))
        await session.execute(delete(Ticket).where(Ticket.event_id == event.id, Ticket.provider == TicketProvider.PRIZE))
        await session.commit()
        print("Deleted. Everyone has 2 attempts again, the board is empty.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--event-id", type=int)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.event_id, args.apply))
