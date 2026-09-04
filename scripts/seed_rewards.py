"""Create the reward catalogue.

Only the guaranteed play is switched on. Everything else is created inactive
on purpose: a reward that nobody is free to hand over does not work, no matter
how good it looks in the bot. Turn them on when there is a person at the door
with nothing else to do:

    update rewards set is_active = true where code = 'SKIP_QUEUE';
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from lyfe.config import get_settings  # noqa: E402
from lyfe.db import SessionFactory  # noqa: E402
from lyfe.models import Reward, RewardKind  # noqa: E402

settings = get_settings()

CATALOGUE = [
    {
        "code": "PRIORITY_TRACK",
        "name": "🎯 Гарантия трека",
        "description": "Твой трек прозвучит этой ночью. Без «если».",
        "kind": RewardKind.PRIORITY_TRACK,
        "cost_points": settings.cost_priority_track,
        "per_user_limit": 1,
        "is_active": True,        # costs nothing to fulfil, needs nobody
        "position": 10,
    },
    {
        "code": "SKIP_QUEUE",
        "name": "🚪 Без очереди",
        "description": "Проходишь мимо очереди.",
        "kind": RewardKind.DOOR,
        "cost_points": 30,
        "per_user_limit": 1,
        "is_active": False,
        "position": 20,
    },
    {
        "code": "WELCOME_DRINK",
        "name": "🍹 Welcome drink",
        "description": "Первый напиток за счёт LYFE.",
        "kind": RewardKind.DOOR,
        "cost_points": 50,
        "per_user_limit": 1,
        "is_active": False,
        "position": 30,
    },
    {
        "code": "PLUS_ONE",
        "name": "👥 Друг бесплатно",
        "description": "Приводишь друга без билета.",
        "kind": RewardKind.DOOR,
        "cost_points": 100,
        "per_user_limit": 1,
        "is_active": False,
        "position": 40,
    },
    {
        "code": "FREE_ENTRY",
        "name": "🎟 Свободный вход",
        "description": "Эта ночь для тебя бесплатна.",
        "kind": RewardKind.DOOR,
        "cost_points": 150,
        "per_user_limit": 1,
        "is_active": False,
        "position": 50,
    },
]


async def main() -> None:
    async with SessionFactory() as session:
        for item in CATALOGUE:
            reward = await session.scalar(select(Reward).where(Reward.code == item["code"]))
            if reward is None:
                session.add(Reward(**item))
                print(f"created  {item['code']:<16} {item['cost_points']:>4} pts "
                      f"{'ON' if item['is_active'] else 'off'}")
            else:
                print(f"exists   {item['code']:<16} {reward.cost_points:>4} pts "
                      f"{'ON' if reward.is_active else 'off'}")
        await session.commit()


if __name__ == "__main__":
    asyncio.run(main())
