"""Events. Everything in LYFE hangs off an event."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lyfe.models.base import Base, PKMixin, TimestampMixin


class EventStatus:
    DRAFT = "DRAFT"
    UPCOMING = "UPCOMING"
    LIVE = "LIVE"
    ENDED = "ENDED"
    ARCHIVED = "ARCHIVED"

    ALL = (DRAFT, UPCOMING, LIVE, ENDED, ARCHIVED)
    ACCEPTS_REQUESTS = (UPCOMING, LIVE)


class Event(PKMixin, TimestampMixin, Base):
    __tablename__ = "events"

    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id", ondelete="RESTRICT"), index=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="RESTRICT"), index=True)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default=EventStatus.DRAFT, index=True)

    doors_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Request window. Outside it the bot politely refuses new tracks.
    requests_open_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requests_open_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Check-in window.
    checkin_open_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checkin_open_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    ticket_url: Mapped[str | None] = mapped_column(String(500))
    poster_url: Mapped[str | None] = mapped_column(String(500))

    city: Mapped["City"] = relationship()  # noqa: F821
    venue: Mapped["Venue"] = relationship()  # noqa: F821

    def accepts_requests(self, now: datetime) -> bool:
        if self.status not in EventStatus.ACCEPTS_REQUESTS:
            return False
        if self.requests_open_from and now < self.requests_open_from:
            return False
        if self.requests_open_until and now > self.requests_open_until:
            return False
        return True
