from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class CriterionRequirement(StrEnum):
    HARD = "HARD"
    SOFT = "SOFT"
    INFORMATIONAL = "INFORMATIONAL"


class CriterionState(StrEnum):
    TRUE = "TRUE"
    FALSE = "FALSE"
    UNKNOWN = "UNKNOWN"


class MatchState(StrEnum):
    VERIFIED_MATCH = "VERIFIED_MATCH"
    ESTIMATED_MATCH = "ESTIMATED_MATCH"
    UNKNOWN = "UNKNOWN"
    VERIFIED_MISMATCH = "VERIFIED_MISMATCH"


class EvidenceStage(StrEnum):
    DISCOVERY_HINT = "DISCOVERY_HINT"
    PREQUALIFICATION_EVIDENCE = "PREQUALIFICATION_EVIDENCE"
    VERIFIED_ACCOUNT_EVIDENCE = "VERIFIED_ACCOUNT_EVIDENCE"


class CompetitorClassification(StrEnum):
    DIRECT_COMPETITOR = "DIRECT_COMPETITOR"
    ADJACENT_VENDOR = "ADJACENT_VENDOR"
    POTENTIAL_BUYER_WITH_OVERLAPPING_FEATURES = (
        "POTENTIAL_BUYER_WITH_OVERLAPPING_FEATURES"
    )
    NOT_COMPETITOR = "NOT_COMPETITOR"
    UNKNOWN = "UNKNOWN"


class PrequalificationOutcome(StrEnum):
    PREQUALIFIED = "PREQUALIFIED"
    PREQUALIFIED_WITH_UNCERTAINTY = "PREQUALIFIED_WITH_UNCERTAINTY"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    REJECTED = "REJECTED"


class SourceRole(StrEnum):
    FIRST_PARTY = "FIRST_PARTY"
    INDEPENDENT_MARKET_SOURCE = "INDEPENDENT_MARKET_SOURCE"
    NEWS = "NEWS"
    DIRECTORY = "DIRECTORY"
    LICENSED_FIRMOGRAPHIC = "LICENSED_FIRMOGRAPHIC"
    VENDOR_MARKETING = "VENDOR_MARKETING"
    COMMUNITY = "COMMUNITY"
    OTHER = "OTHER"


@dataclass(frozen=True)
class CriterionEvaluation:
    key: str
    requirement: CriterionRequirement
    state: CriterionState
    evidence_ids: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class QualificationDecision:
    status: str
    evaluations: tuple[CriterionEvaluation, ...]
    known_hard_count: int
    hard_coverage: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class CandidateScoreBreakdown:
    term_coverage: float
    term_coverage_points: float
    official_page_points: float
    provider_relevance_points: float
    query_agreement_points: float
    provider_agreement_points: float
    total: int


@dataclass(frozen=True)
class CompetitorAssessment:
    classification: CompetitorClassification
    confidence: float = 0
    evidence_ids: tuple[str, ...] = ()
    overlap_dimensions: tuple[str, ...] = ()

    @property
    def automatic_rejection_eligible(self) -> bool:
        required = {"product", "buyer", "use_case", "commercial_substitution"}
        return (
            self.classification == CompetitorClassification.DIRECT_COMPETITOR
            and self.confidence >= 0.8
            and required.issubset(set(self.overlap_dimensions))
            and bool(self.evidence_ids)
        )


@dataclass(frozen=True)
class CandidatePrequalificationInput:
    page_role: str
    duplicate: bool
    identity_state: MatchState
    identity_confidence: float
    domain_state: MatchState
    b2b_software_state: MatchState
    saas_state: MatchState
    india_state: MatchState
    employee_size_state: MatchState
    support_operations_state: MatchState
    category_relevance: int
    evidence_stage: EvidenceStage = EvidenceStage.DISCOVERY_HINT
    evidence_coverage: float = 0
    competitor: CompetitorAssessment = CompetitorAssessment(
        CompetitorClassification.UNKNOWN
    )


