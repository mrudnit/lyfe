"""count 22.09 as a night for everyone who got the attendance gift

The door scanner could not keep up on 22.09, so everyone registered was given
the attendance points as a gift (key gift:back2lyfe-2026-09:<user>). The points
arrived, but MY LYFE counts nights from the attendance table, so those guests
saw "0 nights". This writes the missing attendance rows for that party.

Nobody gets points here: attendance points are paid by check-in, and these
guests already have theirs through the gift. Guests who were scanned keep
their real check-in row untouched.

Revision ID: c8f1a2d3e4b5
Revises: b4e2c7a91d30
Create Date: 2026-10-08
"""
from alembic import op
import sqlalchemy as sa

revision = 'c8f1a2d3e4b5'
down_revision = 'b4e2c7a91d30'
branch_labels = None
depends_on = None

GIFT_KEY_PREFIX = 'gift:back2lyfe-2026-09:'


def upgrade() -> None:
    conn = op.get_bind()
    # The 22.09 party: the latest event that started on 21–23 Sept 2026.
    event_id = conn.execute(
        sa.text(
            """
            SELECT id FROM events
            WHERE starts_at >= '2026-09-21' AND starts_at < '2026-09-24'
            ORDER BY starts_at DESC LIMIT 1
            """
        )
    ).scalar()
    if event_id is None:
        return

    conn.execute(
        sa.text(
            """
            INSERT INTO attendance (event_id, user_id, method, checked_in_at, created_at, updated_at)
            SELECT :event_id, pt.user_id, 'MANUAL', e.starts_at, now(), now()
            FROM point_transactions pt
            JOIN events e ON e.id = :event_id
            WHERE pt.idempotency_key LIKE :prefix
            ON CONFLICT ON CONSTRAINT uq_attendance DO NOTHING
            """
        ),
        dict(event_id=event_id, prefix=GIFT_KEY_PREFIX + '%'),
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            DELETE FROM attendance
            WHERE method = 'MANUAL' AND admin_id IS NULL AND scan_device IS NULL
              AND event_id = (SELECT id FROM events
                              WHERE starts_at >= '2026-09-21' AND starts_at < '2026-09-24'
                              ORDER BY starts_at DESC LIMIT 1)
            """
        )
    )
