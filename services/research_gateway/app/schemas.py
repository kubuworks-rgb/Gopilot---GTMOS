from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class AdapterHealth(BaseModel):
    adapter: str
    status: Literal["available", "degraded", "unavailable"]
    backend: str | None = None
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    detail: str | None = None


class FetchRequest(BaseModel):
    url: HttpUrl
    max_bytes: int = Field(default=1_500_000, ge=1024, le=5_000_000)


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
    text: str
    metadata: dict[str, str] = Field(default_factory=dict)


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=300)
    limit: int = Field(default=5, ge=1, le=20)


class ResearchResult(BaseModel):
    title: str
    url: HttpUrl
    snippet: str
    source_type: str
    backend: str
