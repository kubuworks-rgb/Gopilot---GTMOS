from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

import pytest

from apps.api.app.services.intelligence_quality import (
    CandidatePrequalificationInput,
    CompetitorAssessment,
    CompetitorClassification,
    EvidenceStage,
    MatchState,
    PrequalificationOutcome,
    calculate_prequalification_metrics,
    evaluate_prequalification,
)
from apps.api.app.services.live_research import (
    _competitor_assessment_from_text,
    _qualify_account,
)


FIXTURE = (
    Path(__file__).parent / "fixtures" / "prequalification_recall_baseline.csv"
)


def _candidate(
    *,
    page_role: str = "OFFICIAL_ROOT",
    duplicate: bool = False,
    identity_state: MatchState = MatchState.VERIFIED_MATCH,
    identity_confidence: float = 0.88,
    domain_state: MatchState = MatchState.VERIFIED_MATCH,
    b2b_state: MatchState = MatchState.ESTIMATED_MATCH,
    saas_state: MatchState = MatchState.ESTIMATED_MATCH,
    india_state: MatchState = MatchState.ESTIMATED_MATCH,
    employee_state: MatchState = MatchState.UNKNOWN,
    support_state: MatchState = MatchState.UNKNOWN,
    relevance: int = 33,
    evidence_coverage: float = 0,
    competitor: CompetitorAssessment | None = None,
) -> CandidatePrequalificationInput:
    return CandidatePrequalificationInput(
        page_role=page_role,
        duplicate=duplicate,
        identity_state=identity_state,
        identity_confidence=identity_confidence,
        domain_state=domain_state,
        b2b_software_state=b2b_state,
        saas_state=saas_state,
        india_state=india_state,
        employee_size_state=employee_state,
        support_operations_state=support_state,
        category_relevance=relevance,
        evidence_stage=EvidenceStage.DISCOVERY_HINT,
        evidence_coverage=evidence_coverage,
        competitor=competitor
        or CompetitorAssessment(CompetitorClassification.UNKNOWN),
    )


def _baseline_rows() -> list[dict[str, str]]:
    with FIXTURE.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _baseline_candidate(row: dict[str, str]) -> CandidatePrequalificationInput:
    return _candidate(
        page_role=row["page_role"],
        identity_state=(
            MatchState.VERIFIED_MATCH
            if row["page_role"] == "OFFICIAL_ROOT"
            else MatchState.ESTIMATED_MATCH
        ),
        identity_confidence=float(row["identity_confidence"]),
        domain_state=(
            MatchState.VERIFIED_MATCH
            if float(row["identity_confidence"]) >= 0.85
            else MatchState.ESTIMATED_MATCH
        ),
        relevance=int(row["old_score"]),
    )


@pytest.mark.parametrize("unknown_field", ["employee", "support"])
def test_unknown_soft_discovery_fields_do_not_reject(unknown_field: str) -> None:
    candidate = _candidate(
        employee_state=(
            MatchState.UNKNOWN
            if unknown_field == "employee"
            else MatchState.VERIFIED_MATCH
        ),
        support_state=(
            MatchState.UNKNOWN
            if unknown_field == "support"
            else MatchState.VERIFIED_MATCH
        ),
    )

    decision = evaluate_prequalification(candidate)

    assert decision.outcome == PrequalificationOutcome.PREQUALIFIED_WITH_UNCERTAINTY
    assert any(unknown_field in item for item in decision.research_requirements)


def test_missing_search_snippet_geography_stays_unknown_and_researchable() -> None:
    decision = evaluate_prequalification(
        _candidate(india_state=MatchState.UNKNOWN)
    )

    assert decision.outcome == PrequalificationOutcome.PREQUALIFIED_WITH_UNCERTAINTY
    assert "Verify India connection." in decision.research_requirements


