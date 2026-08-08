"""create the indexes declared on the models but never migrated

Closes the long-standing `alembic check` drift. The drift was purely additive and
one-directional: 21 foreign-key and status lookup indexes were declared in
SQLAlchemy metadata with no migration creating them. There were no column,
uniqueness, or table disagreements, so nothing here corrects an earlier migration —
this only backfills performance indexes.

Deliberately excluded: `uq_source_chunk_ordinal`. The models declare it as a unique
`Index`, but migration 0002 already creates it as a `UniqueConstraint` inside
`create_table`, and PostgreSQL backs that with a unique index of the same name. The
invariant has always been enforced; recreating it here would be redundant.

Revision ID: 0007_index_metadata_parity
Revises: 0006_intelligence_quality
Create Date: 2026-08-08
"""

from collections.abc import Sequence

from alembic import op


revision: str = "0007_index_metadata_parity"
down_revision: str | None = "0006_intelligence_quality"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (index name, table, columns)
SECONDARY_INDEXES: tuple[tuple[str, str, str], ...] = (
    (
        "ix_account_research_snapshots_research_run_id",
        "account_research_snapshots",
        "research_run_id",
    ),
    (
        "ix_account_score_factors_score_snapshot_id",
        "account_score_factors",
        "score_snapshot_id",
    ),
    (
        "ix_account_score_snapshots_research_run_id",
        "account_score_snapshots",
        "research_run_id",
    ),
    ("ix_agent_runs_research_run_id", "agent_runs", "research_run_id"),
    ("ix_agent_runs_status", "agent_runs", "status"),
    (
        "ix_approval_requests_campaign_draft_id",
        "approval_requests",
        "campaign_draft_id",
    ),
    ("ix_approval_requests_status", "approval_requests", "status"),
    ("ix_audit_events_event_type", "audit_events", "event_type"),
    (
        "ix_campaign_drafts_opportunity_brief_id",
        "campaign_drafts",
        "opportunity_brief_id",
    ),
    ("ix_campaign_drafts_status", "campaign_drafts", "status"),
    ("ix_campaigns_account_id", "campaigns", "account_id"),
    ("ix_evidence_facts_source_id", "evidence_facts", "source_id"),
    ("ix_job_leases_research_task_id", "job_leases", "research_task_id"),
    (
        "ix_opportunity_briefs_research_run_id",
        "opportunity_briefs",
        "research_run_id",
    ),
    ("ix_research_runs_status", "research_runs", "status"),
    ("ix_score_snapshots_account_id", "score_snapshots", "account_id"),
    ("ix_signals_account_id", "signals", "account_id"),
    ("ix_source_documents_workspace_id", "source_documents", "workspace_id"),
    ("ix_tool_calls_agent_run_id", "tool_calls", "agent_run_id"),
    ("ix_tool_calls_research_run_id", "tool_calls", "research_run_id"),
    ("ix_tool_calls_status", "tool_calls", "status"),
)


def upgrade() -> None:
    for name, table, column in SECONDARY_INDEXES:
        op.create_index(name, table, [column], if_not_exists=True)


def downgrade() -> None:
    for name, table, _column in reversed(SECONDARY_INDEXES):
        op.drop_index(name, table_name=table, if_exists=True)
