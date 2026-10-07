"""boost points on event tracks

Revision ID: a7d1e5b2c9f0
Revises: c32a7cf20ee7
Create Date: 2026-10-07
"""
from alembic import op
import sqlalchemy as sa

revision = 'a7d1e5b2c9f0'
down_revision = 'c32a7cf20ee7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'event_tracks',
        sa.Column('boost_points', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    op.drop_column('event_tracks', 'boost_points')
