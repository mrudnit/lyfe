"""Sending "YOUR TRACK IS PLAYING NOW".

Two deliberate choices:

1. A 15 second delay. It gives the operator a window to undo a misclick, and it
   means the push lands while the track is actually playing rather than a beat
   before the mix comes in.

2. Paced sending. Telegram caps bulk delivery at roughly 30 messages a second;
   going faster gets the bot throttled exactly when it matters most.
"""
import asyncio
import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from sqlalchemy import select

from lyfe.config import get_settings
from lyfe.core.services import dj_service
from lyfe.db import SessionFactory
from lyfe.i18n import t
from lyfe.models import EventTrack, TrackStatus, User

logger = logging.getLogger(__name__)

NOTIFY_DELAY_SECONDS = 15
SEND_INTERVAL_SECONDS = 0.05  # ~20 messages per second

_bot: Bot | None = None
_pending: dict[int, asyncio.Task] = {}


def get_bot() -> Bot:
    global _bot
    if _bot is None:
        _bot = Bot(
            token=get_settings().bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
    return _bot


async def close() -> None:
    global _bot
    for task in list(_pending.values()):
        task.cancel()
    _pending.clear()
    if _bot is not None:
        await _bot.session.close()
        _bot = None


def schedule_played_notification(event_track_id: int, tg_user_ids: list[int]) -> None:
    cancel_pending(event_track_id)
    if not tg_user_ids:
        return
    _pending[event_track_id] = asyncio.create_task(
        _run(event_track_id, tg_user_ids), name=f"notify:{event_track_id}"
    )


def cancel_pending(event_track_id: int) -> bool:
    task = _pending.pop(event_track_id, None)
    if task is not None and not task.done():
        task.cancel()
        return True
    return False


async def _run(event_track_id: int, tg_user_ids: list[int]) -> None:
    try:
        await asyncio.sleep(NOTIFY_DELAY_SECONDS)
    except asyncio.CancelledError:
        logger.info("Notification for %s cancelled by undo", event_track_id)
        return

    bot = get_bot()

    async with SessionFactory() as session:
        # The operator may have pressed undo during the delay.
        event_track = await session.get(EventTrack, event_track_id)
        if event_track is None or event_track.status != TrackStatus.PLAYED:
            logger.info("Notification for %s skipped, no longer PLAYED", event_track_id)
            return

        track = event_track.track
        rows = await session.execute(
            select(User).where(User.tg_user_id.in_(tg_user_ids))
        )
        users = list(rows.scalars())

        sent = 0
        for user in users:
            text = t("track_played", user.language, track=track.display)
            try:
                await bot.send_message(user.tg_user_id, text)
                sent += 1
            except TelegramRetryAfter as exc:
                await asyncio.sleep(exc.retry_after + 1)
                try:
                    await bot.send_message(user.tg_user_id, text)
                    sent += 1
                except Exception:  # noqa: BLE001
                    pass
            except TelegramForbiddenError:
                user.is_bot_blocked = True
            except Exception as exc:  # noqa: BLE001
                logger.warning("Push to %s failed: %s", user.tg_user_id, exc)

            await asyncio.sleep(SEND_INTERVAL_SECONDS)

        await dj_service.mark_notified(session, event_track_id=event_track_id)
        await session.commit()

    logger.info("PLAYED push for %s delivered to %s people", event_track_id, sent)
    _pending.pop(event_track_id, None)


def schedule_checkin_notification(tg_user_id: int, language: str, points: int) -> None:
    """Confirmation that the scan worked. Sent immediately — the guest is
    standing at the door waiting to know it went through."""
    asyncio.create_task(_send_checkin(tg_user_id, language, points))


async def _send_checkin(tg_user_id: int, language: str, points: int) -> None:
    try:
        await get_bot().send_message(tg_user_id, t("checked_in", language, points=points))
    except TelegramForbiddenError:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("Check-in push to %s failed: %s", tg_user_id, exc)
