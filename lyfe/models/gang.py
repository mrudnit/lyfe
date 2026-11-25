"""Банда: up to five guests who play «Взлом» together for one party.

A gang belongs to one event. One person is in at most one gang per event
(uq_gang_member_event_user), and the gang never has more members than
settings.max_gang_size: both are checked in gang_service under row locks, and
the unique constraints are the last line if two taps race anyway.
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from lyfe.models.base import Base, PKMixin, TimestampMixin


class GangRole:
    LEADER = "leader"
    DRIVER = "driver"
    HACKER = "hacker"
    MUSCLE = "muscle"
    SCOUT = "scout"
    # handed out in this order as people join
    ORDER = (LEADER, DRIVER, HACKER, MUSCLE, SCOUT)


class Gang(PKMixin, TimestampMixin, Base):
    __tablename__ = "gangs"
    __table_args__ = (
        UniqueConstraint("event_id", "name_key", name="uq_gang_event_name"),
    )

    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    # lower-cased, spaces squeezed: «Ночные  Лисы» and «ночные лисы» are one name
    name_key: Mapped[str] = mapped_column(String(32), nullable=False)
    # the part of the invite link after gang_
    invite_code: Mapped[str] = mapped_column(String(16), nullable=False, unique=True, index=True)


class GangMember(PKMixin, TimestampMixin, Base):
    __tablename__ = "gang_members"
    __table_args__ = (
        UniqueConstraint("event_id", "user_id", name="uq_gang_member_event_user"),
        UniqueConstraint("gang_id", "role", name="uq_gang_member_role"),
    )

    gang_id: Mapped[int] = mapped_column(ForeignKey("gangs.id", ondelete="CASCADE"), index=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
