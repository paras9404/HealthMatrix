"""add rate_limit_hits table for 429 telemetry

Revision ID: e7b9a2c4d6f8
Revises: d3a5c1f7b8e2
Create Date: 2026-05-07 16:50:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e7b9a2c4d6f8'
down_revision = 'd3a5c1f7b8e2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'rate_limit_hits',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('ip_hash', sa.String(length=64), nullable=True),
        sa.Column('path', sa.String(length=500), nullable=True),
        sa.Column('method', sa.String(length=10), nullable=True),
        sa.Column('user_agent', sa.String(length=255), nullable=True),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('rate_limit_hits', schema=None) as batch_op:
        batch_op.create_index('ix_rate_limit_hits_ip_hash', ['ip_hash'], unique=False)
        batch_op.create_index('ix_rate_limit_hits_path', ['path'], unique=False)
        batch_op.create_index('ix_rate_limit_hits_occurred_at', ['occurred_at'], unique=False)


def downgrade():
    with op.batch_alter_table('rate_limit_hits', schema=None) as batch_op:
        batch_op.drop_index('ix_rate_limit_hits_occurred_at')
        batch_op.drop_index('ix_rate_limit_hits_path')
        batch_op.drop_index('ix_rate_limit_hits_ip_hash')
    op.drop_table('rate_limit_hits')
