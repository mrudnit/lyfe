"""gangs.is_public: a leader can open the gang to anyone (team finder)

Revision ID: a9c8e7d6b5f4
Revises: f1a2b3c4d5e6
Create Date: 2026-11-25
"""
from alembic import op
import sqlalchemy as sa

revision = 'a9c8e7d6b5f4'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('gangs', sa.Column('is_public', sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    op.drop_column('gangs', 'is_public')
