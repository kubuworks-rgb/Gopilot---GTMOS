from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import Awaitable, Callable, Protocol

import httpx
from pydantic import HttpUrl

from services.research_gateway.app.config import settings
from services.research_gateway.app.errors import GatewayAdapterError
from services.research_gateway.app.normalization import (
    canonicalize_url,
    normalize_whitespace,
)
from services.research_gateway.app.schemas import (
    ProviderAttempt,
    SearchDiagnostics,
    SearchRequest,
    SearchResult,
)
from services.research_gateway.app.security.url_policy import (
    UnsafeUrlError,
    validate_public_url,
)


SearchPayload = tuple[list[SearchResult], SearchDiagnostics]


class GeneralSearchProvider(Protocol):
    name: str

    @property
    def authenticated(self) -> bool: ...

    async def search(self, request: SearchRequest) -> SearchPayload: ...


@dataclass
class CallableSearchProvider:
    """Adapts a reviewed transport to the provider protocol."""

    name: str
    configured: bool
    callback: Callable[[SearchRequest], Awaitable[SearchPayload]]

    @property
    def authenticated(self) -> bool:
        return self.configured

    async def search(self, request: SearchRequest) -> SearchPayload:
        if not self.configured and settings.production_acceptance:
            raise GatewayAdapterError(
                "CONFIG_REQUIRED_FOR_PRODUCTION_ACCEPTANCE",
                f"Authenticated {self.name} search is not configured",
            )
        return await self.callback(request)


