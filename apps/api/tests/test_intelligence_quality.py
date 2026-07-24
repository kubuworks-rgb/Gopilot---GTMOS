from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from apps.api.app.services.company_identity import (
    ResultPageRole,
    classify_result_page,
    registrable_domain,
    resolve_company_identity,
)
from apps.api.app.services.intelligence_quality import (
    CriterionEvaluation,
    CriterionRequirement,
    CriterionState,
    SourceRole,
    candidate_relevance_score,
    claim_source_compatible,
    decide_qualification,
)
from apps.api.app.services.live_research import (
    _news_result_matches_company,
    _signals_from_facts,
)
from apps.api.app.services.scoring import priority_band, score_account
from services.research_gateway.app.errors import GatewayAdapterError
from services.research_gateway.app.providers.general_search import (
    CallableSearchProvider,
    CompositeGeneralSearchProvider,
)
from services.research_gateway.app.schemas import (
    SearchDiagnostics,
    SearchRequest,
    SearchResult,
)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://go.hrone.cloud/demo", "hrone.cloud"),
        ("https://www.example.com", "example.com"),
        ("https://careers.acme.co.in/jobs", "acme.co.in"),
        ("https://support.acme.co.uk", "acme.co.uk"),
        ("https://app.acme.com.au", "acme.com.au"),
        ("https://news.acme.com.br", "acme.com.br"),
        ("https://acme.co.jp", "acme.co.jp"),
        ("https://acme.co.nz", "acme.co.nz"),
        ("https://acme.co.za", "acme.co.za"),
        ("https://acme.com.sg", "acme.com.sg"),
        ("https://acme.com.mx", "acme.com.mx"),
        ("https://acme.com.tr", "acme.com.tr"),
        ("https://acme.com.cn", "acme.com.cn"),
        ("https://acme.com.hk", "acme.com.hk"),
        ("https://acme.com.tw", "acme.com.tw"),
        ("https://acme.com.my", "acme.com.my"),
        ("https://acme.com.ph", "acme.com.ph"),
        ("https://acme.com.pk", "acme.com.pk"),
        ("https://acme.com.bd", "acme.com.bd"),
        ("https://acme.org.uk", "acme.org.uk"),
    ],
)
def test_psl_aware_registrable_domain_matrix(url: str, expected: str) -> None:
    assert registrable_domain(url) == expected


def test_hrone_subdomain_resolves_to_canonical_company_domain() -> None:
    identity = resolve_company_identity("https://go.hrone.cloud/pricing")

    assert identity.hostname == "go.hrone.cloud"
    assert identity.registrable_domain == "hrone.cloud"
    assert identity.canonical_company_domain == "hrone.cloud"
    assert identity.page_role == ResultPageRole.OFFICIAL_SUBDOMAIN
    assert identity.confidence >= 0.80


def test_directory_and_news_pages_are_not_canonical_company_domains() -> None:
    assert classify_result_page("https://www.crunchbase.com/organization/acme") == (
        ResultPageRole.DIRECTORY
    )
    assert resolve_company_identity(
        "https://www.crunchbase.com/organization/acme"
    ).canonical_company_domain is None
    assert classify_result_page("https://techcrunch.com/2026/acme") == (
        ResultPageRole.NEWS
    )
    assert resolve_company_identity(
        "https://techcrunch.com/2026/acme"
    ).canonical_company_domain is None


def test_unknown_hard_criterion_is_not_false() -> None:
    decision = decide_qualification(
        [
            CriterionEvaluation(
                "official_domain",
                CriterionRequirement.HARD,
                CriterionState.TRUE,
            ),
            CriterionEvaluation(
                "b2b_software",
                CriterionRequirement.HARD,
                CriterionState.TRUE,
            ),
            CriterionEvaluation(
                "employee_count",
                CriterionRequirement.HARD,
                CriterionState.UNKNOWN,
            ),
        ]
    )

    assert decision.status == "QUALIFIED_WITH_UNCERTAINTY"
    assert decision.hard_coverage == pytest.approx(2 / 3, abs=0.0001)


def test_unknown_size_is_removed_from_fit_denominator() -> None:
    scores = score_account(
        industry_match=100,
        size_match=None,
        geography_match=100,
        signal_strength=0,
        signal_recency=0,
        evidence_coverage=80,
        source_quality=80,
        fit_evidence=["fit"],
        signal_evidence=[],
    )

    assert scores.fit.score == 100
    assert {item.label for item in scores.fit.components} == {
        "Industry match",
        "Geography match",
    }


def test_vendor_marketing_cannot_support_market_size_claim() -> None:
    assert not claim_source_compatible(
        "MARKET_SIZE", SourceRole.VENDOR_MARKETING
    )
    assert claim_source_compatible(
        "MARKET_SIZE", SourceRole.INDEPENDENT_MARKET_SOURCE
    )


