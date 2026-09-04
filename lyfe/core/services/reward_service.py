"""Buying and redeeming rewards.

Points are deducted at purchase, not at hand-over. Otherwise the same balance
could be spent three times while the codes sat unused in three chats.

Everything that touches a balance goes through the ledger, so "where did my
points go" always has an answer.
"""
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lyfe.core.services import points_service, user_service
from lyfe.models import (
    Event,
    EventStatus,
    EventTrack,
    PointsReason,
    RedemptionStatus,
    Reward,
    RewardKind,
    RewardRedemption,
    TrackRequest,
    TrackStatus,
    User,
)

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no look-alikes
MAX_PRIORITY_PER_EVENT = 2


class BuyResult:
    OK = "OK"
    NOT_ENOUGH_POINTS = "NOT_ENOUGH_POINTS"
    SOLD_OUT = "SOLD_OUT"
    LIMIT_REACHED = "LIMIT_REACHED"
    UNAVAILABLE = "UNAVAILABLE"
    NO_TRACK = "NO_TRACK"
    PRIORITY_FULL = "PRIORITY_FULL"


class UseResult:
    OK = "OK"
    ALREADY_USED = "ALREADY_USED"
    NOT_FOUND = "NOT_FOUND"
    REFUNDED = "REFUNDED"


@dataclass
class BuyOutcome:
    status: str
    redemption: RewardRedemption | None = None
    balance: int = 0


def generate_code() -> str:
    body = "".join(secrets.choice(CODE_ALPHABET) for _ in range(4))
    return f"LYFE-{body}"


async def available_rewards(session: AsyncSession, *, event: Event) -> list[Reward]:
    rows = await session.execute(
        select(Reward)
        .where(
            Reward.is_active.is_(True),
            (Reward.event_id.is_(None)) | (Reward.event_id == event.id),
        )
        .order_by(Reward.position, Reward.id)
    )
    return [
        reward
        for reward in rows.scalars()
        if reward.quantity_left is None or reward.quantity_left > 0
    ]


async def held_by_user(
    session: AsyncSession, *, user_id: int, event_id: int
) -> list[RewardRedemption]:
    rows = await session.execute(
        select(RewardRedemption)
        .where(
            RewardRedemption.user_id == user_id,
            RewardRedemption.event_id == event_id,
            RewardRedemption.status == RedemptionStatus.ISSUED,
        )
        .order_by(RewardRedemption.id)
    )
    return list(rows.scalars().unique())


