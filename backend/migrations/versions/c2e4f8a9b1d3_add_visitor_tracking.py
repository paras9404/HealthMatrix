"""add visitor_sessions and visitor_events tables

Revision ID: c2e4f8a9b1d3
Revises: b1f3c2a4d5e6
Create Date: 2026-05-07 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = 'c2e4f8a9b1d3'
down_revision = 'b1f3c2a4d5e6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'visitor_sessions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('session_uuid', sa.String(length=36), nullable=False),
        sa.Column('visitor_id', sa.String(length=36), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('page_view_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('event_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('entry_path', sa.String(length=500), nullable=True),
        sa.Column('referrer_domain', sa.String(length=160), nullable=True),
        sa.Column('device_type', sa.String(length=20), nullable=True),
        sa.Column('browser', sa.String(length=40), nullable=True),
        sa.Column('os', sa.String(length=40), nullable=True),
        sa.Column('ip_hash', sa.String(length=64), nullable=True),
        sa.Column('country', sa.String(length=2), nullable=True),
        sa.Column('is_bot', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('session_uuid', name='uq_visitor_sessions_session_uuid'),
    )
    with op.batch_alter_table('visitor_sessions', schema=None) as batch_op:
        batch_op.create_index('ix_visitor_sessions_session_uuid', ['session_uuid'], unique=False)
        batch_op.create_index('ix_visitor_sessions_visitor_id', ['visitor_id'], unique=False)
        batch_op.create_index('ix_visitor_sessions_started_at', ['started_at'], unique=False)
        batch_op.create_index('ix_visitor_sessions_last_seen_at', ['last_seen_at'], unique=False)
        batch_op.create_index('ix_visitor_sessions_referrer_domain', ['referrer_domain'], unique=False)
        batch_op.create_index('ix_visitor_sessions_device_type', ['device_type'], unique=False)
        batch_op.create_index('ix_visitor_sessions_ip_hash', ['ip_hash'], unique=False)
        batch_op.create_index('ix_visitor_sessions_is_bot', ['is_bot'], unique=False)

    op.create_table(
        'visitor_events',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=False),
        sa.Column('visitor_id', sa.String(length=36), nullable=False),
        sa.Column('event_type', sa.String(length=30), nullable=False),
        sa.Column('path', sa.String(length=500), nullable=True),
        sa.Column('entity_type', sa.String(length=40), nullable=True),
        sa.Column('entity_id', sa.String(length=40), nullable=True),
        sa.Column('referrer', sa.String(length=500), nullable=True),
        sa.Column('query', sa.String(length=200), nullable=True),
        sa.Column('meta', sa.JSON().with_variant(JSONB(), 'postgresql'), nullable=True),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['visitor_sessions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('visitor_events', schema=None) as batch_op:
        batch_op.create_index('ix_visitor_events_session_id', ['session_id'], unique=False)
        batch_op.create_index('ix_visitor_events_visitor_id', ['visitor_id'], unique=False)
        batch_op.create_index('ix_visitor_events_event_type', ['event_type'], unique=False)
        batch_op.create_index('ix_visitor_events_path', ['path'], unique=False)
        batch_op.create_index('ix_visitor_events_entity_type', ['entity_type'], unique=False)
        batch_op.create_index('ix_visitor_events_entity_id', ['entity_id'], unique=False)
        batch_op.create_index('ix_visitor_events_occurred_at', ['occurred_at'], unique=False)
        batch_op.create_index('ix_visitor_events_occurred_event', ['occurred_at', 'event_type'], unique=False)
        batch_op.create_index('ix_visitor_events_entity', ['entity_type', 'entity_id'], unique=False)


def downgrade():
    with op.batch_alter_table('visitor_events', schema=None) as batch_op:
        batch_op.drop_index('ix_visitor_events_entity')
        batch_op.drop_index('ix_visitor_events_occurred_event')
        batch_op.drop_index('ix_visitor_events_occurred_at')
        batch_op.drop_index('ix_visitor_events_entity_id')
        batch_op.drop_index('ix_visitor_events_entity_type')
        batch_op.drop_index('ix_visitor_events_path')
        batch_op.drop_index('ix_visitor_events_event_type')
        batch_op.drop_index('ix_visitor_events_visitor_id')
        batch_op.drop_index('ix_visitor_events_session_id')
    op.drop_table('visitor_events')

    with op.batch_alter_table('visitor_sessions', schema=None) as batch_op:
        batch_op.drop_index('ix_visitor_sessions_is_bot')
        batch_op.drop_index('ix_visitor_sessions_ip_hash')
        batch_op.drop_index('ix_visitor_sessions_device_type')
        batch_op.drop_index('ix_visitor_sessions_referrer_domain')
        batch_op.drop_index('ix_visitor_sessions_last_seen_at')
        batch_op.drop_index('ix_visitor_sessions_started_at')
        batch_op.drop_index('ix_visitor_sessions_visitor_id')
        batch_op.drop_index('ix_visitor_sessions_session_uuid')
    op.drop_table('visitor_sessions')
