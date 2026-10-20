"""drop the «🚪 Без очереди» reward and give everyone who bought it their points back

Revision ID: d5e6f7a8b9c0
Revises: c8f1a2d3e4b5
Create Date: 2026-10-20

The reward is switched off (it stays in the table: past redemptions point at
it). Every purchase that was not refunded yet is refunded: points go back with
the same idempotency key refund_unused() uses, so nobody is paid twice, and the
redemption is marked REFUNDED so the door scanner no longer lists it.
"""
from alembic import op

revision = 'd5e6f7a8b9c0'
down_revision = 'c8f1a2d3e4b5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE rewards SET is_active = false WHERE code = 'SKIP_QUEUE'")
    op.execute("""
        INSERT INTO point_transactions
            (user_id, delta, reason_code, idempotency_key, event_id, ref_type, ref_id, created_at, updated_at)
        SELECT rr.user_id, rr.spent_points, 'MANUAL_ADJUSTMENT', 'reward_refund:' || rr.id,
               rr.event_id, 'reward_redemption', rr.id, now(), now()
        FROM reward_redemptions rr
        JOIN rewards r ON r.id = rr.reward_id
        WHERE r.code = 'SKIP_QUEUE' AND rr.status IN ('ISSUED', 'USED') AND rr.spent_points > 0
        ON CONFLICT (idempotency_key) DO NOTHING
    """)
    op.execute("""
        UPDATE reward_redemptions rr SET status = 'REFUNDED', refunded_at = now(), updated_at = now()
        FROM rewards r
        WHERE r.id = rr.reward_id AND r.code = 'SKIP_QUEUE' AND rr.status IN ('ISSUED', 'USED')
    """)


def downgrade() -> None:
    # Refunds are not taken back; the reward can be switched on again by hand.
    op.execute("UPDATE rewards SET is_active = true WHERE code = 'SKIP_QUEUE'")
