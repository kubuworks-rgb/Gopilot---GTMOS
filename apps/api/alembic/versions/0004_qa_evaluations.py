"""add persisted account quality evaluations

Revision ID: 0004_qa_evaluations
Revises: 0003_real_gtm_intelligence
Create Date: 2026-07-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0004_qa_evaluations"
down_revision: str | None = "0003_real_gtm_intelligence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "qa_evaluations",
        sa.Column("research_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evaluator_id", sa.String(length=128), nullable=False),
        sa.Column("company_validity", sa.String(length=32), nullable=False),
        sa.Column("domain_correctness", sa.String(length=32), nullable=False),
        sa.Column("icp_relevance", sa.Integer(), nullable=False),
        sa.Column("evidence_correctness", sa.String(length=32), nullable=False),
        sa.Column("signal_relevance", sa.Integer(), nullable=False),
        sa.Column("brief_usefulness", sa.Integer(), nullable=False),
        sa.Column("evidence_links_working", sa.Boolean(), nullable=False),
        sa.Column(
            "unsupported_important_claim",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["research_run_id"], ["research_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_qa_evaluations_workspace_id",
        "qa_evaluations",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_qa_evaluations_research_run_id",
        "qa_evaluations",
        ["research_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_qa_evaluations_account_id",
        "qa_evaluations",
        ["account_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_qa_evaluations_account_id", table_name="qa_evaluations")
    op.drop_index("ix_qa_evaluations_research_run_id", table_name="qa_evaluations")
    op.drop_index("ix_qa_evaluations_workspace_id", table_name="qa_evaluations")
    op.drop_table("qa_evaluations")
