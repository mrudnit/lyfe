"""gangs and gang members (Банда, up to five per gang, one gang per person per party)

Revision ID: f1a2b3c4d5e6
Revises: e7a1b2c3d4f5
Create Date: 2026-11-25
"""
from alembic import op
import sqlalchemy as sa

revision = 'f1a2b3c4d5e6'
down_revision = 'e7a1b2c3d4f5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'gangs',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('event_id', sa.BigInteger(), sa.ForeignKey('events.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(32), nullable=False),
        sa.Column('name_key', sa.String(32), nullable=False),
        sa.Column('invite_code', sa.String(16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('event_id', 'name_key', name='uq_gang_event_name'),
    )
    op.create_index('ix_gangs_event_id', 'gangs', ['event_id'])
    op.create_index('ix_gangs_invite_code', 'gangs', ['invite_code'], unique=True)
    op.create_table(
        'gang_members',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('gang_id', sa.BigInteger(), sa.ForeignKey('gangs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('event_id', sa.BigInteger(), sa.ForeignKey('events.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(16), nullable=False),
        sa.Column('joined_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('event_id', 'user_id', name='uq_gang_member_event_user'),
        sa.UniqueConstraint('gang_id', 'role', name='uq_gang_member_role'),
    )
    op.create_index('ix_gang_members_gang_id', 'gang_members', ['gang_id'])
    op.create_index('ix_gang_members_event_id', 'gang_members', ['event_id'])
    op.create_index('ix_gang_members_user_id', 'gang_members', ['user_id'])


def downgrade() -> None:
    op.drop_table('gang_members')
    op.drop_table('gangs')