@pytest.mark.parametrize(
    ("field", "candidate"),
    [
        ("India connection", _candidate(india_state=MatchState.VERIFIED_MISMATCH)),
        (
            "B2B software model",
            _candidate(
                b2b_state=MatchState.VERIFIED_MISMATCH,
                saas_state=MatchState.VERIFIED_MISMATCH,
            ),
        ),
    ],
)
def test_verified_hard_mismatch_rejects(
    field: str, candidate: CandidatePrequalificationInput
) -> None:
    decision = evaluate_prequalification(candidate)

    assert decision.outcome == PrequalificationOutcome.REJECTED
    assert any(field in reason for reason in decision.rejection_reasons)


def test_incomplete_official_company_proceeds_with_uncertainty() -> None:
    decision = evaluate_prequalification(
        _candidate(
            identity_state=MatchState.ESTIMATED_MATCH,
            domain_state=MatchState.ESTIMATED_MATCH,
            b2b_state=MatchState.UNKNOWN,
            saas_state=MatchState.ESTIMATED_MATCH,
            india_state=MatchState.UNKNOWN,
            relevance=31,
        )
    )

    assert decision.outcome == PrequalificationOutcome.PREQUALIFIED_WITH_UNCERTAINTY
    assert decision.research_requirements


def test_direct_competitor_requires_strong_structured_evidence_to_reject() -> None:
    direct = CompetitorAssessment(
        CompetitorClassification.DIRECT_COMPETITOR,
        confidence=0.91,
        evidence_ids=("evidence-1",),
        overlap_dimensions=(
            "product",
            "buyer",
            "use_case",
            "commercial_substitution",
        ),
    )

    decision = evaluate_prequalification(_candidate(competitor=direct))

    assert direct.automatic_rejection_eligible
    assert decision.outcome == PrequalificationOutcome.REJECTED


def test_adjacent_vendor_does_not_automatically_reject() -> None:
    adjacent = CompetitorAssessment(
        CompetitorClassification.ADJACENT_VENDOR,
        confidence=0.75,
        evidence_ids=("evidence-1",),
        overlap_dimensions=("product", "use_case"),
    )

    decision = evaluate_prequalification(_candidate(competitor=adjacent))

    assert not adjacent.automatic_rejection_eligible
    assert decision.outcome == PrequalificationOutcome.PREQUALIFIED_WITH_UNCERTAINTY


@pytest.mark.parametrize("page_role", ["DIRECTORY", "NEWS", "BLOG", "JOB_BOARD"])
def test_verified_non_company_result_roles_reject(page_role: str) -> None:
    assert (
        evaluate_prequalification(_candidate(page_role=page_role)).outcome
        == PrequalificationOutcome.REJECTED
    )


def test_duplicate_entity_rejects() -> None:
    assert (
        evaluate_prequalification(_candidate(duplicate=True)).outcome
        == PrequalificationOutcome.REJECTED
    )


def test_missing_factor_is_not_zero_mismatch() -> None:
    unknown = evaluate_prequalification(
        _candidate(india_state=MatchState.UNKNOWN, relevance=33)
    )
    mismatch = evaluate_prequalification(
        _candidate(india_state=MatchState.VERIFIED_MISMATCH, relevance=33)
    )

    assert unknown.outcome == PrequalificationOutcome.PREQUALIFIED_WITH_UNCERTAINTY
    assert mismatch.outcome == PrequalificationOutcome.REJECTED


def test_evidence_coverage_remains_separate_from_relevance() -> None:
    sparse = evaluate_prequalification(
        _candidate(relevance=33, evidence_coverage=0.0)
    )
    covered = evaluate_prequalification(
        _candidate(relevance=33, evidence_coverage=0.9)
    )

    assert sparse.candidate_relevance == covered.candidate_relevance == 33
    assert sparse.outcome == covered.outcome
    assert sparse.evidence_coverage == 0
    assert covered.evidence_coverage == 0.9


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (35, PrequalificationOutcome.PREQUALIFIED),
        (30, PrequalificationOutcome.PREQUALIFIED_WITH_UNCERTAINTY),
        (25, PrequalificationOutcome.REVIEW_REQUIRED),
        (24, PrequalificationOutcome.REJECTED),
    ],
)
def test_calibrated_threshold_bands(
    score: int, expected: PrequalificationOutcome
) -> None:
    assert evaluate_prequalification(_candidate(relevance=score)).outcome == expected


