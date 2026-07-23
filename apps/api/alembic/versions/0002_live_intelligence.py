"""Add durable live research, evidence, account, and observability records."""

from collections.abc import Sequence
from typing import Any

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0002_live_intelligence"
down_revision = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def tenant_columns() -> list[sa.Column]:
    return [
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
    ]


def workspace_index(table: str) -> None:
    op.create_index(f"ix_{table}_workspace_id", table, ["workspace_id"])


def upgrade() -> None:
    op.add_column(
        "product_profiles",
        sa.Column(
            "profile_data",
            postgresql.JSONB,
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    for column in (
        sa.Column("trace_id", sa.String(64), server_default="", nullable=False),
        sa.Column("searches_used", sa.Integer, server_default="0", nullable=False),
        sa.Column("documents_used", sa.Integer, server_default="0", nullable=False),
        sa.Column("evidence_count", sa.Integer, server_default="0", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    ):
        op.add_column("research_runs", column)
    op.create_index("ix_research_runs_trace_id", "research_runs", ["trace_id"])

    op.create_table(
        "research_tasks",
        *tenant_columns(),
        sa.Column(
            "research_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("research_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("task_type", sa.String(64), nullable=False),
        sa.Column("query", sa.Text),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "source_strategy",
            postgresql.JSONB,
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "result_summary",
            postgresql.JSONB,
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("error", postgresql.JSONB),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    workspace_index("research_tasks")
    op.create_index("ix_research_tasks_research_run_id", "research_tasks", ["research_run_id"])
    op.create_index("ix_research_tasks_status", "research_tasks", ["status"])

    source_columns: Sequence[sa.Column[Any]] = (
        sa.Column("author", sa.String(255)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column(
            "retrieved_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("language", sa.String(16)),
        sa.Column("raw_storage_key", sa.Text),
        sa.Column("trust_score", sa.Float, server_default="0.5", nullable=False),
        sa.Column(
            "permission_classification",
            sa.String(32),
            server_default="public",
            nullable=False,
        ),
        sa.Column("status", sa.String(32), server_default="retrieved", nullable=False),
        sa.Column(
            "source_metadata",
            postgresql.JSONB,
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    for column in source_columns:
        op.add_column("source_documents", column)
    op.drop_index("uq_source_workspace_hash", table_name="source_documents")
    op.create_index(
        "uq_source_run_hash",
        "source_documents",
        ["research_run_id", "content_hash"],
        unique=True,
    )
    op.create_index(
        "ix_source_documents_research_run_id", "source_documents", ["research_run_id"]
    )
    op.create_index(
        "ix_source_documents_canonical_url", "source_documents", ["canonical_url"]
    )

    op.create_table(
        "source_chunks",
        *tenant_columns(),
        sa.Column(
            "source_document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("source_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("token_estimate", sa.Integer, nullable=False),
        sa.Column("embedding", postgresql.JSONB),
        sa.UniqueConstraint(
            "source_document_id", "ordinal", name="uq_source_chunk_ordinal"
        ),
    )
    workspace_index("source_chunks")
    op.create_index(
        "ix_source_chunks_source_document_id", "source_chunks", ["source_document_id"]
    )

    for column in (
        sa.Column("subject", sa.Text),
        sa.Column("predicate", sa.Text),
        sa.Column("object", sa.Text),
        sa.Column("valid_from", sa.DateTime(timezone=True)),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
    ):
        op.add_column("evidence_facts", column)
    op.create_index("ix_evidence_facts_status", "evidence_facts", ["status"])
    op.create_index("ix_evidence_facts_observed_at", "evidence_facts", ["observed_at"])

    op.create_table(
        "gtm_findings",
        *tenant_columns(),
        sa.Column(
            "research_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("research_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("claim", sa.Text, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("evidence_ids", postgresql.JSONB, nullable=False),
    )
    workspace_index("gtm_findings")
    op.create_index("ix_gtm_findings_research_run_id", "gtm_findings", ["research_run_id"])

    op.create_table(
        "icp_profiles",
        *tenant_columns(),
        sa.Column(
            "research_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("research_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("definition", postgresql.JSONB, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("evidence_ids", postgresql.JSONB, nullable=False),
        sa.Column("selected_at", sa.DateTime(timezone=True)),
    )
    workspace_index("icp_profiles")
    op.create_index("ix_icp_profiles_research_run_id", "icp_profiles", ["research_run_id"])

    op.alter_column("accounts", "icp_id", nullable=True)
    op.add_column(
        "accounts",
        sa.Column(
            "icp_profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("icp_profiles.id"),
        ),
    )
    for column in (
        sa.Column("description", sa.Text),
        sa.Column("industry", sa.String(120)),
        sa.Column("location", sa.String(120)),
        sa.Column("employee_band", sa.String(64)),
        sa.Column("business_model", sa.String(120)),
        sa.Column(
            "evidence_ids",
            postgresql.JSONB,
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("last_researched_at", sa.DateTime(timezone=True)),
    ):
        op.add_column("accounts", column)

    op.create_table(
        "account_research_snapshots",
        *tenant_columns(),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "research_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("research_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("summary", postgresql.JSONB, nullable=False),
        sa.Column("source_ids", postgresql.JSONB, nullable=False),
        sa.Column("evidence_ids", postgresql.JSONB, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
    )
    workspace_index("account_research_snapshots")
    op.create_index(
        "ix_account_research_snapshots_account_id",
        "account_research_snapshots",
        ["account_id"],
    )

    op.create_table(
        "intent_signals",
        *tenant_columns(),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("signal_type", sa.String(64), nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("base_strength", sa.Float, nullable=False),
        sa.Column("relevance", sa.Float, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("adjusted_strength", sa.Float, nullable=False),
        sa.Column("evidence_ids", postgresql.JSONB, nullable=False),
    )
    workspace_index("intent_signals")
    op.create_index("ix_intent_signals_account_id", "intent_signals", ["account_id"])
    op.create_index("ix_intent_signals_observed_at", "intent_signals", ["observed_at"])

    op.create_table(
        "account_score_snapshots",
        *tenant_columns(),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "research_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("research_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scoring_version", sa.String(32), nullable=False),
        sa.Column("scores", postgresql.JSONB, nullable=False),
        sa.Column("weights", postgresql.JSONB, nullable=False),
        sa.Column("inputs", postgresql.JSONB, nullable=False),
    )
    workspace_index("account_score_snapshots")
    op.create_index(
        "ix_account_score_snapshots_account_id",
        "account_score_snapshots",
        ["account_id"],
    )

    op.create_table(
        "account_score_factors",
        *tenant_columns(),
        sa.Column(
            "score_snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("account_score_snapshots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("factor_type", sa.String(32), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("value", sa.Float, nullable=False),
        sa.Column("weight", sa.Float, nullable=False),
        sa.Column("contribution", sa.Float, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("evidence_ids", postgresql.JSONB, nullable=False),
    )
    workspace_index("account_score_factors")

    op.create_table(
        "opportunity_briefs",
        *tenant_columns(),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "research_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("research_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("evidence_ids", postgresql.JSONB, nullable=False),
        sa.Column("version", sa.Integer, server_default="1", nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    workspace_index("opportunity_briefs")
    op.create_index("ix_opportunity_briefs_account_id", "opportunity_briefs", ["account_id"])

    op.create_table(
        "campaign_drafts",
        *tenant_columns(),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "opportunity_brief_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("opportunity_briefs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("subject", sa.Text, nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("evidence_ids", postgresql.JSONB, nullable=False),
        sa.Column(
            "risk_flags",
            postgresql.JSONB,
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    workspace_index("campaign_drafts")
    op.create_index("ix_campaign_drafts_account_id", "campaign_drafts", ["account_id"])

    op.create_table(
        "approval_requests",
        *tenant_columns(),
        sa.Column(
            "campaign_draft_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("campaign_drafts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("requested_by", sa.String(128), nullable=False),
        sa.Column("decided_by", sa.String(128)),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
    )
    workspace_index("approval_requests")

    op.create_table(
        "agent_runs",
        *tenant_columns(),
        sa.Column(
            "research_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("research_runs.id", ondelete="CASCADE"),
        ),
        sa.Column("agent_name", sa.String(120), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("input_summary", postgresql.JSONB, nullable=False),
        sa.Column("output_summary", postgresql.JSONB, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error_category", sa.String(64)),
    )
    workspace_index("agent_runs")

    op.create_table(
        "tool_calls",
        *tenant_columns(),
        sa.Column(
            "research_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("research_runs.id", ondelete="CASCADE"),
        ),
        sa.Column(
            "agent_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="SET NULL"),
        ),
        sa.Column("tool", sa.String(120), nullable=False),
        sa.Column("adapter", sa.String(120), nullable=False),
        sa.Column("backend", sa.String(120)),
        sa.Column("input_summary", postgresql.JSONB, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("latency_ms", sa.Integer),
        sa.Column("error_category", sa.String(64)),
    )
    workspace_index("tool_calls")

    op.create_table(
        "job_leases",
        *tenant_columns(),
        sa.Column(
            "research_task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("research_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("worker_id", sa.String(128), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active", sa.Boolean, server_default=sa.true(), nullable=False),
    )
    workspace_index("job_leases")
    op.create_index("ix_job_leases_expires_at", "job_leases", ["expires_at"])


def downgrade() -> None:
    for table in (
        "job_leases",
        "tool_calls",
        "agent_runs",
        "approval_requests",
        "campaign_drafts",
        "opportunity_briefs",
        "account_score_factors",
        "account_score_snapshots",
        "intent_signals",
        "account_research_snapshots",
        "icp_profiles",
        "gtm_findings",
        "source_chunks",
        "research_tasks",
    ):
        op.drop_table(table)

    for column in (
        "last_researched_at",
        "evidence_ids",
        "business_model",
        "employee_band",
        "location",
        "industry",
        "description",
        "icp_profile_id",
    ):
        op.drop_column("accounts", column)
    op.alter_column("accounts", "icp_id", nullable=False)
    op.drop_index("uq_source_run_hash", table_name="source_documents")
    op.create_index(
        "uq_source_workspace_hash",
        "source_documents",
        ["workspace_id", "content_hash"],
        unique=True,
    )

    for column in ("valid_until", "valid_from", "object", "predicate", "subject"):
        op.drop_column("evidence_facts", column)
    for column in (
        "source_metadata",
        "status",
        "permission_classification",
        "trust_score",
        "raw_storage_key",
        "language",
        "retrieved_at",
        "published_at",
        "author",
    ):
        op.drop_column("source_documents", column)
    for column in (
        "completed_at",
        "updated_at",
        "evidence_count",
        "documents_used",
        "searches_used",
        "trace_id",
    ):
        op.drop_column("research_runs", column)
    op.drop_column("product_profiles", "profile_data")
