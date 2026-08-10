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


class ProductMode(StrEnum):
    BYOA_CORE = "BYOA_CORE"
    AUTONOMOUS_DISCOVERY_EXPERIMENTAL = "AUTONOMOUS_DISCOVERY_EXPERIMENTAL"


class AccountImportSource(StrEnum):
    SINGLE = "SINGLE"
    PASTED_DOMAINS = "PASTED_DOMAINS"
    CSV_UPLOAD = "CSV_UPLOAD"
    API = "API"


class AccountReviewStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"


class AccountReviewEntry(BaseModel):
    """One recorded human decision, kept in order on the account.

    Blueprint section 17: feedback is stored. A later reader needs to know not just
    the current status but who set it and why.
    """

    actor_id: str
    review_status: AccountReviewStatus
    brief_state: str | None = None
    note: str | None = None
    recorded_at: datetime = Field(default_factory=utc_now)


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
    # The run's own budgets, so progress bars report the real ceiling rather than
    # a number hardcoded in the UI.
    max_searches: int | None = None
    max_documents: int | None = None
    findings: list[Finding] = Field(default_factory=list)
    product_mode: ProductMode = ProductMode.BYOA_CORE


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
    subject_entity: str | None = None
    canonical_subject_domain: str | None = None
    event_date: datetime | None = None
    source_id: str | None = None
    supporting_passage: str | None = None
    claim_scope: str = "COMPANY_LEVEL"
    claim_scope_compatible: bool = False
    attachment_decision: str = "UNATTACHED_ENTITY_AMBIGUOUS"
    rejection_reason: str | None = None


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
    brief_state: Literal[
        "FOUNDER_READY",
        "RESEARCH_CANDIDATE",
        "MONITOR",
        "DO_NOT_TARGET",
        "IDENTITY_REVIEW_REQUIRED",
    ] = "RESEARCH_CANDIDATE"
    company_identity: dict[str, object] = Field(default_factory=dict)
    product_mode: ProductMode = ProductMode.BYOA_CORE
    import_source: AccountImportSource | None = None
    provenance: Literal["IMPORTED", "DISCOVERED"] = "DISCOVERED"
    review_status: AccountReviewStatus = AccountReviewStatus.PENDING
    # Supplied at import and carried through to the export, so a founder can hand
    # the reviewed list to the right person on their team.
    owner: str | None = None
    tags: list[str] = Field(default_factory=list)
    review_history: list[AccountReviewEntry] = Field(default_factory=list)


class RetrievalOutcome(StrEnum):
    """Why an official page did or did not become evidence.

    Distinct states, never collapsed into a generic error: a founder reading a brief
    needs to tell "the page said nothing useful" apart from "we were rate limited"
    apart from "that page does not exist".
    """

    RETRIEVED = "RETRIEVED"
    TRUNCATED = "TRUNCATED"
    # Absent, not failed: most company sites have no /careers or /customers page.
    NOT_FOUND = "NOT_FOUND"
    FORBIDDEN = "FORBIDDEN"
    UNAVAILABLE = "UNAVAILABLE"
    TIMED_OUT = "TIMED_OUT"
    RATE_LIMITED = "RATE_LIMITED"
    BLOCKED_BY_POLICY = "BLOCKED_BY_POLICY"
    UNSUPPORTED_CONTENT = "UNSUPPORTED_CONTENT"
    CROSS_DOMAIN_REDIRECT = "CROSS_DOMAIN_REDIRECT"


class RetrievalAttempt(BaseModel):
    url: str
    outcome: RetrievalOutcome
    detail: str | None = None


class RetrievalSummary(BaseModel):
    """How much of what we tried to read we actually read."""

    attempted: int = 0
    retrieved: int = 0
    attempts: list[RetrievalAttempt] = Field(default_factory=list)

    @property
    def absent(self) -> int:
        """Pages that do not exist on the site. Probing them is not a failure."""
        return sum(
            1
            for item in self.attempts
            if item.outcome is RetrievalOutcome.NOT_FOUND
        )

    @property
    def coverage(self) -> float:
        """0-100 over pages that actually exist.

        Absent pages are excluded from the denominator. A site whose only page is
        its homepage has been read completely, and scoring it 12% would penalise
        every small company for not having a /careers page.
        """
        existing = self.attempted - self.absent
        if existing <= 0:
            return 0.0
        return round(self.retrieved / existing * 100, 2)

    @property
    def failed(self) -> list[RetrievalAttempt]:
        """Pages that yielded nothing.

        A truncated page is not here: it was read in part and did produce evidence,
        so counting it as a failure would contradict `retrieved`. It is still
        reported to the reader as a caveat, just not as a failure.
        """
        return [
            item
            for item in self.attempts
            if item.outcome
            not in {
                RetrievalOutcome.RETRIEVED,
                RetrievalOutcome.TRUNCATED,
                RetrievalOutcome.NOT_FOUND,
            }
        ]


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
    # Blueprint section 16.1. Composed deterministically from the verified data
    # below, so it can introduce no claim the rest of the brief does not support.
    executive_summary: str = ""
    risks: list[str]
    evidence: list[EvidenceFact]
    sources: list[SourceDocument]
    signals: list[Signal]
    campaign: CampaignDraft
    verified_facts: list[EvidenceClaim] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    research_candidate: bool = True
    brief_state: Literal[
        "FOUNDER_READY",
        "RESEARCH_CANDIDATE",
        "MONITOR",
        "DO_NOT_TARGET",
        "IDENTITY_REVIEW_REQUIRED",
    ] = "RESEARCH_CANDIDATE"
    verified_identity: dict[str, object] = Field(default_factory=dict)
    verified_icp_facts: list[EvidenceClaim] = Field(default_factory=list)
    icp_mismatches: list[str] = Field(default_factory=list)
    unknown_icp_facts: list[str] = Field(default_factory=list)
    current_signals: list[Signal] = Field(default_factory=list)
    rejected_or_ambiguous_evidence: list[dict[str, object]] = Field(
        default_factory=list
    )
    hypotheses: list[EvidenceClaim] = Field(default_factory=list)
    reason_not_to_target: str | None = None
    next_research_step: str | None = None
    # What we tried to read and what we actually got. Without this a brief built
    # from one page out of eight looked identical to one built from eight.
    retrieval: RetrievalSummary = Field(default_factory=RetrievalSummary)
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


