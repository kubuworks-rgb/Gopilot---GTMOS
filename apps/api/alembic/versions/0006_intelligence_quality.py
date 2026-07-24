"""persist two-stage candidate provenance

Revision ID: 0006_intelligence_quality
Revises: 0005_source_provenance_identity
Create Date: 2026-07-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0006_intelligence_quality"
down_revision: str | None = "0005_source_provenance_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_candidates",
        sa.Column("research_run_id", sa.UUID(), nullable=False),
        sa.Column("discovered_url", sa.Text(), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column("registrable_domain", sa.String(length=255), nullable=False),
        sa.Column("canonical_company_domain", sa.String(length=255), nullable=True),
        sa.Column("page_role", sa.String(length=48), nullable=False),
        sa.Column("candidate_score", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column(
            "query_provenance",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "provider_provenance",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "diagnostics",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["research_run_id"], ["research_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_research_candidates_research_run_id",
        "research_candidates",
        ["research_run_id"],
    )
    op.create_index(
        "ix_research_candidates_registrable_domain",
        "research_candidates",
        ["registrable_domain"],
    )
    op.create_index(
        "ix_research_candidates_stage", "research_candidates", ["stage"]
    )
    op.create_index(
        "ix_research_candidates_workspace_id",
        "research_candidates",
        ["workspace_id"],
    )
    op.create_index(
        "uq_candidate_run_domain",
        "research_candidates",
        ["research_run_id", "registrable_domain"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_candidate_run_domain", table_name="research_candidates")
    op.drop_index(
        "ix_research_candidates_workspace_id", table_name="research_candidates"
    )
    op.drop_index("ix_research_candidates_stage", table_name="research_candidates")
    op.drop_index(
        "ix_research_candidates_registrable_domain",
        table_name="research_candidates",
    )
    op.drop_index(
        "ix_research_candidates_research_run_id", table_name="research_candidates"
    )
    op.drop_table("research_candidates")
