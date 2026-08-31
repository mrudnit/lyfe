"""
LYFE POINTS as a transaction ledger, never as a single number.

The balance is SUM(delta). This costs almost nothing to build now and makes
every "why do I have 47 points?" question answerable forever.

idempotency_key is the safety net: awarding points for a check-in uses the key
"attendance:{event_id}:{user_id}", so a duplicate call physically cannot pay twice.
"""
from sqlalchemy import BigInteger, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from lyfe.models.base import Base, PKMixin, TimestampMixin


class PointsReason:
    MUSIC_REQUEST = "MUSIC_REQUEST"
    VOTE = "VOTE"
    EVENT_ATTENDANCE = "EVENT_ATTENDANCE"
    REFERRAL = "REFERRAL"
    ACTIVITY = "ACTIVITY"
    MANUAL_ADJUSTMENT = "MANUAL_ADJUSTMENT"
    REWARD_REDEMPTION = "REWARD_REDEMPTION"


class PointTransaction(PKMixin, TimestampMixin, Base):
    __tablename__ = "point_transactions"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reason_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    event_id: Mapped[int | None] = mapped_column(
        ForeignKey("events.id", ondelete="SET NULL"), index=True
    )
    ref_type: Mapped[str | None] = mapped_column(String(32))
    ref_id: Mapped[int | None] = mapped_column(BigInteger)

    created_by_admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL")
    )

    # The whole point of this table.
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
