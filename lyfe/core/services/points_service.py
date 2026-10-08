"""LYFE POINTS ledger.

Every award goes through award(), which requires an idempotency key. If the same
key is used twice the second call is a no-op. This is what stops a retried
webhook or a double-tapped button from paying someone twice.
"""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lyfe.models import PointTransaction


async def award(
    session: AsyncSession,
    *,
    user_id: int,
    delta: int,
    reason_code: str,
    idempotency_key: str,
    event_id: int | None = None,
    ref_type: str | None = None,
    ref_id: int | None = None,
    admin_id: int | None = None,
) -> PointTransaction | None:
    """Returns the new transaction, or None if nothing was written."""
    if delta == 0:
        return None

    existing = await session.execute(
        select(PointTransaction).where(PointTransaction.idempotency_key == idempotency_key)
    )
    if existing.scalar_one_or_none() is not None:
        return None

    tx = PointTransaction(
        user_id=user_id,
        delta=delta,
        reason_code=reason_code,
        event_id=event_id,
        ref_type=ref_type,
        ref_id=ref_id,
        created_by_admin_id=admin_id,
        idempotency_key=idempotency_key,
    )
    try:
        # Savepoint: if the same key lands at the same moment from another
        # request, only this insert is undone and the caller carries on.
        async with session.begin_nested():
            session.add(tx)
            await session.flush()
    except IntegrityError:
        return None
    return tx
