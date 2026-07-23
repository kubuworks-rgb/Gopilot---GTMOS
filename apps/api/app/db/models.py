from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class WorkspaceRow(Base):
    __tablename__ = "workspaces"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MembershipRow(Base):
    __tablename__ = "memberships"
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    role: Mapped[str] = mapped_column(String(32), default="member")


class TenantRecord(Base):
    __abstract__ = True
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProductProfileRow(TenantRecord):
    __tablename__ = "product_profiles"
    company_name: Mapped[str] = mapped_column(String(120))
    website: Mapped[str] = mapped_column(String(500))
    product: Mapped[str] = mapped_column(Text)
    target_market: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32))


class ResearchRunRow(TenantRecord):
    __tablename__ = "research_runs"
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("product_profiles.id"))
    status: Mapped[str] = mapped_column(String(32), index=True)
    current_stage: Mapped[str] = mapped_column(String(64))
    budgets: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    error: Mapped[dict[str, object] | None] = mapped_column(JSONB)


class SourceDocumentRow(TenantRecord):
    __tablename__ = "source_documents"
    research_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("research_runs.id", ondelete="CASCADE"))
    platform: Mapped[str] = mapped_column(String(32))
    source_type: Mapped[str] = mapped_column(String(64))
    backend: Mapped[str] = mapped_column(String(64))
    url: Mapped[str] = mapped_column(Text)
    canonical_url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    cleaned_text: Mapped[str] = mapped_column(Text)
    provenance: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    __table_args__ = (Index("uq_source_workspace_hash", "workspace_id", "content_hash", unique=True),)


class EvidenceFactRow(TenantRecord):
    __tablename__ = "evidence_facts"
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_documents.id", ondelete="CASCADE"), index=True)
    claim: Mapped[str] = mapped_column(Text)
    passage: Mapped[str] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(32))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ICPRow(TenantRecord):
    __tablename__ = "icps"
    research_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("research_runs.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    definition: Mapped[dict[str, object]] = mapped_column(JSONB)
    selected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AccountRow(TenantRecord):
    __tablename__ = "accounts"
    icp_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("icps.id"))
    name: Mapped[str] = mapped_column(String(180))
    domain: Mapped[str] = mapped_column(String(255))
    attributes: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    __table_args__ = (Index("uq_account_workspace_domain", "workspace_id", "domain", unique=True),)


class SignalRow(TenantRecord):
    __tablename__ = "signals"
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    signal_type: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    strength: Mapped[str] = mapped_column(String(8))
    evidence_ids: Mapped[list[str]] = mapped_column(JSONB)


class ScoreSnapshotRow(TenantRecord):
    __tablename__ = "score_snapshots"
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    scores: Mapped[dict[str, object]] = mapped_column(JSONB)
    policy_version: Mapped[str] = mapped_column(String(32))


class CampaignRow(TenantRecord):
    __tablename__ = "campaigns"
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    subject: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32))
    evidence_ids: Mapped[list[str]] = mapped_column(JSONB)


class AuditEventRow(TenantRecord):
    __tablename__ = "audit_events"
    actor_id: Mapped[str] = mapped_column(String(128))
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str] = mapped_column(String(64))
    target_id: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
