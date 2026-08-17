"""A research run must report what it actually managed to read.

The defect this covers was observed on the deployed stack: importing apache.org
attempted 8 official pages, 7 failed with SOURCE_UNAVAILABLE, and the brief showed
"VALIDATED DOMAIN 99%", one fact, and "0 evidence items rejected" -- an 87.5%
unsuccessful run presented as clean success. The failures were persisted in
research_tasks but nothing read them back out, so neither the API nor the UI could
show them.
"""

from __future__ import annotations

import pytest

from apps.api.app.domain.models import (
    RetrievalAttempt,
    RetrievalOutcome,
    RetrievalSummary,
)
from apps.api.app.services.live_research import _retrieval_outcome_for
from apps.api.app.services.scoring import score_account


def _summary(*outcomes: RetrievalOutcome) -> RetrievalSummary:
    attempts = [
        RetrievalAttempt(url=f"https://acme.example/{index}", outcome=outcome)
        for index, outcome in enumerate(outcomes)
    ]
    retrieved = sum(
        1
        for item in attempts
        if item.outcome in {RetrievalOutcome.RETRIEVED, RetrievalOutcome.TRUNCATED}
    )
    return RetrievalSummary(
        attempted=len(attempts), retrieved=retrieved, attempts=attempts
    )


# ------------------------------------------------------- the observed apache case


def test_the_apache_case_is_absence_not_failure() -> None:
    """apache.org has no /careers or /customers page. That is normal.

    Reporting seven failures here would be alarming and wrong: everything that
    exists on the site was read.
    """
    summary = _summary(
        RetrievalOutcome.RETRIEVED,
        *[RetrievalOutcome.NOT_FOUND] * 7,
    )

    assert summary.attempted == 8
    assert summary.retrieved == 1
    assert summary.absent == 7
    assert summary.failed == [], "a missing page is not a failed page"
    assert summary.coverage == 100.0, "everything that exists was read"


def test_genuine_failures_do_reduce_coverage() -> None:
    summary = _summary(
        RetrievalOutcome.RETRIEVED,
        RetrievalOutcome.FORBIDDEN,
        RetrievalOutcome.TIMED_OUT,
        RetrievalOutcome.NOT_FOUND,
    )

    # Three pages exist; one was read.
    assert summary.coverage == pytest.approx(33.33, abs=0.01)
    assert len(summary.failed) == 2


def test_a_missing_page_and_a_refused_page_are_different_states() -> None:
    assert _retrieval_outcome_for("SOURCE_NOT_FOUND") is RetrievalOutcome.NOT_FOUND
    assert _retrieval_outcome_for("SOURCE_FORBIDDEN") is RetrievalOutcome.FORBIDDEN
    assert _retrieval_outcome_for("SOURCE_NOT_FOUND") is not _retrieval_outcome_for(
        "SOURCE_FORBIDDEN"
    )


def test_every_gateway_code_keeps_its_own_meaning() -> None:
    """Distinct outcomes, never collapsed into one generic error."""
    assert _retrieval_outcome_for("SOURCE_UNAVAILABLE") is RetrievalOutcome.UNAVAILABLE
    assert _retrieval_outcome_for("FETCH_TIMEOUT") is RetrievalOutcome.TIMED_OUT
    assert _retrieval_outcome_for("RATE_LIMITED") is RetrievalOutcome.RATE_LIMITED
    assert (
        _retrieval_outcome_for("URL_POLICY_BLOCKED")
        is RetrievalOutcome.BLOCKED_BY_POLICY
    )
    assert (
        _retrieval_outcome_for("UNSUPPORTED_CONTENT_TYPE")
        is RetrievalOutcome.UNSUPPORTED_CONTENT
    )


def test_an_unmapped_code_degrades_to_unavailable_not_to_success() -> None:
    assert _retrieval_outcome_for("SOMETHING_NEW") is RetrievalOutcome.UNAVAILABLE


def test_a_truncated_page_counts_as_read() -> None:
    """It produced evidence, so it is not a failure -- but it is still reported."""
    summary = _summary(RetrievalOutcome.RETRIEVED, RetrievalOutcome.TRUNCATED)

    assert summary.retrieved == 2
    assert summary.coverage == 100.0
    assert summary.failed == []


def test_a_run_with_no_attempts_reports_zero_not_a_crash() -> None:
    empty = RetrievalSummary()

    assert empty.attempted == 0
    assert empty.coverage == 0.0
    assert empty.failed == []


# ------------------------------------------------- confidence reflects coverage


def _confidence(retrieval_coverage: float | None) -> int:
    return score_account(
        industry_match=100.0,
        size_match=None,
        geography_match=None,
        signal_strength=0,
        signal_recency=None,
        evidence_coverage=90,
        source_quality=90,
        fit_evidence=["e"],
        signal_evidence=[],
        retrieval_coverage=retrieval_coverage,
    ).confidence.score


def test_reading_a_fraction_of_a_site_scores_lower_than_reading_all_of_it() -> None:
    """The defect made these two identical."""
    assert _confidence(12.5) < _confidence(100.0)


def test_retrieval_coverage_is_visible_in_the_breakdown() -> None:
    scores = score_account(
        industry_match=100.0,
        size_match=None,
        geography_match=None,
        signal_strength=0,
        signal_recency=None,
        evidence_coverage=90,
        source_quality=90,
        fit_evidence=["e"],
        signal_evidence=[],
        retrieval_coverage=12.5,
    )

    labels = [component.label for component in scores.confidence.components]
    assert "Retrieval coverage" in labels, "a founder must see why confidence dropped"


def test_runs_without_outcome_tracking_are_not_penalised() -> None:
    """None means unrecorded, not zero: it renormalises rather than scoring 0."""
    unrecorded = _confidence(None)

    assert unrecorded > _confidence(0.0)
    # With both other components at 90, renormalising onto them yields exactly 90 --
    # the value it had before retrieval coverage existed.
    assert unrecorded == 90


def test_confidence_still_falls_when_retrieval_fails_entirely() -> None:
    assert _confidence(0.0) < _confidence(None)
