from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class WorkspaceRow(Base):
    __tablename__ = "workspaces"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MembershipRow(Base):
    __tablename__ = "memberships"
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    role: Mapped[str] = mapped_column(String(32), default="member")


class TenantRecord(Base):
    __abstract__ = True
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ProductProfileRow(TenantRecord):
    __tablename__ = "product_profiles"
    company_name: Mapped[str] = mapped_column(String(120))
    website: Mapped[str] = mapped_column(String(500))
    product: Mapped[str] = mapped_column(Text)
    target_market: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32))
    profile_data: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)


class ResearchRunRow(TenantRecord):
    __tablename__ = "research_runs"
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("product_profiles.id"))
    status: Mapped[str] = mapped_column(String(32), index=True)
    current_stage: Mapped[str] = mapped_column(String(64))
    budgets: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    error: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    searches_used: Mapped[int] = mapped_column(Integer, default=0)
    documents_used: Mapped[int] = mapped_column(Integer, default=0)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ResearchTaskRow(TenantRecord):
    __tablename__ = "research_tasks"
    research_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_runs.id", ondelete="CASCADE"), index=True
    )
    task_type: Mapped[str] = mapped_column(String(64))
    query: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), index=True)
    source_strategy: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    result_summary: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    error: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ResearchCandidateRow(TenantRecord):
    __tablename__ = "research_candidates"
    research_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_runs.id", ondelete="CASCADE"), index=True
    )
    discovered_url: Mapped[str] = mapped_column(Text)
    hostname: Mapped[str] = mapped_column(String(255))
    registrable_domain: Mapped[str] = mapped_column(String(255), index=True)
    canonical_company_domain: Mapped[str | None] = mapped_column(String(255))
    page_role: Mapped[str] = mapped_column(String(48))
    candidate_score: Mapped[int] = mapped_column(Integer)
    stage: Mapped[str] = mapped_column(String(32), index=True)
    query_provenance: Mapped[list[str]] = mapped_column(JSONB, default=list)
    provider_provenance: Mapped[list[str]] = mapped_column(JSONB, default=list)
    diagnostics: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    __table_args__ = (
        Index(
            "uq_candidate_run_domain",
            "research_run_id",
            "registrable_domain",
            unique=True,
        ),
    )


class SourceDocumentRow(TenantRecord):
    __tablename__ = "source_documents"
    research_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_runs.id", ondelete="CASCADE"), index=True
    )
    platform: Mapped[str] = mapped_column(String(32))
    source_type: Mapped[str] = mapped_column(String(64))
    backend: Mapped[str] = mapped_column(String(64))
    url: Mapped[str] = mapped_column(Text)
    canonical_url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(String(255))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    language: Mapped[str | None] = mapped_column(String(16))
    content_hash: Mapped[str] = mapped_column(String(64))
    cleaned_text: Mapped[str] = mapped_column(Text)
    raw_storage_key: Mapped[str | None] = mapped_column(Text)
    trust_score: Mapped[float] = mapped_column(Float, default=0.5)
    permission_classification: Mapped[str] = mapped_column(String(32), default="public")
    status: Mapped[str] = mapped_column(String(32), default="retrieved")
    provenance: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    source_metadata: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    __table_args__ = (
        Index(
            "uq_source_run_hash",
            "research_run_id",
            "content_hash",
            "canonical_url",
            unique=True,
        ),
        Index("ix_source_documents_canonical_url", "canonical_url"),
    )


class SourceChunkRow(TenantRecord):
    __tablename__ = "source_chunks"
    source_document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_documents.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    token_estimate: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[list[float] | None] = mapped_column(JSONB)
    __table_args__ = (
        # A UniqueConstraint, matching migration 0002, which creates it inline in
        # create_table. PostgreSQL backs it with a unique index of the same name,
        # so this is equivalent to Index(..., unique=True) at runtime -- but
        # `alembic check` compares object kinds, and declaring the index form
        # made it report drift against a database that was already correct.
        UniqueConstraint(
            "source_document_id", "ordinal", name="uq_source_chunk_ordinal"
        ),
    )


