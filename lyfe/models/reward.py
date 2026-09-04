"""Rewards and their redemptions.

Design rule that shapes this whole module: a reward may only exist if somebody
who is already standing on the guest's path can hand it over. That is why there
are exactly two kinds.

  PRIORITY_TRACK  costs nothing to fulfil and needs no human at all — the track
                  is pinned to the top of the DJ screen automatically.
  DOOR            handed over at the entrance by the same person, on the same
                  phone, on the same screen that already does check-in.

Anything that would require the bar, a courier or a new device is deliberately
not modelled.
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lyfe.models.base import Base, PKMixin, TimestampMixin


class RewardKind:
    PRIORITY_TRACK = "PRIORITY_TRACK"
    DOOR = "DOOR"

    ALL = (PRIORITY_TRACK, DOOR)


class RedemptionStatus:
    ISSUED = "ISSUED"        # bought, not yet handed over
    USED = "USED"            # handed over at the door, or applied automatically
    REFUNDED = "REFUNDED"    # event ended unused, points returned
    CANCELLED = "CANCELLED"

    ALL = (ISSUED, USED, REFUNDED, CANCELLED)


class Reward(PKMixin, TimestampMixin, Base):
    __tablename__ = "rewards"

    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(24), nullable=False, default=RewardKind.DOOR)

    cost_points: Mapped[int] = mapped_column(Integer, nullable=False)

    # NULL means unlimited. Decremented atomically on purchase.
    quantity_total: Mapped[int | None] = mapped_column(Integer)
    quantity_left: Mapped[int | None] = mapped_column(Integer)

    # How many one person may hold per event.
    per_user_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # NULL means the reward applies to whatever event is current.
    event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"))

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=100)


class RewardRedemption(PKMixin, TimestampMixin, Base):
    __tablename__ = "reward_redemptions"

    reward_id: Mapped[int] = mapped_column(ForeignKey("rewards.id", ondelete="RESTRICT"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)

    code: Mapped[str] = mapped_column(String(24), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=RedemptionStatus.ISSUED, index=True
    )

    spent_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload: Mapped[dict | None] = mapped_column(JSONB)

    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    used_by_admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL")
    )
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    reward: Mapped["Reward"] = relationship(lazy="joined")
