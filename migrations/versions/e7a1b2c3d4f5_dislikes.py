"""dislikes («В розыск»): a vote can be −1, and the track keeps a dislike counter

Revision ID: e7a1b2c3d4f5
Revises: d5e6f7a8b9c0
Create Date: 2026-11-25
"""
from alembic import op
import sqlalchemy as sa

revision = 'e7a1b2c3d4f5'
down_revision = 'd5e6f7a8b9c0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('track_votes', sa.Column('value', sa.SmallInteger(), nullable=False, server_default='1'))
    op.add_column('event_tracks', sa.Column('dislikes_count', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('event_tracks', 'dislikes_count')
    op.drop_column('track_votes', 'value')