class AccountImportRecord(BaseModel):
    company_name: str = Field(min_length=2, max_length=180)
    domain: str = Field(min_length=3, max_length=500)
    industry: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, max_length=120)
    employee_band: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=2000)
    crm_id: str | None = Field(default=None, max_length=255)
    owner: str | None = Field(default=None, max_length=255)
    tags: list[str] = Field(default_factory=list, max_length=50)


class AccountImportPayload(BaseModel):
    accounts: list[AccountImportRecord] = Field(default_factory=list, max_length=500)
    pasted_domains: str | None = Field(default=None, max_length=100_000)
    csv_text: str | None = Field(default=None, max_length=1_000_000)
    import_source: AccountImportSource = AccountImportSource.API

    @model_validator(mode="after")
    def exactly_one_input_shape(self) -> "AccountImportPayload":
        supplied = sum(
            (
                bool(self.accounts),
                bool((self.pasted_domains or "").strip()),
                bool((self.csv_text or "").strip()),
            )
        )
        if supplied != 1:
            raise ValueError(
                "Provide exactly one of accounts, pasted_domains, or csv_text"
            )
        return self


class AccountImportIssue(BaseModel):
    row: int
    field: str
    code: str
    message: str


class ImportRowVerdict(StrEnum):
    VALID = "VALID"
    DUPLICATE = "DUPLICATE"
    INVALID = "INVALID"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class AccountImportRow(BaseModel):
    """One input row and what happened to it.

    Every submitted row appears here, including the ones that were accepted, so a
    row can never be silently dropped between upload and research.
    """

    row: int
    company_name: str | None = None
    submitted_domain: str | None = None
    canonical_domain: str | None = None
    verdict: ImportRowVerdict
    code: str | None = None
    reason: str | None = None

    @property
    def canonicalised(self) -> bool:
        return bool(
            self.submitted_domain
            and self.canonical_domain
            and self.submitted_domain != self.canonical_domain
        )


class AccountImportSummary(BaseModel):
    total: int = 0
    valid: int = 0
    duplicate: int = 0
    invalid: int = 0
    needs_review: int = 0


class AccountImportValidation(BaseModel):
    import_source: AccountImportSource
    accepted: list[AccountImportRecord]
    issues: list[AccountImportIssue] = Field(default_factory=list)
    duplicate_domains: list[str] = Field(default_factory=list)
    rows: list[AccountImportRow] = Field(default_factory=list)
    summary: AccountImportSummary = Field(default_factory=AccountImportSummary)


class ImportedAccountResult(BaseModel):
    id: str
    company_name: str
    canonical_domain: str
    import_source: AccountImportSource
    provenance: Literal["IMPORTED"] = "IMPORTED"
    queued_for_research: bool = False


class AccountImportResult(BaseModel):
    imported: list[ImportedAccountResult]
    issues: list[AccountImportIssue] = Field(default_factory=list)
    duplicate_domains: list[str] = Field(default_factory=list)


class ProductModeAvailability(BaseModel):
    default_mode: ProductMode = ProductMode.BYOA_CORE
    byoa_core: Literal["AVAILABLE"] = "AVAILABLE"
    autonomous_discovery_experimental: Literal[
        "AVAILABLE", "CONFIGURATION_REQUIRED"
    ]
    search_provider_configured: bool
    primary_provider: Literal["EXA", "TAVILY", "NONE"]
    message: str


class AccountReviewUpdate(BaseModel):
    review_status: AccountReviewStatus
    brief_state: Literal[
        "FOUNDER_READY",
        "RESEARCH_CANDIDATE",
        "MONITOR",
        "DO_NOT_TARGET",
        "IDENTITY_REVIEW_REQUIRED",
    ] | None = None
    # Blueprint section 17: a status change without the reasoning behind it is not
    # much use to whoever reads the account next.
    note: str | None = Field(default=None, max_length=2000)




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
        # Blueprint section 17: flagging the wrong company is a distinct, important
        # correction, not a generic "incorrect".
        "WRONG_IDENTITY",
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
            "WRONG_IDENTITY",
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
