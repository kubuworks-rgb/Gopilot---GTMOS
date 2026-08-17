from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from apps.api.app.config import Settings
from apps.api.app.main import app
from apps.api.app.services.scoring import score_account, signal_decay
from apps.api.app.db.models import EvidenceFactRow
from apps.api.app.services.live_research import (
    _company_size_from_text,
    _is_candidate_company_page,
    _news_result_matches_company,
    _qualify_account,
    _signals_from_facts,
)
from services.research_gateway.app.schemas import SearchResult
from pydantic import HttpUrl


client = TestClient(app)


def test_cross_workspace_access_is_forbidden() -> None:
    workspace = client.post(
        "/api/v1/workspaces",
        headers={"X-Demo-User": "owner-a"},
        json={"name": "Tenant A"},
    ).json()
    response = client.get(
        "/api/v1/bootstrap",
        headers={"X-Demo-User": "attacker-b", "X-Workspace-Id": workspace["id"]},
    )
    assert response.status_code == 403


def test_scoring_is_deterministic_and_fit_is_separate_from_intent() -> None:
    def calculate_score():
        return score_account(
            industry_match=90,
            size_match=80,
            geography_match=100,
            signal_strength=60,
            signal_recency=70,
            evidence_coverage=85,
            source_quality=90,
            fit_evidence=["fit"],
            signal_evidence=["intent"],
        )

    first = calculate_score()
    second = calculate_score()
    assert first == second
    assert first.fit.score != first.intent.score
    assert first.priority == round(
        (first.fit.score * 0.55 + first.intent.score * 0.45)
        * first.confidence.score
        / 100
    )


def test_a_fully_unknown_fit_is_excluded_rather_than_scored_zero() -> None:
    """The fly.io case from the live-mode run (docs/qa/LIVE_E2E_FINDINGS.md #2).

    All three fit factors were unknown. Before the fix, `_breakdown_missing_aware`
    fell through to a confident-looking fit of 0, and priority was computed as
    though a 0-fit account had been evaluated and found wanting --
    (0*0.55 + 70*0.45) * 0.91 = 29 -- instead of excluding fit and renormalizing
    priority onto intent alone -- 70 * 0.91 = 64. The account was ranked less
    than half as urgent as its own evidence supported.
    """
    scores = score_account(
        industry_match=None,
        size_match=None,
        geography_match=None,
        signal_strength=70,
        signal_recency=70,
        evidence_coverage=90,
        source_quality=90,
        retrieval_coverage=94,
        fit_evidence=[],
        signal_evidence=["intent"],
    )

    assert scores.fit.determined is False
    assert scores.fit.components == []
    assert scores.intent.determined is True
    assert scores.intent.score == 70
    assert scores.confidence.score == 91
    assert scores.priority == 64  # not 29


def test_a_partially_unknown_fit_still_renormalizes_as_before() -> None:
    """The fix must not disturb the case that already worked: one known factor
    carries the full weight rather than the dimension itself becoming
    undetermined."""
    scores = score_account(
        industry_match=80,
        size_match=None,
        geography_match=None,
        signal_strength=50,
        signal_recency=50,
        evidence_coverage=80,
        source_quality=80,
        retrieval_coverage=80,
        fit_evidence=["fit"],
        signal_evidence=["intent"],
    )

    assert scores.fit.determined is True
    assert scores.fit.score == 80


def test_priority_renormalizes_onto_intent_when_fit_is_undetermined() -> None:
    """A unit-level check on the composition, independent of score_account's
    particular weightings, so this fails on its own if the renormalization
    regresses even if the fixture numbers above ever drift."""
    from apps.api.app.domain.models import ScoreBreakdown
    from apps.api.app.services.scoring import _priority_from

    fit = ScoreBreakdown(score=0, components=[], determined=False)
    intent = ScoreBreakdown(score=80, components=[], determined=True)
    confidence = ScoreBreakdown(score=100, components=[], determined=True)

    assert _priority_from(fit, intent, confidence) == 80  # not 36


def test_priority_is_zero_when_every_weighted_dimension_is_undetermined() -> None:
    from apps.api.app.domain.models import ScoreBreakdown
    from apps.api.app.services.scoring import _priority_from

    fit = ScoreBreakdown(score=0, components=[], determined=False)
    intent = ScoreBreakdown(score=0, components=[], determined=False)
    confidence = ScoreBreakdown(score=100, components=[], determined=True)

    assert _priority_from(fit, intent, confidence) == 0


