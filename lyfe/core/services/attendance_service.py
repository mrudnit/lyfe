"""Check-in at the door.

The database, not the code, guarantees that nobody is counted twice: a unique
constraint on (event_id, user_id) plus an idempotency key on the points ledger.
Even if the scanner fires the same request five times over a flaky connection,
the guest gets ten points once.
"""
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lyfe.config import get_settings
from lyfe.core.services import points_service
from lyfe.models import Attendance, CheckinMethod, Event, PointsReason, User

settings = get_settings()


class CheckinResult:
    OK = "OK"
    ALREADY = "ALREADY"
    INVALID_TOKEN = "INVALID_TOKEN"
    UNKNOWN_USER = "UNKNOWN_USER"
    BLOCKED = "BLOCKED"
    WINDOW_CLOSED = "WINDOW_CLOSED"
    NO_EVENT = "NO_EVENT"


@dataclass
class CheckinOutcome:
    status: str
    lyfe_id: str | None = None
    name: str | None = None
    points: int = 0
    checked_in_at: str | None = None
    tg_user_id: int | None = None
    language: str = "ru"


def checkin_open(event: Event, now: datetime) -> bool:
    if event.checkin_open_from and now < event.checkin_open_from:
        return False
    if event.checkin_open_until and now > event.checkin_open_until:
        return False
    return True


async def check_in(
    session: AsyncSession,
    *,
    event: Event,
    user_id: int,
    admin_id: int | None = None,
    method: str = CheckinMethod.ADMIN_SCAN,
    device: str | None = None,
) -> CheckinOutcome:
    now = datetime.now(timezone.utc)

    user = await session.get(User, user_id)
    if user is None or user.deleted_at is not None:
        return CheckinOutcome(status=CheckinResult.UNKNOWN_USER)
    if user.is_blocked:
        return CheckinOutcome(status=CheckinResult.BLOCKED, lyfe_id=user.lyfe_id, name=user.name)

    if not checkin_open(event, now):
        return CheckinOutcome(
            status=CheckinResult.WINDOW_CLOSED, lyfe_id=user.lyfe_id, name=user.name
        )

    existing = await session.scalar(
        select(Attendance).where(
            Attendance.event_id == event.id, Attendance.user_id == user.id
        )
    )
    if existing is not None:
        return CheckinOutcome(
            status=CheckinResult.ALREADY,
            lyfe_id=user.lyfe_id,
            name=user.name,
            checked_in_at=existing.checked_in_at.isoformat(),
        )

    attendance = Attendance(
        event_id=event.id,
        user_id=user.id,
        method=method,
        checked_in_at=now,
        admin_id=admin_id,
        scan_device=(device or "")[:64] or None,
    )
    session.add(attendance)
    try:
        await session.flush()
    except IntegrityError:
        # Two scans landed at the same moment. The constraint did its job.
        await session.rollback()
        return CheckinOutcome(
            status=CheckinResult.ALREADY, lyfe_id=user.lyfe_id, name=user.name
        )

    await points_service.award(
        session,
        user_id=user.id,
        delta=settings.points_attendance,
        reason_code=PointsReason.EVENT_ATTENDANCE,
        idempotency_key=f"attendance:{event.id}:{user.id}",
        event_id=event.id,
        ref_type="attendance",
        ref_id=attendance.id,
        admin_id=admin_id,
    )

    return CheckinOutcome(
        status=CheckinResult.OK,
        lyfe_id=user.lyfe_id,
        name=user.name,
        points=settings.points_attendance,
        checked_in_at=now.isoformat(),
        tg_user_id=user.tg_user_id,
        language=user.language,
    )


async def find_by_lyfe_id(session: AsyncSession, lyfe_id: str) -> User | None:
    """Manual fallback when a QR will not scan."""
    cleaned = (lyfe_id or "").strip().lstrip("#").lstrip("LYFE").strip().lstrip("#")
    if not cleaned.isdigit():
        return None
    padded = f"{int(cleaned):04d}"
    return await session.scalar(select(User).where(User.lyfe_id == padded))


async def count_checked_in(session: AsyncSession, *, event_id: int) -> int:
    return int(
        await session.scalar(
            select(func.count(Attendance.id)).where(Attendance.event_id == event_id)
        )
        or 0
    )
