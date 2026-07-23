from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import feedparser  # type: ignore[import-untyped]
from pydantic import HttpUrl

from services.research_gateway.app.adapters.webpage import WebPageAdapter
from services.research_gateway.app.errors import GatewayAdapterError
from services.research_gateway.app.normalization import canonicalize_url, normalize_whitespace
from services.research_gateway.app.schemas import (
    AdapterHealth,
    FetchRequest,
    RSSRequest,
    SourceDocumentInput,
)
from services.research_gateway.app.security.url_policy import (
    UnsafeUrlError,
    validate_public_url,
)


def _entry_date(entry: object) -> datetime | None:
    value = getattr(entry, "published", None) or getattr(entry, "updated", None)
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(str(value))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (TypeError, ValueError, OverflowError):
        return None


class RSSAdapter:
    name = "rss"

    def __init__(self, webpage: WebPageAdapter | None = None) -> None:
        self.webpage = webpage or WebPageAdapter()

    async def health(self) -> AdapterHealth:
        return AdapterHealth(
            adapter=self.name,
            status="available",
            backend="feedparser",
            version=getattr(feedparser, "__version__", None),
            detail="RSS and Atom parsing enabled",
        )

    async def fetch(self, request: RSSRequest) -> list[SourceDocumentInput]:
        payload = await self.webpage.fetch(
            FetchRequest(
                workspace_id=request.workspace_id,
                research_run_id=request.research_run_id,
                url=request.url,
                max_bytes=2_000_000,
            )
        )
        feed = feedparser.parse(payload.text)
        if getattr(feed, "bozo", False) and not feed.entries:
            raise GatewayAdapterError("RSS_PARSE_FAILED", "RSS or Atom feed is malformed")
        feed_title = normalize_whitespace(str(feed.feed.get("title", payload.title)))
        sources: list[SourceDocumentInput] = []
        for entry in feed.entries[: request.limit]:
            url = str(entry.get("link", "")).strip()
            title = normalize_whitespace(str(entry.get("title", "")))
            text = normalize_whitespace(
                str(
                    entry.get("summary")
                    or entry.get("description")
                    or entry.get("content", [{}])[0].get("value", "")
                )
            )
            if not url or not title or not text:
                continue
            try:
                validate_public_url(url)
                canonical_url = canonicalize_url(url)
            except (UnsafeUrlError, ValueError):
                continue
            sources.append(
                SourceDocumentInput(
                    platform="rss",
                    source_type="feed_entry",
                    backend="feedparser",
                    url=HttpUrl(url),
                    canonical_url=HttpUrl(canonical_url),
                    title=title,
                    author=entry.get("author"),
                    published_at=_entry_date(entry),
                    retrieved_at=datetime.now(UTC),
                    content_type="text/plain",
                    text=text,
                    metadata={
                        "feed_title": feed_title,
                        "feed_url": str(request.url),
                    },
                )
            )
        if not sources:
            raise GatewayAdapterError("RSS_PARSE_FAILED", "Feed contained no usable entries")
        return sources
