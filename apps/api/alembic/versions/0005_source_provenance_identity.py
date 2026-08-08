"""preserve source URL identity when content hashes match

Revision ID: 0005_source_provenance_identity
Revises: 0004_qa_evaluations
Create Date: 2026-07-23
"""

from collections.abc import Sequence

from alembic import op


revision: str = "0005_source_provenance_identity"
down_revision: str | None = "0004_qa_evaluations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("uq_source_run_hash", table_name="source_documents")
    op.create_index(
        "uq_source_run_hash",
        "source_documents",
        ["research_run_id", "content_hash", "canonical_url"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_source_run_hash", table_name="source_documents")
    op.create_index(
        "uq_source_run_hash",
        "source_documents",
        ["research_run_id", "content_hash"],
        unique=True,
    )
