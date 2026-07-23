from __future__ import annotations

import httpx
import pytest

from apps.api.app.providers.live import GatewayProviderError, LiveResearchProvider
from apps.api.app.services.live_research import (
    SOURCE_CHUNK_SIZE,
    SOURCE_CHUNK_STEP,
    _evidence_passages,
)
from services.research_gateway.app.adapters.search import (
    _gdelt_datetime,
    _gdelt_query,
    _is_throttle_response,
    _is_relevant,
    _retry_after_seconds,
)
from services.research_gateway.app.normalization import (
    canonicalize_url,
    normalize_whitespace,
)
from services.research_gateway.app.schemas import GatewayError, SourceResponse


def test_canonical_url_removes_tracking_and_fragment() -> None:
    assert (
        canonicalize_url(
            "HTTPS://Example.COM:443/path/?utm_source=test&b=2&a=1#private-fragment"
        )
        == "https://example.com/path?a=1&b=2"
    )


def test_text_normalization_is_stable() -> None:
    assert normalize_whitespace("  one\r\n two\tthree  ") == "one two three"


def test_failed_live_provider_response_never_falls_back() -> None:
    response = SourceResponse(
        status="failed",
        errors=[
            GatewayError(
                code="SOURCE_UNAVAILABLE",
                message="Public source unavailable",
                retryable=True,
            )
        ],
    )
    with pytest.raises(GatewayProviderError) as caught:
        LiveResearchProvider._raise_errors(response)
    assert caught.value.category == "SOURCE_UNAVAILABLE"
    assert caught.value.retryable is True


def test_search_relevance_rejects_generic_keyword_noise() -> None:
    query = "Founder-led B2B SaaS companies in India"

    assert not _is_relevant(
        query,
        "Evidence for a proposition is what supports the proposition.",
    )
    assert not _is_relevant(
        query,
        "A founder in India may establish an organization.",
    )
    assert _is_relevant(
        query,
        "India's founder-led B2B SaaS startups expand into new markets",
    )


def test_gdelt_timestamp_is_parsed_as_utc() -> None:
    parsed = _gdelt_datetime("20260723T131710Z")

    assert parsed is not None
    assert parsed.isoformat() == "2026-07-23T13:17:10+00:00"
    assert _gdelt_datetime("not-a-timestamp") is None


def test_evidence_passages_rank_relevant_content_and_drop_boilerplate() -> None:
    text = (
        "Log into your account and sign in with your password. "
        "India's B2B SaaS founders are expanding into international markets. "
        "The founder-led companies use account prioritization to focus GTM teams."
    )

    passages = _evidence_passages(
        text,
        "Founder-led B2B SaaS companies in India account prioritization",
    )

    assert len(passages) == 2
    assert all("password" not in passage.lower() for passage in passages)
    assert passages[0].startswith("The founder-led companies")


def test_gdelt_throttle_responses_are_classified_and_bounded() -> None:
    response = httpx.Response(
        200,
        text="Please wait: API rate limit reached",
        headers={"retry-after": "120"},
    )

    assert _is_throttle_response(response)
    assert _retry_after_seconds(response) == 30.0


def test_source_chunk_overlap_contains_maximum_evidence_passage() -> None:
    text = "a" * 1099 + "e" * 700 + "z" * 1200
    passage = "e" * 700
    chunks = [
        text[start : start + SOURCE_CHUNK_SIZE]
        for start in range(0, len(text), SOURCE_CHUNK_STEP)
    ]

    assert any(passage in chunk for chunk in chunks)


def test_gdelt_query_quotes_hyphenated_terms_only() -> None:
    query = "Evidence-backed GTM for Founder-led B2B SaaS in India"

    assert (
        _gdelt_query(query)
        == '"Evidence-backed" GTM for "Founder-led" B2B SaaS India'
    )
