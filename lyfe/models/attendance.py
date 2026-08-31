"""Check-in records. One row per person per event, enforced by the database."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from lyfe.models.base import Base, PKMixin, TimestampMixin


class CheckinMethod:
    ADMIN_SCAN = "ADMIN_SCAN"      # staff scanned the guest's LYFE PASS
    VENUE_CODE = "VENUE_CODE"      # guest scanned a rotating code inside the club
    MANUAL = "MANUAL"              # admin ticked someone off by hand


class Attendance(PKMixin, TimestampMixin, Base):
    __tablename__ = "attendance"
    __table_args__ = (UniqueConstraint("event_id", "user_id", name="uq_attendance"),)

    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    method: Mapped[str] = mapped_column(String(16), nullable=False, default=CheckinMethod.ADMIN_SCAN)
    checked_in_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    admin_id: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id", ondelete="SET NULL"))
    scan_device: Mapped[str | None] = mapped_column(String(64))
