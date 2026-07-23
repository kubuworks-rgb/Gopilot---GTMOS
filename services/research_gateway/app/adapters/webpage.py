from __future__ import annotations

from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import urljoin

import httpx
from pydantic import HttpUrl

from services.research_gateway.app.config import settings
from services.research_gateway.app.errors import GatewayAdapterError
from services.research_gateway.app.normalization import canonicalize_url, normalize_whitespace
from services.research_gateway.app.schemas import AdapterHealth, FetchRequest, SourceDocumentInput
from services.research_gateway.app.security.content import classify_untrusted_content
from services.research_gateway.app.security.url_policy import UnsafeUrlError, validate_public_url


ALLOWED_CONTENT_TYPES = {
    "text/html",
    "text/plain",
    "application/xhtml+xml",
    "application/xml",
    "text/xml",
    "application/rss+xml",
    "application/atom+xml",
    "application/json",
}


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._title_depth = 0
        self.text: list[str] = []
        self.title: list[str] = []
        self.metadata: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lower = tag.lower()
        if lower in {"script", "style", "noscript", "svg", "template"}:
            self._ignored_depth += 1
        if lower == "title":
            self._title_depth += 1
        if lower == "meta":
            values = {key.lower(): value or "" for key, value in attrs}
            key = values.get("property") or values.get("name")
            value = values.get("content")
            if key and value and key.lower() in {
                "author",
                "article:published_time",
                "og:title",
                "description",
                "og:description",
                "content-language",
            }:
                self.metadata[key.lower()] = value

    def handle_endtag(self, tag: str) -> None:
        lower = tag.lower()
        if lower in {"script", "style", "noscript", "svg", "template"}:
            self._ignored_depth = max(0, self._ignored_depth - 1)
        if lower == "title":
            self._title_depth = max(0, self._title_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        if self._title_depth:
            self.title.append(data)
        self.text.append(data)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


class WebPageAdapter:
    name = "web"

    async def health(self) -> AdapterHealth:
        return AdapterHealth(
            adapter=self.name,
            status="available",
            backend="safe-httpx",
            detail="HTTP(S) fetch with DNS, redirect, type, size, and timeout policy",
        )

    async def fetch(self, request: FetchRequest) -> SourceDocumentInput:
        url = str(request.url)
        max_bytes = min(request.max_bytes, settings.default_max_bytes)
        headers = {
            "User-Agent": settings.user_agent,
            "Accept": "text/html,text/plain,application/xhtml+xml,application/xml,"
            "application/rss+xml,application/atom+xml,application/json;q=0.8",
        }
        timeout = httpx.Timeout(
            settings.fetch_timeout_seconds,
            connect=min(10.0, settings.fetch_timeout_seconds),
        )
        redirect_count = 0
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=False,
                headers=headers,
            ) as client:
                for _ in range(settings.max_redirects + 1):
                    try:
                        validate_public_url(url)
                    except UnsafeUrlError as exc:
                        raise GatewayAdapterError(
                            "URL_POLICY_BLOCKED", str(exc)
                        ) from exc
                    async with client.stream("GET", url) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            location = response.headers.get("location")
                            if not location:
                                raise GatewayAdapterError(
                                    "SOURCE_UNAVAILABLE", "Redirect had no destination"
                                )
                            url = urljoin(url, location)
                            redirect_count += 1
                            continue
                        if response.status_code == 429:
                            raise GatewayAdapterError(
                                "RATE_LIMITED",
                                "Source rate limit reached",
                                retryable=True,
                            )
                        if response.status_code >= 500:
                            raise GatewayAdapterError(
                                "SOURCE_UNAVAILABLE",
                                "Source temporarily unavailable",
                                retryable=True,
                            )
                        if response.status_code >= 400:
                            raise GatewayAdapterError(
                                "SOURCE_UNAVAILABLE",
                                f"Source returned HTTP {response.status_code}",
                            )
                        content_type = (
                            response.headers.get("content-type", "")
                            .split(";", 1)[0]
                            .strip()
                            .lower()
                        )
                        if content_type not in ALLOWED_CONTENT_TYPES:
                            raise GatewayAdapterError(
                                "UNSUPPORTED_CONTENT_TYPE",
                                f"Unsupported content type: {content_type or 'unknown'}",
                            )
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > max_bytes:
                                raise GatewayAdapterError(
                                    "FETCH_TOO_LARGE",
                                    "Source exceeded the configured response limit",
                                )
                        final_url = str(response.url)
                        break
                else:
                    raise GatewayAdapterError(
                        "SOURCE_UNAVAILABLE", "Redirect limit exceeded"
                    )
        except httpx.TimeoutException as exc:
            raise GatewayAdapterError(
                "FETCH_TIMEOUT", "Source retrieval timed out", retryable=True
            ) from exc
        except httpx.NetworkError as exc:
            raise GatewayAdapterError(
                "SOURCE_UNAVAILABLE", "Source network request failed", retryable=True
            ) from exc

        encoding = response.encoding or "utf-8"
        decoded = bytes(body).decode(encoding, errors="replace")
        metadata: dict[str, object] = {
            "http_status": response.status_code,
            "content_length": len(body),
            "redirect_count": redirect_count,
        }
        title = final_url
        author = None
        published_at = None
        language = None
        if content_type in {"text/html", "application/xhtml+xml"}:
            parser = _HTMLTextExtractor()
            parser.feed(decoded)
            text = normalize_whitespace(" ".join(parser.text))
            title = normalize_whitespace(
                parser.metadata.get("og:title") or " ".join(parser.title)
            ) or final_url
            author = parser.metadata.get("author")
            published_at = _parse_datetime(parser.metadata.get("article:published_time"))
            language = parser.metadata.get("content-language")
            metadata.update(parser.metadata)
        else:
            text = normalize_whitespace(decoded)
        if not text:
            raise GatewayAdapterError("SOURCE_UNAVAILABLE", "Source contained no readable text")
        metadata["content_security"] = classify_untrusted_content(text)
        return SourceDocumentInput(
            platform="web",
            source_type="webpage",
            backend="safe-httpx",
            url=HttpUrl(final_url),
            canonical_url=HttpUrl(canonicalize_url(final_url)),
            title=title[:500],
            author=author,
            published_at=published_at,
            language=language,
            content_type=content_type,
            text=text,
            metadata=metadata,
        )
