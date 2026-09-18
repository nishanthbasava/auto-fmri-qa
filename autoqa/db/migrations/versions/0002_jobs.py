"""jobs: background job status that survives an API restart

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-18
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("run_id", sa.String(128), nullable=False),
        sa.Column("phase", sa.String(32), nullable=False, server_default="starting"),
        sa.Column("returncode", sa.Integer, nullable=True),
        sa.Column("host_pid", sa.Integer, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_jobs_run_id", "jobs", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_jobs_run_id", table_name="jobs")
    op.drop_table("jobs")
