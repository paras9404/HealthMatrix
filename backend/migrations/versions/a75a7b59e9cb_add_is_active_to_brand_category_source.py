"""add is_active to brand, category, source

Revision ID: a75a7b59e9cb
Revises: f9a991b725a1
Create Date: 2026-04-30 16:43:55.485741

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a75a7b59e9cb'
down_revision = 'f9a991b725a1'
branch_labels = None
depends_on = None


def upgrade():
    # Add nullable first so existing rows get NULL, backfill with TRUE, then enforce NOT NULL.
    for table in ('brands', 'categories', 'sources'):
        op.add_column(table, sa.Column('is_active', sa.Boolean(),
                                       nullable=True, server_default=sa.true()))
        op.execute(f"UPDATE {table} SET is_active = TRUE WHERE is_active IS NULL")
        op.alter_column(table, 'is_active', nullable=False, server_default=None)
        op.create_index(f'ix_{table}_is_active', table, ['is_active'])


def downgrade():
    for table in ('sources', 'categories', 'brands'):
        op.drop_index(f'ix_{table}_is_active', table_name=table)
        op.drop_column(table, 'is_active')