@dataclass(frozen=True)
class CandidatePrequalificationDecision:
    outcome: PrequalificationOutcome
    research_worthiness: int
    candidate_relevance: int
    identity_confidence: float
    evidence_coverage: float
    research_requirements: tuple[str, ...]
    rejection_reasons: tuple[str, ...]
    high_threshold: int
    middle_threshold: int
    low_threshold: int


@dataclass(frozen=True)
class PrequalificationMetrics:
    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float
    false_negative_rate: float


PREQUALIFICATION_HIGH_THRESHOLD = 35
PREQUALIFICATION_MIDDLE_THRESHOLD = 30
PREQUALIFICATION_LOW_THRESHOLD = 25


def decide_qualification(
    evaluations: list[CriterionEvaluation],
) -> QualificationDecision:
    hard = [
        item for item in evaluations if item.requirement == CriterionRequirement.HARD
    ]
    known = [item for item in hard if item.state != CriterionState.UNKNOWN]
    false_hard = [item for item in hard if item.state == CriterionState.FALSE]
    true_hard = [item for item in hard if item.state == CriterionState.TRUE]
    unknown_soft = [
        item
        for item in evaluations
        if item.requirement == CriterionRequirement.SOFT
        and item.state == CriterionState.UNKNOWN
    ]
    coverage = len(known) / len(hard) if hard else 1.0
    if false_hard:
        status = "DISQUALIFIED"
    elif hard and len(true_hard) == len(hard) and not unknown_soft:
        status = "QUALIFIED"
    elif hard and len(true_hard) == len(hard):
        status = "QUALIFIED_WITH_UNCERTAINTY"
    elif true_hard and coverage >= 0.5:
        status = "QUALIFIED_WITH_UNCERTAINTY"
    else:
        status = "INSUFFICIENT_EVIDENCE"
    return QualificationDecision(
        status=status,
        evaluations=tuple(evaluations),
        known_hard_count=len(known),
        hard_coverage=round(coverage, 4),
        reasons=tuple(item.reason for item in evaluations if item.reason),
    )


def candidate_relevance_breakdown(
    *,
    title: str,
    snippet: str,
    target_terms: set[str],
    official_page: bool,
    provider_score: float | None,
    query_hits: int,
    provider_hits: int,
) -> CandidateScoreBreakdown:
    text_terms = set(re.findall(r"[a-z0-9]{3,}", f"{title} {snippet}".lower()))
    term_coverage = (
        len(text_terms & target_terms) / max(1, len(target_terms))
        if target_terms
        else 0
    )
    term_points = term_coverage * 45
    official_points = 25 if official_page else 0
    provider_points = (provider_score or 0) * 15
    query_points = min(10, max(0, query_hits - 1) * 5)
    provider_agreement_points = min(5, max(0, provider_hits - 1) * 5)
    total = round(
        max(
            0,
            min(
                100,
                term_points
                + official_points
                + provider_points
                + query_points
                + provider_agreement_points,
            ),
        )
    )
    return CandidateScoreBreakdown(
        term_coverage=round(term_coverage, 4),
        term_coverage_points=round(term_points, 2),
        official_page_points=float(official_points),
        provider_relevance_points=round(provider_points, 2),
        query_agreement_points=float(query_points),
        provider_agreement_points=float(provider_agreement_points),
        total=total,
    )


def candidate_relevance_score(
    *,
    title: str,
    snippet: str,
    target_terms: set[str],
    official_page: bool,
    provider_score: float | None,
    query_hits: int,
    provider_hits: int,
) -> int:
    return candidate_relevance_breakdown(
        title=title,
        snippet=snippet,
        target_terms=target_terms,
        official_page=official_page,
        provider_score=provider_score,
        query_hits=query_hits,
        provider_hits=provider_hits,
    ).total