def test_hrone_does_not_match_distinct_hr_one_entity_or_robotaxi_ipo() -> None:
    hr_one = SearchResult(
        url="https://example-news.test/hr-one",
        canonical_url="https://example-news.test/hr-one",
        title="HR One expands payroll operations",
        snippet="HR One announced a new office.",
        backend="controlled",
    )
    robotaxi = SearchResult(
        url="https://example-news.test/robotaxi",
        canonical_url="https://example-news.test/robotaxi",
        title="Robotaxi startup prepares IPO",
        snippet="The autonomous vehicle company is expanding.",
        backend="controlled",
    )

    assert not _news_result_matches_company(
        hr_one, company_name="HROne", domain="go.hrone.cloud"
    )
    assert not _news_result_matches_company(
        robotaxi, company_name="HROne", domain="go.hrone.cloud"
    )


def test_zero_signal_is_valid_and_maps_to_monitor() -> None:
    assert _signals_from_facts([]) == []
    scores = score_account(
        industry_match=80,
        size_match=None,
        geography_match=80,
        signal_strength=0,
        signal_recency=0,
        evidence_coverage=70,
        source_quality=75,
        fit_evidence=["fit"],
        signal_evidence=[],
    )
    band, action = priority_band(
        scores,
        qualification_status="QUALIFIED_WITH_UNCERTAINTY",
        has_verified_signal=False,
    )
    assert band == "MONITOR"
    assert "verify" in action.lower()


def test_candidate_score_rewards_query_and_provider_agreement() -> None:
    single = candidate_relevance_score(
        title="Acme B2B SaaS",
        snippet="India software platform",
        target_terms={"india", "saas", "support"},
        official_page=True,
        provider_score=0.7,
        query_hits=1,
        provider_hits=1,
    )
    agreed = candidate_relevance_score(
        title="Acme B2B SaaS",
        snippet="India software platform",
        target_terms={"india", "saas", "support"},
        official_page=True,
        provider_score=0.7,
        query_hits=3,
        provider_hits=2,
    )
    assert agreed > single


class _ControlledProvider:
    def __init__(
        self,
        name: str,
        *,
        results: list[SearchResult] | None = None,
        error: GatewayAdapterError | None = None,
    ) -> None:
        self.name = name
        self.authenticated = True
        self.results = results or []
        self.error = error

    async def search(
        self, request: SearchRequest
    ) -> tuple[list[SearchResult], SearchDiagnostics]:
        if self.error:
            raise self.error
        return self.results, SearchDiagnostics(
            requested_at=datetime.now(UTC),
            http_status=200,
            provider_query=request.query,
            results_before_filter=len(self.results),
            results_after_filter=len(self.results),
            rejected_results=0,
        )


@pytest.mark.asyncio
async def test_secondary_keyed_provider_fallback_is_diagnostic() -> None:
    result = SearchResult(
        url="https://acme.example",
        canonical_url="https://acme.example",
        title="Acme",
        snippet="India B2B SaaS support platform",
        backend="secondary",
        provider="secondary",
    )
    composite = CompositeGeneralSearchProvider(
        _ControlledProvider(
            "primary",
            error=GatewayAdapterError(
                "RATE_LIMITED", "Primary exhausted", retryable=True
            ),
        ),
        _ControlledProvider("secondary", results=[result]),
        minimum_results=1,
    )

    results, diagnostics = await composite.search(
        SearchRequest(
            workspace_id="workspace",
            research_run_id="run",
            query="India B2B SaaS",
            limit=5,
        )
    )

    assert results == [result]
    assert diagnostics.fallback_used is True
    assert diagnostics.completion_status == "completed_with_provider_fallback"
    assert [item.provider for item in diagnostics.provider_attempts] == [
        "primary",
        "secondary",
    ]


@pytest.mark.asyncio
async def test_anonymous_exa_is_rejected_for_production_acceptance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def never_called(
        request: SearchRequest,
    ) -> tuple[list[SearchResult], SearchDiagnostics]:
        raise AssertionError(request)

    import services.research_gateway.app.providers.general_search as module

    monkeypatch.setattr(
        module,
        "settings",
        SimpleNamespace(production_acceptance=True),
    )
    provider = CallableSearchProvider("exa", False, never_called)
    with pytest.raises(GatewayAdapterError) as caught:
        await provider.search(
            SearchRequest(
                workspace_id="workspace",
                research_run_id="run",
                query="authenticated provider check",
            )
        )
    assert caught.value.code == "CONFIG_REQUIRED_FOR_PRODUCTION_ACCEPTANCE"
