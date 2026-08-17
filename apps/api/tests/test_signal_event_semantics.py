"""Signals must describe events that happened, not pages we happened to fetch.

Regression cover for the defect where a static marketing line ("Trusted by 100+
customers") became a maximum-recency current intent signal, because
`CUSTOMER_GROWTH_INDICATOR` was exempt from the event-page requirement and signal
recency was derived from retrieval time rather than event time.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from apps.api.app.db.models import EvidenceFactRow, SourceDocumentRow
from apps.api.app.services.live_research import _signals_from_facts, signal_event_date
from apps.api.app.services.scoring import score_account


WORKSPACE = uuid4()


def _source(
    url: str, *, published_at: datetime | None, text: str = ""
) -> SourceDocumentRow:
    return SourceDocumentRow(
        id=uuid4(),
        workspace_id=WORKSPACE,
        research_run_id=uuid4(),
        platform="web",
        source_type="webpage",
        backend="safe-httpx",
        url=url,
        canonical_url=url,
        title="Acme",
        author=None,
        published_at=published_at,
        retrieved_at=datetime.now(UTC),
        language="en",
        content_hash="hash",
        cleaned_text=text,
        raw_storage_key=None,
        trust_score=0.9,
        permission_classification="public",
        status="retrieved",
        provenance={"source_role": "FIRST_PARTY"},
        source_metadata={},
    )


def _fact(source: SourceDocumentRow, claim: str) -> EvidenceFactRow:
    return EvidenceFactRow(
        id=uuid4(),
        workspace_id=WORKSPACE,
        source_id=source.id,
        subject="Acme",
        predicate="states",
        object=claim,
        claim=claim,
        passage=claim,
        confidence="0.82",
        status="supported",
        # Mirrors production: undated pages fall back to retrieval time.
        observed_at=source.published_at or source.retrieved_at,
        valid_from=source.published_at,
        valid_until=None,
    )


TRUSTED_BY = "Trusted by 100+ customers who rely on Acme every day."


def test_static_homepage_customer_boast_is_not_a_current_signal() -> None:
    """The original defect: a static homepage line became a fresh intent signal."""

    source = _source("https://acme.example/", published_at=None)
    fact = _fact(source, TRUSTED_BY)

    assert _signals_from_facts(
        [fact],
        {source.id: source},
        company_name="Acme",
        domain="acme.example",
    ) == []


def test_undated_event_page_yields_a_signal_with_no_event_date() -> None:
    """A careers page is a real event surface, but carries no verifiable date."""

    source = _source("https://acme.example/careers", published_at=None)
    fact = _fact(source, "Acme is hiring customer success managers for three roles.")

    matches = _signals_from_facts(
        [fact],
        {source.id: source},
        company_name="Acme",
        domain="acme.example",
    )

    assert [item[0] for item in matches] == ["CUSTOMER_SUCCESS_HIRING"]
    assert matches[0][2] is None, "an undated page must not claim an event date"


def test_dated_press_release_carries_its_real_event_date() -> None:
    published = datetime.now(UTC) - timedelta(days=30)
    source = _source("https://acme.example/press/series-b", published_at=published)
    fact = _fact(source, "Acme raised a Series B funding round.")

    matches = _signals_from_facts(
        [fact],
        {source.id: source},
        company_name="Acme",
        domain="acme.example",
    )

    assert [item[0] for item in matches] == ["FUNDING"]
    assert matches[0][2] == published


def test_stale_dated_events_are_dropped() -> None:
    source = _source(
        "https://acme.example/news/2019-launch",
        published_at=datetime.now(UTC) - timedelta(days=1200),
    )
    fact = _fact(source, "Acme launched a new product for enterprise teams.")

    assert _signals_from_facts(
        [fact],
        {source.id: source},
        company_name="Acme",
        domain="acme.example",
    ) == []


def test_event_date_never_falls_back_to_retrieval_time() -> None:
    undated = _source("https://acme.example/careers", published_at=None)
    assert signal_event_date(undated) is None
    assert signal_event_date(None) is None

    published = datetime.now(UTC) - timedelta(days=5)
    assert signal_event_date(_source("https://acme.example/news/x", published_at=published)) == published


def test_unknown_recency_renormalizes_intent_instead_of_fabricating_freshness() -> None:
    """Unknown recency is neither maximum freshness nor a penalty."""

    def scored(recency: float | None) -> int:
        return score_account(
            industry_match=80,
            size_match=80,
            geography_match=80,
            signal_strength=70,
            signal_recency=recency,
            evidence_coverage=80,
            source_quality=80,
            fit_evidence=["fit"],
            signal_evidence=["intent"],
        ).intent.score

    unknown = scored(None)
    fabricated_fresh = scored(100)
    stale = scored(0)

    # Unknown recency must fall back to signal strength alone, not to a fresh event.
    assert unknown == 70
    assert unknown < fabricated_fresh
    assert unknown > stale


def test_no_signal_still_produces_zero_intent() -> None:
    scores = score_account(
        industry_match=90,
        size_match=90,
        geography_match=90,
        signal_strength=0,
        signal_recency=0,
        evidence_coverage=80,
        source_quality=80,
        fit_evidence=["fit"],
        signal_evidence=[],
    )

    assert scores.intent.score == 0
    assert scores.fit.score > 0, "NO_SIGNAL must not erase a verified fit"