class EvidenceFactRow(TenantRecord):
    __tablename__ = "evidence_facts"
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_documents.id", ondelete="CASCADE"), index=True
    )
    subject: Mapped[str | None] = mapped_column(Text)
    predicate: Mapped[str | None] = mapped_column(Text)
    object: Mapped[str | None] = mapped_column(Text)
    claim: Mapped[str] = mapped_column(Text)
    passage: Mapped[str] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(32), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GTMFindingRow(TenantRecord):
    __tablename__ = "gtm_findings"
    research_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_runs.id", ondelete="CASCADE"), index=True
    )
    category: Mapped[str] = mapped_column(String(64))
    claim: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32))
    evidence_ids: Mapped[list[str]] = mapped_column(JSONB)


class ICPRow(TenantRecord):
    """Published MVP table retained for migration compatibility."""

    __tablename__ = "icps"
    research_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_runs.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(120))
    definition: Mapped[dict[str, object]] = mapped_column(JSONB)
    selected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ICPProfileRow(TenantRecord):
    __tablename__ = "icp_profiles"
    research_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_runs.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text)
    definition: Mapped[dict[str, object]] = mapped_column(JSONB)
    confidence: Mapped[float] = mapped_column(Float)
    evidence_ids: Mapped[list[str]] = mapped_column(JSONB)
    selected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AccountRow(TenantRecord):
    __tablename__ = "accounts"
    icp_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("icps.id"))
    icp_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("icp_profiles.id")
    )
    name: Mapped[str] = mapped_column(String(180))
    domain: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    industry: Mapped[str | None] = mapped_column(String(120))
    location: Mapped[str | None] = mapped_column(String(120))
    employee_band: Mapped[str | None] = mapped_column(String(64))
    business_model: Mapped[str | None] = mapped_column(String(120))
    attributes: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    evidence_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    last_researched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        Index("uq_account_workspace_domain", "workspace_id", "domain", unique=True),
    )


class AccountResearchSnapshotRow(TenantRecord):
    __tablename__ = "account_research_snapshots"
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    research_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_runs.id", ondelete="CASCADE"), index=True
    )
    summary: Mapped[dict[str, object]] = mapped_column(JSONB)
    source_ids: Mapped[list[str]] = mapped_column(JSONB)
    evidence_ids: Mapped[list[str]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(32))


class SignalRow(TenantRecord):
    """Published MVP table retained for migration compatibility."""

    __tablename__ = "signals"
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    signal_type: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    strength: Mapped[str] = mapped_column(String(8))
    evidence_ids: Mapped[list[str]] = mapped_column(JSONB)


class IntentSignalRow(TenantRecord):
    __tablename__ = "intent_signals"
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    signal_type: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    base_strength: Mapped[float] = mapped_column(Float)
    relevance: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    adjusted_strength: Mapped[float] = mapped_column(Float)
    evidence_ids: Mapped[list[str]] = mapped_column(JSONB)


class ScoreSnapshotRow(TenantRecord):
    """Published MVP table retained for migration compatibility."""

    __tablename__ = "score_snapshots"
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    scores: Mapped[dict[str, object]] = mapped_column(JSONB)
    policy_version: Mapped[str] = mapped_column(String(32))


class AccountScoreSnapshotRow(TenantRecord):
    __tablename__ = "account_score_snapshots"
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    research_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_runs.id", ondelete="CASCADE"), index=True
    )
    scoring_version: Mapped[str] = mapped_column(String(32))
    scores: Mapped[dict[str, object]] = mapped_column(JSONB)
    weights: Mapped[dict[str, object]] = mapped_column(JSONB)
    inputs: Mapped[dict[str, object]] = mapped_column(JSONB)


