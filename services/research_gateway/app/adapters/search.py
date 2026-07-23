from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from math import ceil
from time import monotonic
from urllib.parse import urlencode

import feedparser  # type: ignore[import-untyped]
import httpx
from pydantic import HttpUrl

from services.research_gateway.app.config import settings
from services.research_gateway.app.errors import GatewayAdapterError
from services.research_gateway.app.normalization import canonicalize_url, normalize_whitespace
from services.research_gateway.app.schemas import (
    AdapterHealth,
    SearchDiagnostics,
    SearchRequest,
    SearchResult,
)
from services.research_gateway.app.security.url_policy import UnsafeUrlError, validate_public_url


class SearchAdapter:
    """Public Bing RSS and GDELT DOC 2.0 search transports.

    It is deliberately isolated behind the same gateway policy as other upstream
    sources. No result is synthesized when the provider is unavailable.
    """

    name = "search"

    def __init__(self) -> None:
        self._gdelt_lock = asyncio.Lock()
        self._last_gdelt_request = 0.0

    @property
    def backend(self) -> str:
        return "gdelt-doc-2" if settings.search_backend == "gdelt_doc" else "bing-rss"

    async def health(self) -> AdapterHealth:
        if settings.search_backend not in {"bing_rss", "gdelt_doc"}:
            return AdapterHealth(
                adapter=self.name,
                status="unavailable",
                backend=settings.search_backend,
                detail="Configured search backend is not implemented",
            )
        return AdapterHealth(
            adapter=self.name,
            status="available",
            backend=self.backend,
            detail=f"Public {self.backend} search transport configured",
        )

    async def search(
        self, request: SearchRequest
    ) -> tuple[list[SearchResult], SearchDiagnostics]:
        if settings.search_backend == "gdelt_doc":
            return await self._search_gdelt(request)
        if settings.search_backend != "bing_rss":
            raise GatewayAdapterError(
                "SEARCH_PROVIDER_UNAVAILABLE",
                "Configured search backend is not implemented",
            )
        return await self._search_bing(request)

    async def _search_bing(
        self, request: SearchRequest
    ) -> tuple[list[SearchResult], SearchDiagnostics]:
        requested_at = datetime.now(UTC)
        query = request.query
        if request.freshness_days and request.freshness_days <= 365:
            query = f"{query} recent"
        endpoint = f"{settings.search_endpoint}?{urlencode({'q': query, 'format': 'rss'})}"
        try:
            validate_public_url(endpoint)
        except UnsafeUrlError as exc:
            raise GatewayAdapterError("URL_POLICY_BLOCKED", str(exc)) from exc
        try:
            async with httpx.AsyncClient(
                timeout=settings.fetch_timeout_seconds,
                headers={"User-Agent": settings.user_agent},
                follow_redirects=False,
            ) as client:
                response = await client.get(endpoint)
        except httpx.TimeoutException as exc:
            raise GatewayAdapterError(
                "FETCH_TIMEOUT", "Search provider timed out", retryable=True
            ) from exc
        except httpx.NetworkError as exc:
            raise GatewayAdapterError(
                "SEARCH_PROVIDER_UNAVAILABLE",
                "Search provider network request failed",
                retryable=True,
            ) from exc
        if response.status_code == 429:
            raise GatewayAdapterError("RATE_LIMITED", "Search rate limit reached", retryable=True)
        if response.status_code != 200:
            raise GatewayAdapterError(
                "SEARCH_PROVIDER_UNAVAILABLE",
                f"Search provider returned HTTP {response.status_code}",
                retryable=response.status_code >= 500,
            )
        feed = feedparser.parse(response.content)
        if getattr(feed, "bozo", False) and not feed.entries:
            raise GatewayAdapterError(
                "SEARCH_PROVIDER_UNAVAILABLE", "Search provider returned an invalid feed"
            )
        now = datetime.now(UTC)
        results: list[SearchResult] = []
        seen: set[str] = set()
        rejection_reasons: dict[str, int] = {}
        for entry in feed.entries:
            url = str(entry.get("link", "")).strip()
            title = normalize_whitespace(str(entry.get("title", "")))
            if not url or not title:
                _reject(rejection_reasons, "missing_url_or_title")
                continue
            try:
                validate_public_url(url)
                canonical = canonicalize_url(url)
            except (UnsafeUrlError, ValueError):
                _reject(rejection_reasons, "url_policy_or_canonicalization")
                continue
            if canonical in seen:
                _reject(rejection_reasons, "duplicate_url")
                continue
            snippet = normalize_whitespace(
                str(entry.get("summary", entry.get("description", "")))
            )[:1500]
            if not _is_relevant(request.query, f"{title} {snippet}"):
                _reject(rejection_reasons, "below_relevance_threshold")
                continue
            seen.add(canonical)
            results.append(
                SearchResult(
                    url=HttpUrl(url),
                    canonical_url=HttpUrl(canonical),
                    title=title[:500],
                    snippet=snippet,
                    retrieved_at=now,
                    backend=self.backend,
                )
            )
            if len(results) >= request.limit:
                break
        before = len(feed.entries)
        return results, SearchDiagnostics(
            requested_at=requested_at,
            http_status=response.status_code,
            provider_query=query,
            results_before_filter=before,
            results_after_filter=len(results),
            rejected_results=max(0, before - len(results)),
            rejection_reasons=rejection_reasons,
        )

    async def _search_gdelt(
        self, request: SearchRequest
    ) -> tuple[list[SearchResult], SearchDiagnostics]:
        requested_at = datetime.now(UTC)
        provider_query = _gdelt_query(request.query)
        params = {
            "query": provider_query,
            "mode": "artlist",
            "format": "json",
            "maxrecords": str(request.limit),
            "sort": "hybridrel",
        }
        endpoint = f"{settings.gdelt_endpoint}?{urlencode(params)}"
        try:
            validate_public_url(endpoint)
        except UnsafeUrlError as exc:
            raise GatewayAdapterError("URL_POLICY_BLOCKED", str(exc)) from exc
        response = await self._request_gdelt(endpoint)
        if response.status_code != 200:
            raise GatewayAdapterError(
                "SEARCH_PROVIDER_UNAVAILABLE",
                f"GDELT returned HTTP {response.status_code}",
                retryable=response.status_code >= 500,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            if _is_throttle_response(response):
                raise GatewayAdapterError(
                    "RATE_LIMITED",
                    "GDELT search rate limit reached",
                    retryable=True,
                ) from exc
            preview = normalize_whitespace(response.text)[:240]
            raise GatewayAdapterError(
                "SEARCH_PROVIDER_UNAVAILABLE",
                "GDELT returned a non-JSON response"
                + (f": {preview}" if preview else ""),
            ) from exc
        articles = payload.get("articles", []) if isinstance(payload, dict) else []
        if not isinstance(articles, list):
            articles = []
        now = datetime.now(UTC)
        results: list[SearchResult] = []
        seen: set[str] = set()
        rejection_reasons: dict[str, int] = {}
        for article in articles:
            if not isinstance(article, dict):
                _reject(rejection_reasons, "invalid_article_record")
                continue
            url = str(article.get("url") or "").strip()
            title = normalize_whitespace(str(article.get("title") or ""))
            if not url or not title:
                _reject(rejection_reasons, "missing_url_or_title")
                continue
            try:
                validate_public_url(url)
                canonical = canonicalize_url(url)
            except (UnsafeUrlError, ValueError):
                _reject(rejection_reasons, "url_policy_or_canonicalization")
                continue
            if canonical in seen:
                _reject(rejection_reasons, "duplicate_url")
                continue
            snippet = normalize_whitespace(
                " ".join(
                    str(article.get(key) or "")
                    for key in ("domain", "sourcecountry", "language")
                )
            )[:1500]
            if not _is_relevant(request.query, f"{title} {snippet}"):
                _reject(rejection_reasons, "below_relevance_threshold")
                continue
            seen.add(canonical)
            results.append(
                SearchResult(
                    url=HttpUrl(url),
                    canonical_url=HttpUrl(canonical),
                    title=title[:500],
                    snippet=snippet,
                    published_at=_gdelt_datetime(article.get("seendate")),
                    retrieved_at=now,
                    backend=self.backend,
                )
            )
            if len(results) >= request.limit:
                break
        before = len(articles)
        return results, SearchDiagnostics(
            requested_at=requested_at,
            http_status=response.status_code,
            provider_query=provider_query,
            results_before_filter=before,
            results_after_filter=len(results),
            rejected_results=max(0, before - len(results)),
            rejection_reasons=rejection_reasons,
        )

    async def _request_gdelt(self, endpoint: str) -> httpx.Response:
        attempts = max(1, settings.gdelt_max_attempts)
        async with self._gdelt_lock:
            async with httpx.AsyncClient(
                timeout=settings.fetch_timeout_seconds,
                headers={"User-Agent": settings.user_agent},
                follow_redirects=False,
            ) as client:
                for attempt in range(attempts):
                    elapsed = monotonic() - self._last_gdelt_request
                    interval = max(0.0, settings.gdelt_min_interval_seconds)
                    if elapsed < interval:
                        await asyncio.sleep(interval - elapsed)
                    try:
                        response = await client.get(endpoint)
                    except httpx.TimeoutException as exc:
                        raise GatewayAdapterError(
                            "FETCH_TIMEOUT",
                            "GDELT search timed out",
                            retryable=True,
                        ) from exc
                    except httpx.NetworkError as exc:
                        raise GatewayAdapterError(
                            "SEARCH_PROVIDER_UNAVAILABLE",
                            "GDELT search request failed",
                            retryable=True,
                        ) from exc
                    self._last_gdelt_request = monotonic()
                    throttled = (
                        response.status_code == 429
                        or _is_throttle_response(response)
                    )
                    if not throttled:
                        return response
                    if attempt + 1 >= attempts:
                        raise GatewayAdapterError(
                            "RATE_LIMITED",
                            "GDELT search rate limit reached after bounded retries",
                            retryable=True,
                        )
                    retry_after = _retry_after_seconds(response)
                    await asyncio.sleep(
                        retry_after
                        if retry_after is not None
                        else min(30.0, interval * (attempt + 2))
                    )
        raise GatewayAdapterError(
            "SEARCH_PROVIDER_UNAVAILABLE",
            "GDELT search did not return a response",
            retryable=True,
        )


SEARCH_STOP_WORDS = {
    "and",
    "the",
    "for",
    "with",
    "from",
    "into",
    "market",
    "companies",
    "company",
    "recent",
    "alternatives",
}


def _reject(reasons: dict[str, int], reason: str) -> None:
    reasons[reason] = reasons.get(reason, 0) + 1


def _gdelt_query(query: str) -> str:
    quoted = re.sub(
        r'(?<!["\w])([A-Za-z0-9]+(?:-[A-Za-z0-9]+)+)(?!["\w])',
        r'"\1"',
        query,
    )
    return " ".join(
        token
        for token in quoted.split()
        if len(token.strip('"')) >= 3
    )


def _is_throttle_response(response: httpx.Response) -> bool:
    preview = response.text[:500].lower()
    return any(
        marker in preview
        for marker in ("rate limit", "too many requests", "please wait")
    )


def _retry_after_seconds(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after", "").strip()
    try:
        return min(30.0, max(0.0, float(raw)))
    except ValueError:
        return None


def _terms(value: str) -> set[str]:
    return {
        item.lower()
        for item in re.findall(r"[A-Za-z0-9]{3,}", value)
        if item.lower() not in SEARCH_STOP_WORDS
    }


def _is_relevant(query: str, result_text: str) -> bool:
    query_terms = _terms(query)
    matches = query_terms & _terms(result_text)
    required = 1 if len(query_terms) <= 2 else max(3, ceil(len(query_terms) * 0.4))
    return len(matches) >= required


def _gdelt_datetime(value: object) -> datetime | None:
    raw = str(value or "").strip()
    for pattern in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(raw, pattern).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None
