"""Initial tenant, evidence, account, campaign, and audit schema."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table("workspaces", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("name", sa.String(120), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table("memberships", sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True), sa.Column("user_id", sa.String(128), primary_key=True), sa.Column("role", sa.String(32), nullable=False))
    def tenant_columns() -> list[sa.Column]:
        return [sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)]
    op.create_table("product_profiles", *tenant_columns(), sa.Column("company_name", sa.String(120), nullable=False), sa.Column("website", sa.String(500), nullable=False), sa.Column("product", sa.Text, nullable=False), sa.Column("target_market", sa.Text, nullable=False), sa.Column("status", sa.String(32), nullable=False))
    op.create_index("ix_product_profiles_workspace_id", "product_profiles", ["workspace_id"])
    op.create_table("research_runs", *tenant_columns(), sa.Column("product_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("product_profiles.id"), nullable=False), sa.Column("status", sa.String(32), nullable=False), sa.Column("current_stage", sa.String(64), nullable=False), sa.Column("budgets", postgresql.JSONB, nullable=False), sa.Column("error", postgresql.JSONB))
    op.create_index("ix_research_runs_workspace_id", "research_runs", ["workspace_id"])
    op.create_table("source_documents", *tenant_columns(), sa.Column("research_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("research_runs.id", ondelete="CASCADE"), nullable=False), sa.Column("platform", sa.String(32), nullable=False), sa.Column("source_type", sa.String(64), nullable=False), sa.Column("backend", sa.String(64), nullable=False), sa.Column("url", sa.Text, nullable=False), sa.Column("canonical_url", sa.Text, nullable=False), sa.Column("title", sa.Text, nullable=False), sa.Column("content_hash", sa.String(64), nullable=False), sa.Column("cleaned_text", sa.Text, nullable=False), sa.Column("provenance", postgresql.JSONB, nullable=False))
    op.create_index("uq_source_workspace_hash", "source_documents", ["workspace_id", "content_hash"], unique=True)
    op.create_table("evidence_facts", *tenant_columns(), sa.Column("source_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_documents.id", ondelete="CASCADE"), nullable=False), sa.Column("claim", sa.Text, nullable=False), sa.Column("passage", sa.Text, nullable=False), sa.Column("confidence", sa.String(8), nullable=False), sa.Column("status", sa.String(32), nullable=False), sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("icps", *tenant_columns(), sa.Column("research_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("research_runs.id", ondelete="CASCADE"), nullable=False), sa.Column("name", sa.String(120), nullable=False), sa.Column("definition", postgresql.JSONB, nullable=False), sa.Column("selected_at", sa.DateTime(timezone=True)))
    op.create_table("accounts", *tenant_columns(), sa.Column("icp_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("icps.id"), nullable=False), sa.Column("name", sa.String(180), nullable=False), sa.Column("domain", sa.String(255), nullable=False), sa.Column("attributes", postgresql.JSONB, nullable=False))
    op.create_index("uq_account_workspace_domain", "accounts", ["workspace_id", "domain"], unique=True)
    op.create_table("signals", *tenant_columns(), sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False), sa.Column("signal_type", sa.String(64), nullable=False), sa.Column("description", sa.Text, nullable=False), sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False), sa.Column("strength", sa.String(8), nullable=False), sa.Column("evidence_ids", postgresql.JSONB, nullable=False))
    op.create_table("score_snapshots", *tenant_columns(), sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False), sa.Column("scores", postgresql.JSONB, nullable=False), sa.Column("policy_version", sa.String(32), nullable=False))
    op.create_table("campaigns", *tenant_columns(), sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False), sa.Column("subject", sa.Text, nullable=False), sa.Column("body", sa.Text, nullable=False), sa.Column("status", sa.String(32), nullable=False), sa.Column("evidence_ids", postgresql.JSONB, nullable=False))
    op.create_table("audit_events", *tenant_columns(), sa.Column("actor_id", sa.String(128), nullable=False), sa.Column("event_type", sa.String(64), nullable=False), sa.Column("target_type", sa.String(64), nullable=False), sa.Column("target_id", sa.String(128), nullable=False), sa.Column("payload", postgresql.JSONB, nullable=False))
    for table in ("evidence_facts", "icps", "accounts", "signals", "score_snapshots", "campaigns", "audit_events"):
        op.create_index(f"ix_{table}_workspace_id", table, ["workspace_id"])


def downgrade() -> None:
    for table in ("audit_events", "campaigns", "score_snapshots", "signals", "accounts", "icps", "evidence_facts", "source_documents", "research_runs", "product_profiles", "memberships", "workspaces"):
        op.drop_table(table)
