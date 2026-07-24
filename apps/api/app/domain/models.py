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


class ProvenanceStatus(StrEnum):
    USER_CONFIRMED = "USER_CONFIRMED"
    SOURCE_SUPPORTED = "SOURCE_SUPPORTED"
    INFERRED = "INFERRED"
    UNKNOWN = "UNKNOWN"


class QualificationStatus(StrEnum):
    QUALIFIED = "QUALIFIED"
    QUALIFIED_WITH_UNCERTAINTY = "QUALIFIED_WITH_UNCERTAINTY"
    BORDERLINE = "BORDERLINE"
    DISQUALIFIED = "DISQUALIFIED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class CompanySizeStatus(StrEnum):
    VERIFIED = "VERIFIED"
    ESTIMATED = "ESTIMATED"
    UNKNOWN = "UNKNOWN"


class ProfileClaim(BaseModel):
    field: str
    value: str | None
    status: ProvenanceStatus
    evidence_ids: list[str] = Field(default_factory=list)
    rationale: str | None = None


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
    understanding: list[ProfileClaim] = Field(default_factory=list)
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
    content_hash: str | None = None
    content_type: str | None = None
    normalized_text_length: int | None = None


class EvidenceFact(BaseModel):
    id: str
    workspace_id: str
    source_id: str
    passage: str
    claim: str
    confidence: float = Field(ge=0, le=1)
    status: ClaimStatus
    observed_at: datetime
    source_chunk_id: str | None = None


class SourceChunk(BaseModel):
    id: str
    source_document_id: str
    ordinal: int
    text: str
    content_hash: str


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
    status: Literal[
        "queued",
        "planning",
        "researching",
        "extracting",
        "awaiting_icp",
        "discovering_accounts",
        "scoring",
        "completed",
        "partial",
        "failed",
    ]
    current_stage: str
    started_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    error: dict[str, object] | None = None
    searches_used: int = 0
    documents_used: int = 0
    findings: list[Finding] = Field(default_factory=list)


class ResearchEvidence(BaseModel):
    run_id: str
    findings: list[Finding]
    evidence: list[EvidenceFact]
    sources: list[SourceDocument]
    chunks: list[SourceChunk]


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
    recommended: bool = False
    qualification_logic: list[str] = Field(default_factory=list)
    criteria_version: str = "legacy"
    criteria: list[dict[str, str]] = Field(default_factory=list)


class Signal(BaseModel):
    id: str
    signal_type: str
    description: str
    observed_at: datetime
    strength: float = Field(ge=0, le=1)
    evidence_ids: list[str]
    entity_match_score: float = Field(default=0, ge=0, le=1)
    event_confidence: float = Field(default=0, ge=0, le=1)
    relevance: float = Field(default=0, ge=0, le=1)
    source_role: str = "OTHER"


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
    qualification_status: QualificationStatus = (
        QualificationStatus.INSUFFICIENT_EVIDENCE
    )
    qualification_reasons: list[str] = Field(default_factory=list)
    company_size_status: CompanySizeStatus = CompanySizeStatus.UNKNOWN
    discovery_source: str | None = None
    domain_validation: str = "UNKNOWN"
    evidence_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    top_signal_type: str | None = None
    registrable_domain: str | None = None
    official_subdomains: list[str] = Field(default_factory=list)
    domain_confidence: float = Field(default=0, ge=0, le=1)
    qualification_coverage: float = Field(default=0, ge=0, le=1)
    priority_band: Literal["HIGH", "MEDIUM", "LOW", "MONITOR"] = "MONITOR"
    research_candidate: bool = True


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
    verified_facts: list[EvidenceClaim] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    research_candidate: bool = True
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


class FeedbackInput(BaseModel):
    target_type: Literal["account", "signal", "finding", "brief"]
    target_id: str = Field(min_length=1, max_length=128)
    rating: Literal[
        "GOOD_ACCOUNT",
        "BAD_ACCOUNT",
        "USEFUL_SIGNAL",
        "IRRELEVANT_SIGNAL",
        "CORRECT",
        "INCORRECT",
        "USEFUL",
        "NOT_USEFUL",
        "NEEDS_REVIEW",
    ]
    reason: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def reason_required_for_negative_feedback(self) -> "FeedbackInput":
        negative = {
            "BAD_ACCOUNT",
            "IRRELEVANT_SIGNAL",
            "INCORRECT",
            "NOT_USEFUL",
            "NEEDS_REVIEW",
        }
        if self.rating in negative and not (self.reason or "").strip():
            raise ValueError("Negative feedback requires a reason")
        return self


class FeedbackRecord(FeedbackInput):
    id: str
    workspace_id: str
    actor_id: str
    created_at: datetime = Field(default_factory=utc_now)


class QAEvaluationInput(BaseModel):
    research_run_id: str
    account_id: str
    company_validity: Literal["REAL", "WRONG_ENTITY", "UNCERTAIN"]
    domain_correctness: Literal["CORRECT", "INCORRECT", "UNCERTAIN"]
    icp_relevance: int = Field(ge=0, le=3)
    evidence_correctness: Literal["SUPPORTED", "PARTIAL", "UNSUPPORTED"]
    signal_relevance: int = Field(ge=0, le=3)
    brief_usefulness: int = Field(ge=0, le=3)
    evidence_links_working: bool
    unsupported_important_claim: bool = False
    notes: str | None = Field(default=None, max_length=2000)


class QAEvaluationRecord(QAEvaluationInput):
    id: str
    workspace_id: str
    evaluator_id: str
    created_at: datetime = Field(default_factory=utc_now)