async def purchase(
    session: AsyncSession,
    *,
    user: User,
    reward: Reward,
    event: Event,
    payload: dict | None = None,
) -> BuyOutcome:
    if not reward.is_active or event.status not in (EventStatus.UPCOMING, EventStatus.LIVE):
        return BuyOutcome(status=BuyResult.UNAVAILABLE)

    # Serialise everything this person does with their balance.
    await session.execute(select(User.id).where(User.id == user.id).with_for_update())

    balance = await user_service.get_points_balance(session, user.id)
    if balance < reward.cost_points:
        return BuyOutcome(status=BuyResult.NOT_ENOUGH_POINTS, balance=balance)

    held = await session.scalar(
        select(func.count(RewardRedemption.id)).where(
            RewardRedemption.user_id == user.id,
            RewardRedemption.reward_id == reward.id,
            RewardRedemption.event_id == event.id,
            RewardRedemption.status.in_((RedemptionStatus.ISSUED, RedemptionStatus.USED)),
        )
    )
    if (held or 0) >= reward.per_user_limit:
        return BuyOutcome(status=BuyResult.LIMIT_REACHED, balance=balance)

    event_track: EventTrack | None = None
    if reward.kind == RewardKind.PRIORITY_TRACK:
        event_track_id = (payload or {}).get("event_track_id")
        event_track = await session.get(EventTrack, event_track_id) if event_track_id else None
        if event_track is None or event_track.event_id != event.id:
            return BuyOutcome(status=BuyResult.NO_TRACK, balance=balance)
        if event_track.status == TrackStatus.PLAYED:
            return BuyOutcome(status=BuyResult.NO_TRACK, balance=balance)

        pinned = await session.scalar(
            select(func.count(EventTrack.id)).where(
                EventTrack.event_id == event.id, EventTrack.is_priority.is_(True)
            )
        )
        # A DJ set has to stay a DJ set.
        if (pinned or 0) >= MAX_PRIORITY_PER_EVENT:
            return BuyOutcome(status=BuyResult.PRIORITY_FULL, balance=balance)

    if reward.quantity_left is not None:
        claimed = await session.execute(
            update(Reward)
            .where(Reward.id == reward.id, Reward.quantity_left > 0)
            .values(quantity_left=Reward.quantity_left - 1)
            .returning(Reward.id)
        )
        if claimed.scalar_one_or_none() is None:
            return BuyOutcome(status=BuyResult.SOLD_OUT, balance=balance)

    redemption = RewardRedemption(
        reward_id=reward.id,
        user_id=user.id,
        event_id=event.id,
        code=generate_code(),
        spent_points=reward.cost_points,
        payload=payload,
        status=RedemptionStatus.ISSUED,
    )
    session.add(redemption)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        redemption.code = generate_code()
        session.add(redemption)
        await session.flush()

    await points_service.award(
        session,
        user_id=user.id,
        delta=-reward.cost_points,
        reason_code=PointsReason.REWARD_REDEMPTION,
        idempotency_key=f"reward:{redemption.id}",
        event_id=event.id,
        ref_type="reward_redemption",
        ref_id=redemption.id,
    )

    # Nothing to hand over: apply it and close it in the same breath.
    if reward.kind == RewardKind.PRIORITY_TRACK and event_track is not None:
        event_track.is_priority = True
        event_track.priority_at = datetime.now(timezone.utc)
        redemption.status = RedemptionStatus.USED
        redemption.used_at = datetime.now(timezone.utc)

    return BuyOutcome(
        status=BuyResult.OK,
        redemption=redemption,
        balance=balance - reward.cost_points,
    )


async def mark_used(
    session: AsyncSession, *, redemption_id: int, admin_id: int
) -> tuple[str, RewardRedemption | None]:
    redemption = await session.get(RewardRedemption, redemption_id)
    if redemption is None:
        return UseResult.NOT_FOUND, None
    if redemption.status == RedemptionStatus.USED:
        return UseResult.ALREADY_USED, redemption
    if redemption.status != RedemptionStatus.ISSUED:
        return UseResult.REFUNDED, redemption

    redemption.status = RedemptionStatus.USED
    redemption.used_at = datetime.now(timezone.utc)
    redemption.used_by_admin_id = admin_id
    return UseResult.OK, redemption


async def refund_unused(session: AsyncSession, *, event: Event) -> int:
    """Called once an event is over. Somebody who bought a reward and never
    showed up gets their points back — cheaper than arguing about it."""
    rows = await session.execute(
        select(RewardRedemption).where(
            RewardRedemption.event_id == event.id,
            RewardRedemption.status == RedemptionStatus.ISSUED,
        )
    )
    refunded = 0
    now = datetime.now(timezone.utc)
    for redemption in rows.scalars().unique():
        redemption.status = RedemptionStatus.REFUNDED
        redemption.refunded_at = now
        await points_service.award(
            session,
            user_id=redemption.user_id,
            delta=redemption.spent_points,
            reason_code=PointsReason.MANUAL_ADJUSTMENT,
            idempotency_key=f"reward_refund:{redemption.id}",
            event_id=event.id,
            ref_type="reward_redemption",
            ref_id=redemption.id,
        )
        if redemption.reward and redemption.reward.quantity_left is not None:
            redemption.reward.quantity_left += 1
        refunded += 1
    return refunded


async def user_requests_for_event(
    session: AsyncSession, *, user_id: int, event_id: int
) -> list[EventTrack]:
    """The tracks this person asked for — the choices offered when buying a
    guaranteed play."""
    rows = await session.execute(
        select(EventTrack)
        .join(TrackRequest, TrackRequest.event_track_id == EventTrack.id)
        .where(
            TrackRequest.user_id == user_id,
            EventTrack.event_id == event_id,
            EventTrack.status.in_((TrackStatus.NEW, TrackStatus.APPROVED)),
            EventTrack.is_priority.is_(False),
        )
        .order_by(EventTrack.id)
    )
    return list(rows.scalars().unique())
