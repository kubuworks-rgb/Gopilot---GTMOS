from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


HealthStatus = Literal["available", "degraded", "unavailable"]
ResultStatus = Literal["completed", "partial", "failed"]


class AdapterHealth(BaseModel):
    adapter: str
    status: HealthStatus
    backend: str | None = None
    version: str | None = None
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    detail: str | None = None


class CapabilityHealth(BaseModel):
    channel: str
    status: HealthStatus
    backend: str | None = None
    version: str | None = None
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    detail: str | None = None


class GatewayError(BaseModel):
    code: str
    message: str
    retryable: bool = False


class ResearchContext(BaseModel):
    workspace_id: str = Field(min_length=1, max_length=128)
    research_run_id: str = Field(min_length=1, max_length=128)


class SearchRequest(ResearchContext):
    query: str = Field(min_length=2, max_length=500)
    limit: int = Field(default=5, ge=1, le=20)
    freshness_days: int | None = Field(default=365, ge=1, le=3650)
    purpose: str = Field(default="market_research", min_length=2, max_length=64)


class SearchResult(BaseModel):
    platform: str = "web"
    source_type: str = "search_result"
    url: HttpUrl
    canonical_url: HttpUrl
    title: str
    snippet: str
    published_at: datetime | None = None
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    backend: str


class SearchDiagnostics(BaseModel):
    requested_at: datetime
    http_status: int
    provider_query: str
    results_before_filter: int
    results_after_filter: int
    rejected_results: int
    rejection_reasons: dict[str, int] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    status: ResultStatus
    backend: str | None = None
    results: list[SearchResult] = Field(default_factory=list)
    diagnostics: SearchDiagnostics | None = None
    errors: list[GatewayError] = Field(default_factory=list)


class FetchRequest(ResearchContext):
    url: HttpUrl
    max_bytes: int = Field(default=1_500_000, ge=1024, le=5_000_000)


class GitHubRequest(ResearchContext):
    repository: str = Field(min_length=3, max_length=300)
    include_readme: bool = True
    include_releases: bool = True
    include_issues: bool = False


class RSSRequest(ResearchContext):
    url: HttpUrl
    limit: int = Field(default=10, ge=1, le=30)


class YouTubeRequest(ResearchContext):
    url: HttpUrl
    include_transcript: bool = True
    max_duration_seconds: int = Field(default=7200, ge=1, le=14400)


class SourceDocumentInput(BaseModel):
    platform: str
    source_type: str
    backend: str
    url: HttpUrl
    canonical_url: HttpUrl
    title: str
    author: str | None = None
    published_at: datetime | None = None
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    language: str | None = None
    content_type: str
    text: str
    metadata: dict[str, object] = Field(default_factory=dict)


class SourceResponse(BaseModel):
    status: ResultStatus
    source: SourceDocumentInput | None = None
    sources: list[SourceDocumentInput] = Field(default_factory=list)
    errors: list[GatewayError] = Field(default_factory=list)


# Backward-compatible names used by the original adapter protocol.
ResearchResult = SearchResult
