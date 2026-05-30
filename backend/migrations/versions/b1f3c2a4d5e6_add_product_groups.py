"""add product_groups table and supplement.product_group_id / variant_label

Revision ID: b1f3c2a4d5e6
Revises: d9741c1b50c3
Create Date: 2026-05-05 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b1f3c2a4d5e6'
down_revision = 'd9741c1b50c3'
branch_labels = None
depends_on = None


def upgrade():
    # Create product_groups WITHOUT the FK to supplements.primary_supplement_id yet.
    # supplements doesn't have product_group_id at this moment, and a circular FK
    # would prevent SQLite from recreating the table when we add it.
    op.create_table(
        'product_groups',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=500), nullable=False),
        sa.Column('slug', sa.String(length=250), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('brand_id', sa.Integer(), nullable=False),
        sa.Column('category_id', sa.Integer(), nullable=False),
        sa.Column('primary_supplement_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['brand_id'], ['brands.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['category_id'], ['categories.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['primary_supplement_id'], ['supplements.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('product_groups', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_product_groups_name'), ['name'], unique=False)
        batch_op.create_index(batch_op.f('ix_product_groups_slug'), ['slug'], unique=True)
        batch_op.create_index(batch_op.f('ix_product_groups_brand_id'), ['brand_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_product_groups_category_id'), ['category_id'], unique=False)

    with op.batch_alter_table('supplements', schema=None) as batch_op:
        batch_op.add_column(sa.Column('product_group_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('variant_label', sa.String(length=200), nullable=True))
        batch_op.create_foreign_key(
            'fk_supplements_product_group_id',
            'product_groups',
            ['product_group_id'], ['id'],
            ondelete='SET NULL',
        )
        batch_op.create_index(
            batch_op.f('ix_supplements_product_group_id'),
            ['product_group_id'],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table('supplements', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_supplements_product_group_id'))
        batch_op.drop_constraint('fk_supplements_product_group_id', type_='foreignkey')
        batch_op.drop_column('variant_label')
        batch_op.drop_column('product_group_id')

    with op.batch_alter_table('product_groups', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_product_groups_category_id'))
        batch_op.drop_index(batch_op.f('ix_product_groups_brand_id'))
        batch_op.drop_index(batch_op.f('ix_product_groups_slug'))
        batch_op.drop_index(batch_op.f('ix_product_groups_name'))

    op.drop_table('product_groups')
