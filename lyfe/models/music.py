"""
Three-level track model — the most important design decision in the schema.

  tracks          canonical track, one row per song in the whole project
  event_tracks    that track in the context of one event; this is the DJ's list
  track_requests  who exactly asked for it; these are the notification targets

23 people asking for FE!N  =>  1 event_track (counter 23)  +  23 track_requests.
The DJ presses PLAYED once on the event_track and 23 people get the push.
Deduplication is a property of the schema, not a moderation chore.
"""
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lyfe.models.base import Base, PKMixin, TimestampMixin


class TrackStatus:
    NEW = "NEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PLAYED = "PLAYED"

    ALL = (NEW, APPROVED, REJECTED, PLAYED)


class RequestSource:
    SEARCH = "SEARCH"      # picked from catalogue search results
    LINK = "LINK"          # pasted a Spotify / YouTube / Apple Music link
    MANUAL = "MANUAL"      # typed free text, resolver found nothing


class Track(PKMixin, TimestampMixin, Base):
    __tablename__ = "tracks"

    artist_name: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    album_name: Mapped[str | None] = mapped_column(String(255))
    cover_url: Mapped[str | None] = mapped_column(String(500))
    external_url: Mapped[str | None] = mapped_column(String(500))
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    # Which catalogue this came from ("itunes", "deezer", "spotify", "manual").
    provider: Mapped[str | None] = mapped_column(String(24))
    provider_track_id: Mapped[str | None] = mapped_column(String(128))

    # Deduplication key, e.g. "traviscott|fein". Unique across the project.
    normalized_key: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)

    # True when the resolver could not identify the track and a human should look.
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    @property
    def display(self) -> str:
        return f"{self.artist_name} - {self.title}"


class EventTrack(PKMixin, TimestampMixin, Base):
    """A track in the context of one event. This is what the DJ screen shows."""

    __tablename__ = "event_tracks"
    __table_args__ = (UniqueConstraint("event_id", "track_id", name="uq_event_track"),)

    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    track_id: Mapped[int] = mapped_column(ForeignKey("tracks.id", ondelete="RESTRICT"), index=True)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default=TrackStatus.NEW, index=True)

    # Denormalised counters — read on every TOP screen, so we keep them here.
    requests_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    votes_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    played_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    played_by_admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL")
    )

    # Bought with points: pinned to the top of the DJ screen, guaranteed to play.
    is_priority: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    priority_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    track: Mapped["Track"] = relationship(lazy="joined")

    @property
    def score(self) -> int:
        return self.requests_count + self.votes_count


class TrackRequest(PKMixin, TimestampMixin, Base):
    """One person asking for one track at one event. Notification target."""

    __tablename__ = "track_requests"
    __table_args__ = (
        UniqueConstraint("event_track_id", "user_id", name="uq_track_request_user"),
    )

    event_track_id: Mapped[int] = mapped_column(
        ForeignKey("event_tracks.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default=RequestSource.SEARCH)
    raw_input: Mapped[str | None] = mapped_column(String(500))

    # Set when the user has been told their track was played.
    notified_played_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TrackVote(PKMixin, TimestampMixin, Base):
    """A like on someone else's request. This IS the voting system."""

    __tablename__ = "track_votes"
    __table_args__ = (UniqueConstraint("event_track_id", "user_id", name="uq_track_vote_user"),)

    event_track_id: Mapped[int] = mapped_column(
        ForeignKey("event_tracks.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
