"""Tickets and the Halloween game.

Tickets are sold by GoOut. Until GoOut gives API access we cannot see who
bought what, so a guest attaches the code from their GoOut ticket to their
LYFE ID. The app then shows that code as a QR next to the LYFE PASS, and the
door scanner shows it next to the guest's name — one phone, one screen.

A code can belong to one person only, which is what stops a single ticket
from being attached by a whole group chat.
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from lyfe.models.base import Base, PKMixin, TimestampMixin


class TicketProvider:
    GOOUT = "GOOUT"


class Ticket(PKMixin, TimestampMixin, Base):
    __tablename__ = "tickets"
    __table_args__ = (
        UniqueConstraint("event_id", "user_id", name="uq_ticket_event_user"),
        UniqueConstraint("provider", "code", name="uq_ticket_provider_code"),
    )

    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(16), nullable=False, default=TicketProvider.GOOUT)
    code: Mapped[str] = mapped_column(String(128), nullable=False)


class GameSession(PKMixin, TimestampMixin, Base):
    """One attempt at the mini game. The server draws the pumpkins from the
    seed, so the score it accepts is the one it can recompute."""

    __tablename__ = "game_sessions"

    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False, default="pumpkin_rush")
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    score: Mapped[int | None] = mapped_column(Integer)
