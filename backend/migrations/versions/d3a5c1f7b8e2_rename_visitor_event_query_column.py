"""rename visitor_events.query → search_query (avoids shadowing Flask-SQLAlchemy Model.query)

Revision ID: d3a5c1f7b8e2
Revises: c2e4f8a9b1d3
Create Date: 2026-05-07 16:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd3a5c1f7b8e2'
down_revision = 'c2e4f8a9b1d3'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('visitor_events', schema=None) as batch_op:
        batch_op.alter_column('query', new_column_name='search_query',
                              existing_type=sa.String(length=200),
                              existing_nullable=True)


def downgrade():
    with op.batch_alter_table('visitor_events', schema=None) as batch_op:
        batch_op.alter_column('search_query', new_column_name='query',
                              existing_type=sa.String(length=200),
                              existing_nullable=True)
