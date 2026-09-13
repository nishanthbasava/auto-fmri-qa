"""users, decisions (append-only), audit_events (append-only)

Revision ID: 0001
Revises:
Create Date: 2026-09-13
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(16), nullable=False, server_default="viewer"),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    op.create_table(
        "decisions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("run_id", sa.String(128), nullable=False),
        sa.Column("scan_key", sa.String(128), nullable=False),
        sa.Column("decision", sa.String(8), nullable=False),
        sa.Column("note", sa.Text, nullable=False, server_default=""),
        sa.Column("status_at_decision", sa.String(16), nullable=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_decisions_run_id", "decisions", ["run_id"])
    op.create_index("ix_decisions_run_scan", "decisions", ["run_id", "scan_key"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(64), nullable=True),
        sa.Column("action", sa.String(48), nullable=False),
        sa.Column("target", sa.String(256), nullable=True),
        sa.Column("detail", JSONType, nullable=True),
        sa.Column("ip", sa.String(64), nullable=True),
    )
    for col in ("ts", "actor", "action", "target"):
        op.create_index(f"ix_audit_events_{col}", "audit_events", [col])

    # Append-only tables: on Postgres, take UPDATE/DELETE away from the app role
    # at the database level so the audit trail cannot be rewritten by the API.
    if op.get_bind().dialect.name == "postgresql":
        op.execute("REVOKE UPDATE, DELETE ON decisions, audit_events FROM PUBLIC")


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("decisions")
    op.drop_table("users")
