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
    text_terms = set(re.findall(r"[a-z0-9]{3,}", f"{title} {snippet}".lower()))
    term_coverage = (
        len(text_terms & target_terms) / max(1, len(target_terms))
        if target_terms
        else 0
    )
    score = term_coverage * 45
    score += 25 if official_page else 0
    score += (provider_score or 0) * 15
    score += min(10, max(0, query_hits - 1) * 5)
    score += min(5, max(0, provider_hits - 1) * 5)
    return round(max(0, min(100, score)))


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
