"""Give every registered guest the same number of LYFE POINTS.

Made for the night the door scanner could not keep up: nobody should lose their
attendance points because the queue moved faster than the phone.

Safe to run twice. Each grant is written with the key
"gift:<campaign>:<user_id>", so a second run with the same campaign pays nobody.
Use a new campaign name for a genuinely new gift.

    # see who would get what, write nothing
    python scripts/grant_points.py --dry-run

    # pay out
    python scripts/grant_points.py

    # pay out and tell everyone in Telegram
    python scripts/grant_points.py --notify

On Railway, from the bot service:
    railway run python scripts/grant_points.py --dry-run
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from lyfe.core.services import points_service  # noqa: E402
from lyfe.db import SessionFactory  # noqa: E402
from lyfe.i18n import t  # noqa: E402
from lyfe.models import PointsReason, PointTransaction, User  # noqa: E402

DEFAULT_CAMPAIGN = "back2lyfe-2026-09"
SEND_INTERVAL_SECONDS = 0.05


async def main(amount: int, campaign: str, dry_run: bool, notify: bool) -> None:
    async with SessionFactory() as session:
        users = list(
            (
                await session.execute(
                    select(User).where(User.deleted_at.is_(None)).order_by(User.id)
                )
            ).scalars()
        )
        already = set(
            (
                await session.execute(
                    select(PointTransaction.user_id).where(
                        PointTransaction.idempotency_key.like(f"gift:{campaign}:%")
                    )
                )
            ).scalars()
        )

        to_pay = [user for user in users if user.id not in already]
        print(f"Registered: {len(users)} · already paid: {len(already)} · to pay: {len(to_pay)}")
        print(f"Campaign: {campaign} · +{amount} each")

        if dry_run:
            for user in to_pay[:20]:
                print(f"  LYFE #{user.lyfe_id}  {user.name}")
            if len(to_pay) > 20:
                print(f"  … and {len(to_pay) - 20} more")
            print("Dry run, nothing written.")
            return

        paid = []
        for user in to_pay:
            tx = await points_service.award(
                session,
                user_id=user.id,
                delta=amount,
                reason_code=PointsReason.GIFT,
                idempotency_key=f"gift:{campaign}:{user.id}",
                ref_type="gift",
            )
            if tx is not None:
                paid.append(user)
        await session.commit()
        print(f"Paid {len(paid)} guests.")

    if notify and paid:
        await _notify(paid, amount)


async def _notify(users: list[User], amount: int) -> None:
    from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

    from lyfe.web.notifier import close, get_bot

    bot = get_bot()
    sent = 0
    try:
        for user in users:
            if user.is_bot_blocked:
                continue
            text = t("gift_points", user.language, points=amount)
            try:
                await bot.send_message(user.tg_user_id, text)
                sent += 1
            except TelegramRetryAfter as exc:
                await asyncio.sleep(exc.retry_after + 1)
            except TelegramForbiddenError:
                pass
            except Exception as exc:  # noqa: BLE001
                print(f"  push to LYFE #{user.lyfe_id} failed: {exc}")
            await asyncio.sleep(SEND_INTERVAL_SECONDS)
    finally:
        await close()
    print(f"Notified {sent} guests.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--amount", type=int, default=10)
    parser.add_argument("--campaign", default=DEFAULT_CAMPAIGN)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--notify", action="store_true", help="send a Telegram message")
    args = parser.parse_args()
    asyncio.run(main(args.amount, args.campaign, args.dry_run, args.notify))