def test_old_signals_decay() -> None:
    recent = signal_decay(datetime.now(UTC) - timedelta(days=1))
    old = signal_decay(datetime.now(UTC) - timedelta(days=90))
    assert recent > old
    assert old == pytest.approx(0.25, abs=0.01)


def test_production_rejects_demo_and_fixtures() -> None:
    with pytest.raises(RuntimeError, match="Production forbids"):
        Settings(
            app_env="production", research_mode="fixture", demo_auth_enabled=True
        ).validate()


def test_csv_formula_injection_is_neutralized() -> None:
    from apps.api.app.api.routes import _csv_safe

    assert _csv_safe("=HYPERLINK('bad')").startswith("'")
    assert _csv_safe("Normal Co") == "Normal Co"



def test_account_qualification_preserves_unknown_size() -> None:
    status, reasons = _qualify_account(
        (
            "An India B2B SaaS enterprise software platform based in Bengaluru "
            "with customer support and customer success teams."
        ),
        domain_validated=True,
        size_in_range=None,
    )

    assert status == "QUALIFIED_WITH_UNCERTAINTY"
    assert "Company size remains unknown." in reasons
    assert _company_size_from_text("Our team builds software.") == (
        None,
        "UNKNOWN",
        None,
    )


def test_account_size_and_signal_classes_are_evidence_driven() -> None:
    band, size_status, in_range = _company_size_from_text(
        "Our team has 180 employees building enterprise software in India."
    )
    fact = EvidenceFactRow(
        id=uuid4(),
        workspace_id=uuid4(),
        source_id=uuid4(),
        subject="Acme",
        predicate="states",
        object="Acme is hiring customer success managers.",
        claim="Acme is hiring customer success managers for three open roles.",
        passage="Acme is hiring customer success managers for three open roles.",
        confidence="0.90",
        status="supported",
        observed_at=datetime.now(UTC),
        valid_from=None,
        valid_until=None,
    )

    assert (band, size_status, in_range) == ("180+", "VERIFIED", True)
    assert [item[0] for item in _signals_from_facts([fact])] == [
        "CUSTOMER_SUCCESS_HIRING"
    ]

    fact.claim = "Acme provides customer success software."
    assert _signals_from_facts([fact]) == []


def test_account_size_ignores_product_ui_mock_numbers() -> None:
    assert _company_size_from_text(
        "May 2025 Payroll 4,832 employees Net Payroll Present On Leave Absent"
    ) == (None, "UNKNOWN", None)


def test_company_discovery_rejects_profile_articles_as_official_pages() -> None:
    article = SearchResult(
        url=HttpUrl("https://example.ai/blog/acme-profile-2026"),
        canonical_url=HttpUrl("https://example.ai/blog/acme-profile-2026"),
        title="Acme Profile 2026: Financials and competitors",
        snippet="An analyst profile.",
        backend="test",
    )
    official = SearchResult(
        url=HttpUrl("https://acme.example/about"),
        canonical_url=HttpUrl("https://acme.example/about"),
        title="About Acme",
        snippet="Official company page.",
        backend="test",
    )

    assert not _is_candidate_company_page(article)
    assert _is_candidate_company_page(official)


def test_external_news_must_match_the_company_entity() -> None:
    wrong_entity = SearchResult(
        url=HttpUrl("https://news.example/go-robotaxi-ipo"),
        canonical_url=HttpUrl("https://news.example/go-robotaxi-ipo"),
        title="Go raises $553M IPO for robotaxis",
        snippet="The Japanese mobility company plans international expansion.",
        backend="test",
    )
    correct_entity = SearchResult(
        url=HttpUrl("https://news.example/hrone-expansion"),
        canonical_url=HttpUrl("https://news.example/hrone-expansion"),
        title="HROne expands its HR software platform",
        snippet="HROne announced a new enterprise product in India.",
        backend="test",
    )

    assert not _news_result_matches_company(
        wrong_entity,
        company_name="HROne",
        domain="go.hrone.cloud",
    )
    assert _news_result_matches_company(
        correct_entity,
        company_name="HROne",
        domain="go.hrone.cloud",
    )

    unrelated_product = SearchResult(
        url=HttpUrl("https://news.example/amazon-profit-tool"),
        canonical_url=HttpUrl("https://news.example/amazon-profit-tool"),
        title="A new Amazon seller profit tool launches",
        snippet="Analytics software for every marketplace SKU.",
        backend="test",
    )
    assert not _news_result_matches_company(
        unrelated_product,
        company_name="asintellect — Real P&L for Every Amazon SKU",
        domain="asintellect.com",
    )
