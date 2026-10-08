"""halloween: tickets, game sessions, reward ladder, 22.09 attendance gift

Revision ID: b4e2c7a91d30
Revises: a7d1e5b2c9f0
Create Date: 2026-10-08
"""
from alembic import op
import sqlalchemy as sa

revision = 'b4e2c7a91d30'
down_revision = 'a7d1e5b2c9f0'
branch_labels = None
depends_on = None

# The reward ladder. Prices are set against what a guest earns in one night
# (about 10-15 points: tracks, likes, check-in) so that BOOST is an every-night
# thing, a drink or skipping the queue takes two or three nights, and the big
# ones are for regulars. Door rewards are handed over by the person who scans
# the LYFE PASS; the scanner already lists them on the same screen.
REWARDS = [
    # code, name, description, kind, cost, per_user_limit, active, position
    ("PRIORITY_TRACK", "🎯 Гарантия трека", "Твой трек закрепляется у DJ и прозвучит этой ночью.",
     "PRIORITY_TRACK", 40, 1, True, 10),
    ("SKIP_QUEUE", "🚪 Без очереди", "Проходишь мимо очереди. Покажи LYFE PASS на входе.",
     "DOOR", 25, 1, True, 20),
    ("WELCOME_DRINK", "🍹 Напиток от LYFE", "На входе получаешь жетон, на баре меняешь на напиток.",
     "DOOR", 40, 1, True, 30),
    ("PLUS_ONE", "👥 Друг бесплатно", "Приводишь друга без билета.",
     "DOOR", 100, 1, False, 40),
    ("FREE_ENTRY", "🎟 Вход за баллы", "Эта ночь для тебя бесплатна.",
     "DOOR", 150, 1, False, 50),
]

# Same key the grant_points.py script uses, so nobody who already got the
# 22.09 points from the script is paid twice.
GIFT_CAMPAIGN = "back2lyfe-2026-09"
GIFT_POINTS = 10


def upgrade() -> None:
    op.create_table(
        'tickets',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('event_id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('provider', sa.String(length=16), nullable=False),
        sa.Column('code', sa.String(length=128), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['event_id'], ['events.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('event_id', 'user_id', name='uq_ticket_event_user'),
        sa.UniqueConstraint('provider', 'code', name='uq_ticket_provider_code'),
    )
    op.create_index('ix_tickets_event_id', 'tickets', ['event_id'])
    op.create_index('ix_tickets_user_id', 'tickets', ['user_id'])

    op.create_table(
        'game_sessions',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('event_id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('kind', sa.String(length=24), nullable=False),
        sa.Column('seed', sa.Integer(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('score', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['event_id'], ['events.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_game_sessions_event_id', 'game_sessions', ['event_id'])
    op.create_index('ix_game_sessions_user_id', 'game_sessions', ['user_id'])

    conn = op.get_bind()
    for code, name, description, kind, cost, limit, active, position in REWARDS:
        conn.execute(
            sa.text(
                """
                INSERT INTO rewards (code, name, description, kind, cost_points, per_user_limit,
                                     is_active, position, created_at, updated_at)
                VALUES (:code, :name, :description, :kind, :cost, :limit, :active, :position, now(), now())
                ON CONFLICT (code) DO UPDATE SET
                    name = EXCLUDED.name, description = EXCLUDED.description, kind = EXCLUDED.kind,
                    cost_points = EXCLUDED.cost_points, per_user_limit = EXCLUDED.per_user_limit,
                    is_active = EXCLUDED.is_active, position = EXCLUDED.position, updated_at = now()
                """
            ),
            dict(code=code, name=name, description=description, kind=kind, cost=cost,
                 limit=limit, active=active, position=position),
        )

    conn.execute(
        sa.text(
            """
            INSERT INTO point_transactions (user_id, delta, reason_code, ref_type, idempotency_key,
                                            created_at, updated_at)
            SELECT id, :points, 'GIFT', 'gift', 'gift:' || :campaign || ':' || id, now(), now()
            FROM users
            WHERE deleted_at IS NULL
            ON CONFLICT (idempotency_key) DO NOTHING
            """
        ),
        dict(points=GIFT_POINTS, campaign=GIFT_CAMPAIGN),
    )


def downgrade() -> None:
    # Points already handed out stay where they are: the ledger is append-only.
    op.drop_index('ix_game_sessions_user_id', table_name='game_sessions')
    op.drop_index('ix_game_sessions_event_id', table_name='game_sessions')
    op.drop_table('game_sessions')
    op.drop_index('ix_tickets_user_id', table_name='tickets')
    op.drop_index('ix_tickets_event_id', table_name='tickets')
    op.drop_table('tickets')
