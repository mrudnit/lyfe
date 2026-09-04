"""All models must be imported here so Alembic autogenerate can see them."""
from lyfe.models.admin import AdminAction, AdminRole, AdminUser
from lyfe.models.attendance import Attendance, CheckinMethod
from lyfe.models.base import Base
from lyfe.models.event import Event, EventStatus
from lyfe.models.geo import City, Venue
from lyfe.models.music import (
    EventTrack,
    RequestSource,
    Track,
    TrackRequest,
    TrackStatus,
    TrackVote,
)
from lyfe.models.points import PointsReason, PointTransaction
from lyfe.models.reward import (
    RedemptionStatus,
    Reward,
    RewardKind,
    RewardRedemption,
)
from lyfe.models.user import User

__all__ = [
    "AdminAction",
    "AdminRole",
    "AdminUser",
    "Attendance",
    "Base",
    "CheckinMethod",
    "City",
    "Event",
    "EventStatus",
    "EventTrack",
    "PointTransaction",
    "PointsReason",
    "RedemptionStatus",
    "Reward",
    "RewardKind",
    "RewardRedemption",
    "RequestSource",
    "Track",
    "TrackRequest",
    "TrackStatus",
    "TrackVote",
    "User",
    "Venue",
]
