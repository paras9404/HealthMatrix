"""add admin_users and admin_audit_logs tables

Revision ID: c1a2b3d4e5f6
Revises: 8fc48c056c61
Create Date: 2026-05-03 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "c1a2b3d4e5f6"
down_revision = "8fc48c056c61"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "admin_users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=80), nullable=False),
        sa.Column("email", sa.String(length=160), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="readonly"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "role IN ('readonly', 'editor', 'superadmin')",
            name="ck_admin_user_role",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("admin_users", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_admin_users_username"), ["username"], unique=True)
        batch_op.create_index(batch_op.f("ix_admin_users_email"), ["email"], unique=True)
        batch_op.create_index(batch_op.f("ix_admin_users_is_active"), ["is_active"], unique=False)

    op.create_table(
        "admin_audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("admin_user_id", sa.Integer(), nullable=True),
        sa.Column("admin_username", sa.String(length=80), nullable=True),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("entity_type", sa.String(length=40), nullable=True),
        sa.Column("entity_id", sa.String(length=40), nullable=True),
        sa.Column("summary", sa.String(length=255), nullable=True),
        sa.Column(
            "changes",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["admin_user_id"], ["admin_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("admin_audit_logs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_admin_audit_logs_admin_user_id"), ["admin_user_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_admin_audit_logs_admin_username"), ["admin_username"], unique=False)
        batch_op.create_index(batch_op.f("ix_admin_audit_logs_action"), ["action"], unique=False)
        batch_op.create_index(batch_op.f("ix_admin_audit_logs_entity_type"), ["entity_type"], unique=False)
        batch_op.create_index(batch_op.f("ix_admin_audit_logs_entity_id"), ["entity_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_admin_audit_logs_created_at"), ["created_at"], unique=False)


def downgrade():
    with op.batch_alter_table("admin_audit_logs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_admin_audit_logs_created_at"))
        batch_op.drop_index(batch_op.f("ix_admin_audit_logs_entity_id"))
        batch_op.drop_index(batch_op.f("ix_admin_audit_logs_entity_type"))
        batch_op.drop_index(batch_op.f("ix_admin_audit_logs_action"))
        batch_op.drop_index(batch_op.f("ix_admin_audit_logs_admin_username"))
        batch_op.drop_index(batch_op.f("ix_admin_audit_logs_admin_user_id"))
    op.drop_table("admin_audit_logs")

    with op.batch_alter_table("admin_users", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_admin_users_is_active"))
        batch_op.drop_index(batch_op.f("ix_admin_users_email"))
        batch_op.drop_index(batch_op.f("ix_admin_users_username"))
    op.drop_table("admin_users")