def test_bizbms_overlap_is_not_direct_competitor_without_substitution_evidence() -> None:
    assessment = _competitor_assessment_from_text(
        "BizBMS is an enterprise B2B SaaS and AI platform with customer support "
        "capabilities for operations teams.",
        evidence_ids=("bizbms-first-party",),
    )

    assert assessment.classification == (
        CompetitorClassification.POTENTIAL_BUYER_WITH_OVERLAPPING_FEATURES
    )
    assert not assessment.automatic_rejection_eligible


def test_final_qualification_rejects_evidenced_direct_competitor() -> None:
    status, reasons = _qualify_account(
        "India B2B SaaS customer support platform for support teams. "
        "Our AI agents automate customer support and resolve tickets as a "
        "commercial support automation platform.",
        domain_validated=True,
        size_in_range=None,
        competitor_evidence_ids=("first-party-evidence",),
    )

    assert status == "DISQUALIFIED"
    assert any("direct support-automation competitor" in item for item in reasons)


def test_final_qualification_keeps_adjacent_vendor_uncertain() -> None:
    status, reasons = _qualify_account(
        "India B2B SaaS software platform for enterprise teams. The product "
        "includes AI customer support workflows and can resolve tickets.",
        domain_validated=True,
        size_in_range=None,
        competitor_evidence_ids=("first-party-evidence",),
    )

    assert status == "QUALIFIED_WITH_UNCERTAINTY"
    assert any("Competitor overlap requires research" in item for item in reasons)


def test_first_30_replay_proves_recall_recovery_without_precision_collapse() -> None:
    labelled = [
        row for row in _baseline_rows()[:30] if row["manual_label"] != "UNCERTAIN"
    ]
    old_predictions = [
        (
            row["manual_label"] == "USEFUL_RAW_CANDIDATE",
            row["old_decision"] == "ACCEPTED",
        )
        for row in labelled
    ]
    new_predictions = [
        (
            row["manual_label"] == "USEFUL_RAW_CANDIDATE",
            evaluate_prequalification(_baseline_candidate(row)).outcome
            in {
                PrequalificationOutcome.PREQUALIFIED,
                PrequalificationOutcome.PREQUALIFIED_WITH_UNCERTAINTY,
            },
        )
        for row in labelled
    ]

    old = calculate_prequalification_metrics(old_predictions)
    new = calculate_prequalification_metrics(new_predictions)

    assert (old.true_positives, old.false_negatives, old.true_negatives) == (1, 24, 2)
    assert old.recall == 0.04
    assert (new.true_positives, new.false_positives, new.false_negatives) == (
        25,
        2,
        0,
    )
    assert new.recall >= 0.85
    assert new.precision >= 0.70
    assert new.false_negative_rate <= 0.15


def test_all_60_shadow_replay_has_expected_outcome_distribution() -> None:
    outcomes = Counter(
        evaluate_prequalification(_baseline_candidate(row)).outcome
        for row in _baseline_rows()
    )

    assert outcomes == {
        PrequalificationOutcome.PREQUALIFIED: 5,
        PrequalificationOutcome.PREQUALIFIED_WITH_UNCERTAINTY: 30,
        PrequalificationOutcome.REVIEW_REQUIRED: 25,
    }


def test_prequalification_metrics_calculation() -> None:
    metrics = calculate_prequalification_metrics(
        [(True, True), (True, False), (False, True), (False, False)]
    )

    assert metrics.true_positives == 1
    assert metrics.false_positives == 1
    assert metrics.true_negatives == 1
    assert metrics.false_negatives == 1
    assert metrics.precision == 0.5
    assert metrics.recall == 0.5
    assert metrics.f1 == 0.5
    assert metrics.false_negative_rate == 0.5