class TavilySearchProvider:
    name = "tavily"

    @property
    def authenticated(self) -> bool:
        return bool(settings.tavily_api_key)

    async def search(self, request: SearchRequest) -> SearchPayload:
        if not settings.tavily_api_key:
            raise GatewayAdapterError(
                "CONFIG_REQUIRED_FOR_PRODUCTION_ACCEPTANCE",
                "Authenticated Tavily search is not configured",
            )
        try:
            validate_public_url(settings.tavily_endpoint)
        except UnsafeUrlError as exc:
            raise GatewayAdapterError("URL_POLICY_BLOCKED", str(exc)) from exc

        requested_at = datetime.now(UTC)
        started = monotonic()
        try:
            async with httpx.AsyncClient(
                timeout=settings.fetch_timeout_seconds,
                headers={
                    "Authorization": f"Bearer {settings.tavily_api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": settings.user_agent,
                },
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    settings.tavily_endpoint,
                    json={
                        "query": request.query,
                        "topic": "general",
                        "search_depth": "basic",
                        "max_results": request.limit,
                        "include_answer": False,
                        "include_raw_content": False,
                    },
                )
        except httpx.TimeoutException as exc:
            raise GatewayAdapterError(
                "FETCH_TIMEOUT", "Tavily search timed out", retryable=True
            ) from exc
        except httpx.NetworkError as exc:
            raise GatewayAdapterError(
                "SEARCH_PROVIDER_UNAVAILABLE",
                "Tavily search network request failed",
                retryable=True,
            ) from exc
        if response.status_code == 429:
            raise GatewayAdapterError(
                "RATE_LIMITED", "Tavily search rate limit reached", retryable=True
            )
        if response.status_code in {401, 403}:
            raise GatewayAdapterError(
                "SEARCH_PROVIDER_AUTH_FAILED",
                "Tavily rejected the configured API credential",
            )
        if response.status_code != 200:
            raise GatewayAdapterError(
                "SEARCH_PROVIDER_UNAVAILABLE",
                f"Tavily returned HTTP {response.status_code}",
                retryable=response.status_code >= 500,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise GatewayAdapterError(
                "SEARCH_PROVIDER_INVALID_RESPONSE",
                "Tavily returned invalid JSON",
            ) from exc

        raw_results = payload.get("results", []) if isinstance(payload, dict) else []
        if not isinstance(raw_results, list):
            raw_results = []
        results: list[SearchResult] = []
        seen: set[str] = set()
        rejected: dict[str, int] = {}
        for item in raw_results:
            if not isinstance(item, dict):
                rejected["invalid_record"] = rejected.get("invalid_record", 0) + 1
                continue
            url = str(item.get("url") or "").strip()
            title = normalize_whitespace(str(item.get("title") or ""))
            if not url or not title:
                rejected["missing_url_or_title"] = (
                    rejected.get("missing_url_or_title", 0) + 1
                )
                continue
            try:
                validate_public_url(url)
                canonical = canonicalize_url(url)
            except (UnsafeUrlError, ValueError):
                rejected["url_policy_or_canonicalization"] = (
                    rejected.get("url_policy_or_canonicalization", 0) + 1
                )
                continue
            if canonical in seen:
                rejected["duplicate_url"] = rejected.get("duplicate_url", 0) + 1
                continue
            seen.add(canonical)
            raw_score = item.get("score")
            score = (
                max(0.0, min(1.0, float(raw_score)))
                if isinstance(raw_score, (int, float))
                else None
            )
            results.append(
                SearchResult(
                    url=HttpUrl(url),
                    canonical_url=HttpUrl(canonical),
                    title=title[:500],
                    snippet=normalize_whitespace(
                        str(item.get("content") or "")
                    )[:4000],
                    backend="tavily-api",
                    provider=self.name,
                    provider_relevance_score=score,
                )
            )
        latency = int((monotonic() - started) * 1000)
        diagnostics = SearchDiagnostics(
            requested_at=requested_at,
            http_status=response.status_code,
            provider_query=request.query,
            results_before_filter=len(raw_results),
            results_after_filter=len(results),
            rejected_results=max(0, len(raw_results) - len(results)),
            rejection_reasons=rejected,
            provider_attempts=[
                ProviderAttempt(
                    provider=self.name,
                    authenticated=True,
                    outcome=(
                        "completed"
                        if len(results) >= settings.minimum_general_search_results
                        else "insufficient_results"
                    ),
                    result_count=len(results),
                    latency_ms=latency,
                )
            ],
            estimated_cost_usd=0,
        )
        return results, diagnostics


class CompositeGeneralSearchProvider:
    """Primary/fallback search with transparent diagnostics and no synthesis."""

    name = "composite"

    def __init__(
        self,
        primary: GeneralSearchProvider,
        secondary: GeneralSearchProvider | None,
        minimum_results: int,
    ) -> None:
        self.primary = primary
        self.secondary = secondary
        self.minimum_results = max(1, minimum_results)

    @property
    def authenticated(self) -> bool:
        return self.primary.authenticated and bool(
            self.secondary and self.secondary.authenticated
        )

    async def search(self, request: SearchRequest) -> SearchPayload:
        attempts: list[ProviderAttempt] = []
        primary_results: list[SearchResult] = []
        primary_diagnostics: SearchDiagnostics | None = None
        primary_error: GatewayAdapterError | None = None
        try:
            started = monotonic()
            primary_results, primary_diagnostics = await self.primary.search(request)
            attempts.extend(primary_diagnostics.provider_attempts)
            if not primary_diagnostics.provider_attempts:
                attempts.append(
                    ProviderAttempt(
                        provider=self.primary.name,
                        authenticated=self.primary.authenticated,
                        outcome=(
                            "completed"
                            if len(primary_results) >= self.minimum_results
                            else "insufficient_results"
                        ),
                        result_count=len(primary_results),
                        latency_ms=int((monotonic() - started) * 1000),
                    )
                )
            if len(primary_results) >= self.minimum_results:
                primary_diagnostics.provider_attempts = attempts
                return primary_results, primary_diagnostics
        except GatewayAdapterError as exc:
            attempts.append(
                ProviderAttempt(
                    provider=self.primary.name,
                    authenticated=self.primary.authenticated,
                    outcome="failed",
                    error_code=exc.code,
                )
            )
            primary_error = exc

        if self.secondary is None or not self.secondary.authenticated:
            attempts.append(
                ProviderAttempt(
                    provider=self.secondary.name if self.secondary else "none",
                    authenticated=False,
                    outcome="not_configured",
                    error_code="CONFIG_REQUIRED_FOR_PRODUCTION_ACCEPTANCE",
                )
            )
            if settings.production_acceptance:
                raise GatewayAdapterError(
                    "CONFIG_REQUIRED_FOR_PRODUCTION_ACCEPTANCE",
                    "A keyed secondary general-web provider is required for production acceptance",
                )
            if primary_diagnostics is not None:
                primary_diagnostics.provider_attempts = attempts
                primary_diagnostics.completion_status = "partial"
                return primary_results, primary_diagnostics
            if primary_error is not None:
                raise primary_error

        assert self.secondary is not None
        secondary_started = monotonic()
        secondary_results, secondary_diagnostics = await self.secondary.search(request)
        attempts.extend(secondary_diagnostics.provider_attempts)
        if not secondary_diagnostics.provider_attempts:
            attempts.append(
                ProviderAttempt(
                    provider=self.secondary.name,
                    authenticated=self.secondary.authenticated,
                    outcome=(
                        "completed"
                        if len(secondary_results) >= self.minimum_results
                        else "insufficient_results"
                    ),
                    result_count=len(secondary_results),
                    latency_ms=int((monotonic() - secondary_started) * 1000),
                )
            )
        combined: list[SearchResult] = []
        seen: set[str] = set()
        for item in [*primary_results, *secondary_results]:
            key = str(item.canonical_url)
            if key not in seen:
                seen.add(key)
                combined.append(item)
            if len(combined) >= request.limit:
                break
        secondary_diagnostics.provider_attempts = attempts
        secondary_diagnostics.fallback_used = True
        secondary_diagnostics.completion_status = "completed_with_provider_fallback"
        secondary_diagnostics.results_after_filter = len(combined)
        return combined, secondary_diagnostics
