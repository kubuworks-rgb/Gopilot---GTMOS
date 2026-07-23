from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class ClaimStatus(StrEnum):
    SUPPORTED = "supported"
    PARTIAL = "partially_supported"
    HYPOTHESIS = "hypothesis"
    CONTRADICTED = "contradicted"


class Workspace(BaseModel):
    id: str
    name: str
    created_at: datetime = Field(default_factory=utc_now)


class ProductProfileInput(BaseModel):
    company_name: str = Field(min_length=2, max_length=120)
    website: str = Field(default="https://kubu.example", max_length=300)
    product: str = Field(min_length=5, max_length=500)
    target_market: str = Field(min_length=5, max_length=500)


class ProductProfile(ProductProfileInput):
    id: str
    workspace_id: str
    status: Literal["draft", "confirmed"] = "confirmed"
    created_at: datetime = Field(default_factory=utc_now)


class SourceDocument(BaseModel):
    id: str
    workspace_id: str
    platform: str
    source_type: str
    backend: str
    url: HttpUrl
    canonical_url: HttpUrl
    title: str
    published_at: datetime | None = None
    retrieved_at: datetime = Field(default_factory=utc_now)
    permission_classification: str = "public"
    trust_score: float = Field(ge=0, le=1)
    demo_data: bool = True


class EvidenceFact(BaseModel):
    id: str
    workspace_id: str
    source_id: str
    passage: str
    claim: str
    confidence: float = Field(ge=0, le=1)
    status: ClaimStatus
    observed_at: datetime


class Finding(BaseModel):
    id: str
    category: Literal["market", "competitor", "pain_point", "buying_trigger"]
    claim: str
    confidence: float = Field(ge=0, le=1)
    status: ClaimStatus
    evidence_ids: list[str]

    @model_validator(mode="after")
    def evidence_or_hypothesis(self) -> "Finding":
        if self.status != ClaimStatus.HYPOTHESIS and not self.evidence_ids:
            raise ValueError("Supported findings require evidence IDs")
        return self


class ResearchRun(BaseModel):
    id: str
    workspace_id: str
    product_id: str
    status: Literal["queued", "running", "awaiting_icp", "completed", "partial", "failed"]
    current_stage: str
    started_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    error: str | None = None
    searches_used: int = 0
    documents_used: int = 0
    findings: list[Finding] = Field(default_factory=list)


class ICP(BaseModel):
    id: str
    workspace_id: str
    research_run_id: str
    name: str
    description: str
    firmographics: list[str]
    pains: list[str]
    triggers: list[str]
    rationale: str
    evidence_ids: list[str]
    selected: bool = False


class Signal(BaseModel):
    id: str
    signal_type: str
    description: str
    observed_at: datetime
    strength: float = Field(ge=0, le=1)
    evidence_ids: list[str]


class ScoreComponent(BaseModel):
    label: str
    value: float
    weight: float
    contribution: float
    evidence_ids: list[str] = Field(default_factory=list)


class ScoreBreakdown(BaseModel):
    score: int = Field(ge=0, le=100)
    components: list[ScoreComponent]


class AccountScores(BaseModel):
    fit: ScoreBreakdown
    intent: ScoreBreakdown
    confidence: ScoreBreakdown
    priority: int = Field(ge=0, le=100)


class Account(BaseModel):
    id: str
    workspace_id: str
    icp_id: str
    name: str
    domain: str
    industry: str
    location: str
    employee_band: str
    scores: AccountScores
    top_signal: str
    recommended_action: str
    last_researched_at: datetime


class EvidenceClaim(BaseModel):
    statement: str
    status: ClaimStatus
    confidence: float = Field(ge=0, le=1)
    evidence_ids: list[str]


class CampaignDraft(BaseModel):
    id: str
    account_id: str
    subject: str
    body: str
    status: Literal["draft", "approved", "rejected"] = "draft"
    evidence_ids: list[str]
    updated_at: datetime = Field(default_factory=utc_now)


class AccountOpportunityBrief(BaseModel):
    account: Account
    why_it_fits: list[EvidenceClaim]
    why_now: list[EvidenceClaim]
    pain_hypotheses: list[EvidenceClaim]
    recommended_problem: str
    recommended_offer: str
    recommended_action: str
    risks: list[str]
    evidence: list[EvidenceFact]
    sources: list[SourceDocument]
    signals: list[Signal]
    campaign: CampaignDraft
    generated_at: datetime = Field(default_factory=utc_now)


class AuditEvent(BaseModel):
    id: str
    workspace_id: str
    actor_id: str
    event_type: str
    target_type: str
    target_id: str
    occurred_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, str] = Field(default_factory=dict)


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)


class CampaignUpdate(BaseModel):
    action: Literal["approve", "reject", "edit"]
    subject: str | None = Field(default=None, max_length=200)
    body: str | None = Field(default=None, max_length=5000)