def _research_requirements(
    candidate: CandidatePrequalificationInput,
) -> tuple[str, ...]:
    requirements: list[str] = []
    for label, state in (
        ("official domain", candidate.domain_state),
        ("B2B software model", candidate.b2b_software_state),
        ("SaaS model", candidate.saas_state),
        ("India connection", candidate.india_state),
        ("employee size", candidate.employee_size_state),
        ("support operations", candidate.support_operations_state),
    ):
        if state in {MatchState.UNKNOWN, MatchState.ESTIMATED_MATCH}:
            requirements.append(f"Verify {label}.")
    if candidate.competitor.classification in {
        CompetitorClassification.UNKNOWN,
        CompetitorClassification.ADJACENT_VENDOR,
        CompetitorClassification.POTENTIAL_BUYER_WITH_OVERLAPPING_FEATURES,
    }:
        requirements.append("Verify competitor overlap and commercial substitution.")
    return tuple(requirements)


def evaluate_prequalification(
    candidate: CandidatePrequalificationInput,
    *,
    high_threshold: int = PREQUALIFICATION_HIGH_THRESHOLD,
    middle_threshold: int = PREQUALIFICATION_MIDDLE_THRESHOLD,
    low_threshold: int = PREQUALIFICATION_LOW_THRESHOLD,
) -> CandidatePrequalificationDecision:
    if not (0 <= low_threshold <= middle_threshold <= high_threshold <= 100):
        raise ValueError("Prequalification thresholds must be ordered within 0-100")

    rejection_reasons: list[str] = []
    rejected_roles = {
        "DIRECTORY",
        "NEWS",
        "BLOG",
        "JOB_BOARD",
        "SOCIAL",
        "VENDOR_MARKETING",
        "OTHER",
    }
    if candidate.duplicate:
        rejection_reasons.append("Duplicate canonical company entity.")
    if candidate.page_role in rejected_roles:
        rejection_reasons.append(
            f"Verified non-company result role: {candidate.page_role}."
        )
    for label, state in (
        ("official company identity", candidate.identity_state),
        ("official company domain", candidate.domain_state),
        ("B2B software model", candidate.b2b_software_state),
        ("SaaS model", candidate.saas_state),
        ("India connection", candidate.india_state),
    ):
        if state == MatchState.VERIFIED_MISMATCH:
            rejection_reasons.append(f"Verified hard-criterion mismatch: {label}.")
    if candidate.competitor.automatic_rejection_eligible:
        rejection_reasons.append(
            "High-confidence direct competitor with commercial-substitution evidence."
        )
    requirements = _research_requirements(candidate)
    if rejection_reasons:
        return CandidatePrequalificationDecision(
            outcome=PrequalificationOutcome.REJECTED,
            research_worthiness=0,
            candidate_relevance=candidate.category_relevance,
            identity_confidence=candidate.identity_confidence,
            evidence_coverage=candidate.evidence_coverage,
            research_requirements=requirements,
            rejection_reasons=tuple(rejection_reasons),
            high_threshold=high_threshold,
            middle_threshold=middle_threshold,
            low_threshold=low_threshold,
        )

    relevance = max(0, min(100, candidate.category_relevance))
    plausible_model = any(
        state in {MatchState.VERIFIED_MATCH, MatchState.ESTIMATED_MATCH}
        for state in (candidate.b2b_software_state, candidate.saas_state)
    )
    if relevance >= high_threshold and plausible_model:
        outcome = PrequalificationOutcome.PREQUALIFIED
    elif relevance >= middle_threshold:
        outcome = PrequalificationOutcome.PREQUALIFIED_WITH_UNCERTAINTY
    elif relevance >= low_threshold:
        outcome = PrequalificationOutcome.REVIEW_REQUIRED
    else:
        outcome = PrequalificationOutcome.REJECTED
        rejection_reasons.append(
            f"Candidate relevance {relevance} is below calibrated low threshold "
            f"{low_threshold}."
        )
    research_worthiness = round(
        relevance * 0.65
        + max(0, min(1, candidate.identity_confidence)) * 25
        + (
            10
            if candidate.evidence_stage == EvidenceStage.PREQUALIFICATION_EVIDENCE
            else 5
            if candidate.evidence_stage == EvidenceStage.DISCOVERY_HINT
            else 15
        )
    )
    return CandidatePrequalificationDecision(
        outcome=outcome,
        research_worthiness=max(0, min(100, research_worthiness)),
        candidate_relevance=relevance,
        identity_confidence=candidate.identity_confidence,
        evidence_coverage=candidate.evidence_coverage,
        research_requirements=requirements,
        rejection_reasons=tuple(rejection_reasons),
        high_threshold=high_threshold,
        middle_threshold=middle_threshold,
        low_threshold=low_threshold,
    )