class AccountScoreFactorRow(TenantRecord):
    __tablename__ = "account_score_factors"
    score_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("account_score_snapshots.id", ondelete="CASCADE"), index=True
    )
    factor_type: Mapped[str] = mapped_column(String(32))
    label: Mapped[str] = mapped_column(String(120))
    value: Mapped[float] = mapped_column(Float)
    weight: Mapped[float] = mapped_column(Float)
    contribution: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text)
    evidence_ids: Mapped[list[str]] = mapped_column(JSONB)


class OpportunityBriefRow(TenantRecord):
    __tablename__ = "opportunity_briefs"
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    research_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_runs.id", ondelete="CASCADE"), index=True
    )
    payload: Mapped[dict[str, object]] = mapped_column(JSONB)
    evidence_ids: Mapped[list[str]] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, default=1)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CampaignRow(TenantRecord):
    """Published MVP table retained for migration compatibility."""

    __tablename__ = "campaigns"
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    subject: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32))
    evidence_ids: Mapped[list[str]] = mapped_column(JSONB)


class CampaignDraftRow(TenantRecord):
    __tablename__ = "campaign_drafts"
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    opportunity_brief_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("opportunity_briefs.id", ondelete="CASCADE"), index=True
    )
    subject: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), index=True)
    evidence_ids: Mapped[list[str]] = mapped_column(JSONB)
    risk_flags: Mapped[list[str]] = mapped_column(JSONB, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ApprovalRequestRow(TenantRecord):
    __tablename__ = "approval_requests"
    campaign_draft_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("campaign_drafts.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(32), index=True)
    requested_by: Mapped[str] = mapped_column(String(128))
    decided_by: Mapped[str | None] = mapped_column(String(128))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentRunRow(TenantRecord):
    __tablename__ = "agent_runs"
    research_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("research_runs.id", ondelete="CASCADE"), index=True
    )
    agent_name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(32), index=True)
    input_summary: Mapped[dict[str, object]] = mapped_column(JSONB)
    output_summary: Mapped[dict[str, object]] = mapped_column(JSONB)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_category: Mapped[str | None] = mapped_column(String(64))


class ToolCallRow(TenantRecord):
    __tablename__ = "tool_calls"
    research_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("research_runs.id", ondelete="CASCADE"), index=True
    )
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), index=True
    )
    tool: Mapped[str] = mapped_column(String(120))
    adapter: Mapped[str] = mapped_column(String(120))
    backend: Mapped[str | None] = mapped_column(String(120))
    input_summary: Mapped[dict[str, object]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(32), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error_category: Mapped[str | None] = mapped_column(String(64))


class AuditEventRow(TenantRecord):
    __tablename__ = "audit_events"
    actor_id: Mapped[str] = mapped_column(String(128))
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str] = mapped_column(String(64))
    target_id: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)


class FeedbackEventRow(TenantRecord):
    __tablename__ = "feedback_events"
    actor_id: Mapped[str] = mapped_column(String(128))
    target_type: Mapped[str] = mapped_column(String(32), index=True)
    target_id: Mapped[str] = mapped_column(String(128), index=True)
    rating: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)


class QAEvaluationRow(TenantRecord):
    __tablename__ = "qa_evaluations"
    research_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_runs.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    evaluator_id: Mapped[str] = mapped_column(String(128))
    company_validity: Mapped[str] = mapped_column(String(32))
    domain_correctness: Mapped[str] = mapped_column(String(32))
    icp_relevance: Mapped[int] = mapped_column(Integer)
    evidence_correctness: Mapped[str] = mapped_column(String(32))
    signal_relevance: Mapped[int] = mapped_column(Integer)
    brief_usefulness: Mapped[int] = mapped_column(Integer)
    evidence_links_working: Mapped[bool] = mapped_column(Boolean)
    unsupported_important_claim: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)


# JobLeaseRow was removed in migration 0008. A lease table was modelled for worker
# reliability but never read or written: the worker claims jobs with Redis BLMOVE
# into a per-worker in-flight list instead, which is where that concern actually
# lives.
