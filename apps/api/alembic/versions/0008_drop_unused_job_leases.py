"""drop the never-used job_leases table

A lease table was modelled and migrated for worker reliability but never read or
written by any code path. That concern is handled in Redis instead: the worker
claims a job with BLMOVE into a per-worker in-flight list and releases it only once
the job settles, so an interrupted job is reclaimed on restart.

Verified empty before writing this migration. The downgrade recreates the table
exactly as migration 0002 defined it, so the change is reversible.

Revision ID: 0008_drop_unused_job_leases
Revises: 0007_index_metadata_parity
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0008_drop_unused_job_leases"
down_revision: str | None = "0007_index_metadata_parity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("job_leases")


def downgrade() -> None:
    op.create_table(
        "job_leases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "research_task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("research_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("worker_id", sa.String(128), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active", sa.Boolean, nullable=False),
    )
    op.create_index("ix_job_leases_workspace_id", "job_leases", ["workspace_id"])
    op.create_index("ix_job_leases_expires_at", "job_leases", ["expires_at"])
    op.create_index(
        "ix_job_leases_research_task_id", "job_leases", ["research_task_id"]
    )