def calculate_prequalification_metrics(
    labelled_predictions: list[tuple[bool, bool]],
) -> PrequalificationMetrics:
    true_positives = sum(
        1 for expected, predicted in labelled_predictions if expected and predicted
    )
    false_positives = sum(
        1
        for expected, predicted in labelled_predictions
        if not expected and predicted
    )
    true_negatives = sum(
        1
        for expected, predicted in labelled_predictions
        if not expected and not predicted
    )
    false_negatives = sum(
        1
        for expected, predicted in labelled_predictions
        if expected and not predicted
    )
    precision = true_positives / max(1, true_positives + false_positives)
    recall = true_positives / max(1, true_positives + false_negatives)
    f1 = 2 * precision * recall / max(0.000001, precision + recall)
    false_negative_rate = false_negatives / max(
        1, true_positives + false_negatives
    )
    return PrequalificationMetrics(
        true_positives=true_positives,
        false_positives=false_positives,
        true_negatives=true_negatives,
        false_negatives=false_negatives,
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1=round(f1, 4),
        false_negative_rate=round(false_negative_rate, 4),
    )


def source_quality_score(
    *,
    role: SourceRole,
    directness: float,
    recency: float,
    entity_match: float,
) -> float:
    role_weight = {
        SourceRole.FIRST_PARTY: 0.88,
        SourceRole.LICENSED_FIRMOGRAPHIC: 0.90,
        SourceRole.INDEPENDENT_MARKET_SOURCE: 0.84,
        SourceRole.NEWS: 0.78,
        SourceRole.DIRECTORY: 0.58,
        SourceRole.COMMUNITY: 0.45,
        SourceRole.VENDOR_MARKETING: 0.35,
        SourceRole.OTHER: 0.40,
    }[role]
    return round(
        max(
            0,
            min(
                1,
                role_weight * 0.40
                + directness * 0.25
                + recency * 0.15
                + entity_match * 0.20,
            ),
        ),
        4,
    )


def claim_source_compatible(claim_type: str, role: SourceRole) -> bool:
    normalized = claim_type.upper()
    if normalized in {"MARKET_SIZE", "MARKET_GROWTH"}:
        return role in {
            SourceRole.INDEPENDENT_MARKET_SOURCE,
            SourceRole.NEWS,
            SourceRole.LICENSED_FIRMOGRAPHIC,
        }
    if normalized in {"EMPLOYEE_COUNT", "REVENUE"}:
        return role in {
            SourceRole.FIRST_PARTY,
            SourceRole.LICENSED_FIRMOGRAPHIC,
            SourceRole.INDEPENDENT_MARKET_SOURCE,
            SourceRole.NEWS,
        }
    if normalized in {"PRODUCT", "LOCATION", "CUSTOMERS", "HIRING"}:
        return role in {
            SourceRole.FIRST_PARTY,
            SourceRole.INDEPENDENT_MARKET_SOURCE,
            SourceRole.NEWS,
            SourceRole.LICENSED_FIRMOGRAPHIC,
        }
    return role != SourceRole.VENDOR_MARKETING
