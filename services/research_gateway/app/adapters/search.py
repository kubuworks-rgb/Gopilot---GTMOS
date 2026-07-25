from __future__ import annotations

import asyncio
import importlib.util
import json
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
from services.research_gateway.app.normalization import (
    canonicalize_url,
    normalize_whitespace,
)
from services.research_gateway.app.schemas import (
    AdapterHealth,
    SearchDiagnostics,
    SearchRequest,
    SearchResult,
)
from services.research_gateway.app.providers.general_search import (
    CallableSearchProvider,
    CompositeGeneralSearchProvider,
    TavilySearchProvider,
    authenticated_provider_order,
    production_acceptance_ready,
)
from services.research_gateway.app.security.url_policy import (
    UnsafeUrlError,
    validate_public_url,
)


class SearchAdapter:
    """Source-aware Exa general-web, Bing RSS, and GDELT news transports.

    It is deliberately isolated behind the same gateway policy as other upstream
    sources. Exa MCP exposes only the reviewed search capability; GDELT remains a
    news-only route. No result is synthesized when a provider is unavailable.
    """

    name = "search"

    def __init__(self) -> None:
        self._exa_lock = asyncio.Lock()
        self._last_exa_request = 0.0
        self._gdelt_lock = asyncio.Lock()
        self._last_gdelt_request = 0.0
        secondary = (
            TavilySearchProvider()
            if settings.secondary_search_provider == "tavily"
            else None
        )
        self._general_search = CompositeGeneralSearchProvider(
            CallableSearchProvider(
                name="exa",
                configured=bool(settings.exa_api_key),
                callback=self._search_exa_routed,
            ),
            secondary,
            settings.minimum_general_search_results,
        )

    @property
    def backend(self) -> str:
        if settings.search_backend == "exa_mcp":
            return "exa-mcp+tavily-api"
        return "gdelt-doc-2" if settings.search_backend == "gdelt_doc" else "bing-rss"

    async def health(self) -> AdapterHealth:
        if settings.search_backend not in {"exa_mcp", "bing_rss", "gdelt_doc"}:
            return AdapterHealth(
                adapter=self.name,
                status="unavailable",
                backend=settings.search_backend,
                detail="Configured search backend is not implemented",
            )
        authenticated = bool(settings.exa_api_key)
        secondary_authenticated = bool(settings.tavily_api_key)
        psl_installed = importlib.util.find_spec("tldextract") is not None
        production_ready = production_acceptance_ready(
            exa_authenticated=authenticated,
            tavily_authenticated=secondary_authenticated,
            psl_dependency_installed=psl_installed,
        )
        provider_order = authenticated_provider_order(
            exa_authenticated=authenticated,
            tavily_authenticated=secondary_authenticated,
        )
        return AdapterHealth(
            adapter=self.name,
            status=(
                "available"
                if production_ready or not settings.production_acceptance
                else "degraded"
            ),
            backend=self.backend,
            detail=(
                (
                    "Authenticated provider order: " + ", ".join(provider_order)
                    if production_ready
                    else "CONFIG_REQUIRED_FOR_PRODUCTION_ACCEPTANCE: "
                    f"exa_authenticated={authenticated}, "
                    f"tavily_authenticated={secondary_authenticated}, "
                    f"psl_dependency_installed={psl_installed}"
                )
                if settings.search_backend == "exa_mcp"
                else f"Public {self.backend} search transport configured"
            ),
        )

    async def search(
        self, request: SearchRequest
    ) -> tuple[list[SearchResult], SearchDiagnostics]:
        if request.purpose == "news":
            try:
                return await self._search_gdelt(request)
            except GatewayAdapterError as exc:
                if settings.search_backend != "exa_mcp" or exc.code not in {
                    "RATE_LIMITED",
                    "SEARCH_PROVIDER_UNAVAILABLE",
                }:
                    raise
                return await self._search_exa_routed(request)
        if settings.search_backend == "exa_mcp":
            return await self._general_search.search(request)
        if settings.search_backend == "gdelt_doc":
            return await self._search_gdelt(request)
        if settings.search_backend != "bing_rss":
            raise GatewayAdapterError(
                "SEARCH_PROVIDER_UNAVAILABLE",
                "Configured search backend is not implemented",
            )
        return await self._search_bing(request)

    async def _search_exa_routed(
        self, request: SearchRequest
    ) -> tuple[list[SearchResult], SearchDiagnostics]:
        async with self._exa_lock:
            elapsed = monotonic() - self._last_exa_request
            interval = max(0.0, settings.exa_min_interval_seconds)
            if elapsed < interval:
                await asyncio.sleep(interval - elapsed)
            for attempt in range(2):
                try:
                    result = await self._search_exa(request)
                    self._last_exa_request = monotonic()
                    return result
                except GatewayAdapterError as exc:
                    self._last_exa_request = monotonic()
                    if attempt or (
                        exc.code != "SEARCH_PROVIDER_INVALID_RESPONSE"
                        and not exc.retryable
                    ):
                        raise
                    await asyncio.sleep(max(2.0, interval))
        raise GatewayAdapterError(
            "SEARCH_PROVIDER_UNAVAILABLE",
            "Exa search did not return a response",
            retryable=True,
        )

    async def _search_exa(
        self, request: SearchRequest
    ) -> tuple[list[SearchResult], SearchDiagnostics]:
        """Call Exa's fixed remote MCP search tool using Streamable HTTP."""

        requested_at = datetime.now(UTC)
        endpoint = settings.exa_mcp_endpoint
        try:
            validate_public_url(endpoint)
        except UnsafeUrlError as exc:
            raise GatewayAdapterError("URL_POLICY_BLOCKED", str(exc)) from exc
        base_headers = {
            "Accept": "application/json, text/event-stream",
            "User-Agent": settings.user_agent,
        }
        if settings.exa_api_key:
            base_headers["x-api-key"] = settings.exa_api_key
        session_headers: dict[str, str] | None = None
        try:
            async with httpx.AsyncClient(
                timeout=settings.fetch_timeout_seconds,
                headers=base_headers,
                follow_redirects=False,
            ) as client:
                initialized = await client.post(
                    endpoint,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-03-26",
                            "capabilities": {},
                            "clientInfo": {
                                "name": "GoPilot Research Gateway",
                                "version": "1.0.0",
                            },
                        },
                    },
                )
                if initialized.status_code != 200:
                    raise _exa_http_error(initialized)
                _mcp_result(initialized, expected_id=1)
                session_id = initialized.headers.get("mcp-session-id")
                if not session_id:
                    raise GatewayAdapterError(
                        "SEARCH_PROVIDER_INVALID_RESPONSE",
                        "Exa MCP did not establish a session",
                    )
                session_headers = {
                    "Mcp-Session-Id": session_id,
                    "MCP-Protocol-Version": "2025-03-26",
                }
                ready = await client.post(
                    endpoint,
                    headers=session_headers,
                    json={
                        "jsonrpc": "2.0",
                        "method": "notifications/initialized",
                    },
                )
                if ready.status_code not in {200, 202, 204}:
                    raise _exa_http_error(ready)
                arguments: dict[str, object] = {
                    "query": request.query,
                    "numResults": request.limit,
                    "type": "auto",
                    "contextMaxCharacters": settings.exa_context_max_characters,
                }
                if request.freshness_days:
                    arguments["livecrawl"] = "preferred"
                response = await client.post(
                    endpoint,
                    headers=session_headers,
                    json={
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {
                            "name": "web_search_exa",
                            "arguments": arguments,
                        },
                    },
                )
                if response.status_code != 200:
                    raise _exa_http_error(response)
                payload = _mcp_result(response, expected_id=2)
                if session_headers is not None:
                    try:
                        await client.delete(endpoint, headers=session_headers)
                    except httpx.HTTPError:
                        pass
        except GatewayAdapterError:
            raise
        except httpx.TimeoutException as exc:
            raise GatewayAdapterError(
                "FETCH_TIMEOUT", "Exa search timed out", retryable=True
            ) from exc
        except httpx.NetworkError as exc:
            raise GatewayAdapterError(
                "SEARCH_PROVIDER_UNAVAILABLE",
                "Exa search network request failed",
                retryable=True,
            ) from exc

        blocks = _exa_result_blocks(payload)
        now = datetime.now(UTC)
        results: list[SearchResult] = []
        seen: set[str] = set()
        rejection_reasons: dict[str, int] = {}
        for block in blocks:
            url = block.get("url", "")
            title = normalize_whitespace(block.get("title", ""))
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
            snippet = normalize_whitespace(block.get("highlights", ""))[:4000]
            if not _is_exa_relevant(request.query, f"{title} {snippet}"):
                _reject(rejection_reasons, "below_relevance_threshold")
                continue
            seen.add(canonical)
            results.append(
                SearchResult(
                    url=HttpUrl(url),
                    canonical_url=HttpUrl(canonical),
                    title=title[:500],
                    snippet=snippet,
                    published_at=_exa_datetime(block.get("published")),
                    retrieved_at=now,
                    backend=self.backend,
                    provider="exa",
                )
            )
            if len(results) >= request.limit:
                break
        return results, SearchDiagnostics(
            requested_at=requested_at,
            http_status=200,
            provider_query=request.query,
            results_before_filter=len(blocks),
            results_after_filter=len(results),
            rejected_results=max(0, len(blocks) - len(results)),
            rejection_reasons=rejection_reasons,
        )

    async def _search_bing(
        self, request: SearchRequest
    ) -> tuple[list[SearchResult], SearchDiagnostics]:
        requested_at = datetime.now(UTC)
        query = request.query
        if request.freshness_days and request.freshness_days <= 365:
            query = f"{query} recent"
        endpoint = (
            f"{settings.search_endpoint}?{urlencode({'q': query, 'format': 'rss'})}"
        )
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
            raise GatewayAdapterError(
                "RATE_LIMITED", "Search rate limit reached", retryable=True
            )
        if response.status_code != 200:
            raise GatewayAdapterError(
                "SEARCH_PROVIDER_UNAVAILABLE",
                f"Search provider returned HTTP {response.status_code}",
                retryable=response.status_code >= 500,
            )
        feed = feedparser.parse(response.content)
        if getattr(feed, "bozo", False) and not feed.entries:
            raise GatewayAdapterError(
                "SEARCH_PROVIDER_UNAVAILABLE",
                "Search provider returned an invalid feed",
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
                    provider="bing",
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
                    provider="gdelt",
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
                    throttled = response.status_code == 429 or _is_throttle_response(
                        response
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
    return " ".join(token for token in quoted.split() if len(token.strip('"')) >= 3)


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


def _is_exa_relevant(query: str, result_text: str) -> bool:
    """Apply a conservative floor without undoing Exa's semantic ranking."""

    query_terms = _terms(query)
    if not query_terms:
        return False
    return bool(query_terms & _terms(result_text))


def _mcp_json(response: httpx.Response) -> dict[str, object]:
    if "text/event-stream" not in response.headers.get("content-type", ""):
        try:
            value = response.json()
        except ValueError as exc:
            raise GatewayAdapterError(
                "SEARCH_PROVIDER_INVALID_RESPONSE",
                "Exa MCP returned invalid JSON",
            ) from exc
        if isinstance(value, dict):
            return value
        raise GatewayAdapterError(
            "SEARCH_PROVIDER_INVALID_RESPONSE",
            "Exa MCP returned an invalid payload",
        )
    for line in response.text.splitlines():
        if not line.startswith("data:"):
            continue
        try:
            value = json.loads(line.removeprefix("data:").strip())
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise GatewayAdapterError(
        "SEARCH_PROVIDER_INVALID_RESPONSE",
        "Exa MCP returned no message event",
    )


def _mcp_result(response: httpx.Response, *, expected_id: int) -> dict[str, object]:
    payload = _mcp_json(response)
    if payload.get("id") != expected_id:
        raise GatewayAdapterError(
            "SEARCH_PROVIDER_INVALID_RESPONSE",
            "Exa MCP response identifier did not match",
        )
    error = payload.get("error")
    if isinstance(error, dict):
        code = error.get("code")
        message = normalize_whitespace(str(error.get("message") or "MCP call failed"))
        raise GatewayAdapterError(
            "RATE_LIMITED" if code == -32001 else "SEARCH_PROVIDER_UNAVAILABLE",
            f"Exa MCP error: {message[:300]}",
            retryable=code in {-32001, -32603},
        )
    result = payload.get("result")
    if not isinstance(result, dict):
        raise GatewayAdapterError(
            "SEARCH_PROVIDER_INVALID_RESPONSE",
            "Exa MCP returned no result object",
        )
    if result.get("isError") is True:
        content = result.get("content")
        message = "Exa MCP search failed"
        if isinstance(content, list) and content and isinstance(content[0], dict):
            message = normalize_whitespace(str(content[0].get("text") or message))[:300]
        raise GatewayAdapterError(
            "SEARCH_PROVIDER_UNAVAILABLE", message, retryable=True
        )
    return result


def _exa_http_error(response: httpx.Response) -> GatewayAdapterError:
    if response.status_code == 429:
        return GatewayAdapterError(
            "RATE_LIMITED", "Exa search rate limit reached", retryable=True
        )
    return GatewayAdapterError(
        "SEARCH_PROVIDER_UNAVAILABLE",
        f"Exa MCP returned HTTP {response.status_code}",
        retryable=response.status_code >= 500,
    )


def _exa_result_blocks(payload: dict[str, object]) -> list[dict[str, str]]:
    content = payload.get("content")
    if not isinstance(content, list):
        return []
    text = "\n".join(
        str(item.get("text") or "")
        for item in content
        if isinstance(item, dict) and item.get("type") == "text"
    )
    results: list[dict[str, str]] = []
    for raw_block in re.split(r"\n\s*---\s*\n", text):
        title = re.search(r"(?m)^Title:\s*(.+)$", raw_block)
        url = re.search(r"(?m)^URL:\s*(\S+)$", raw_block)
        if not title or not url:
            continue
        published = re.search(r"(?m)^Published:\s*(.+)$", raw_block)
        highlights = raw_block
        marker = re.search(r"(?m)^Highlights:\s*", raw_block)
        if marker:
            highlights = raw_block[marker.end() :]
        results.append(
            {
                "title": title.group(1).strip(),
                "url": url.group(1).strip(),
                "published": published.group(1).strip() if published else "",
                "highlights": highlights.strip(),
            }
        )
    return results


def _exa_datetime(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw or raw.upper() == "N/A":
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _gdelt_datetime(value: object) -> datetime | None:
    raw = str(value or "").strip()
    for pattern in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(raw, pattern).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None
