"""«Взлом» runs belong to the gang they were played for; one gang change per party

Revision ID: b2c3d4e5f6a7
Revises: a9c8e7d6b5f4
Create Date: 2026-11-25
"""
from alembic import op
import sqlalchemy as sa

revision = 'b2c3d4e5f6a7'
down_revision = 'a9c8e7d6b5f4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('game_sessions', sa.Column('gang_id', sa.BigInteger(), nullable=True))
    op.create_foreign_key('fk_game_sessions_gang_id', 'game_sessions', 'gangs', ['gang_id'], ['id'], ondelete='SET NULL')
    op.create_index('ix_game_sessions_gang_id', 'game_sessions', ['gang_id'])
    # runs played so far count for the gang the player is in now
    op.execute("""
        UPDATE game_sessions g SET gang_id = m.gang_id
        FROM gang_members m
        WHERE g.kind = 'hack' AND m.user_id = g.user_id AND m.event_id = g.event_id
    """)
    op.create_table(
        'gang_leaves',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('event_id', sa.BigInteger(), sa.ForeignKey('events.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('gang_name', sa.String(32), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_gang_leaves_event_id', 'gang_leaves', ['event_id'])
    op.create_index('ix_gang_leaves_user_id', 'gang_leaves', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_gang_leaves_user_id', 'gang_leaves')
    op.drop_index('ix_gang_leaves_event_id', 'gang_leaves')
    op.drop_table('gang_leaves')
    op.drop_index('ix_game_sessions_gang_id', 'game_sessions')
    op.drop_constraint('fk_game_sessions_gang_id', 'game_sessions', type_='foreignkey')
    op.drop_column('game_sessions', 'gang_id')
