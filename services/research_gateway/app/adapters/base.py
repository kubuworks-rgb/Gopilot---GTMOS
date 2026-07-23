from __future__ import annotations

from typing import Protocol

from services.research_gateway.app.schemas import (
    AdapterHealth,
    FetchRequest,
    SearchRequest,
    SearchResult,
    SourceDocumentInput,
)


class ResearchAdapter(Protocol):
    async def health(self) -> AdapterHealth: ...

    async def search(self, request: SearchRequest) -> list[SearchResult]: ...

    async def fetch(self, request: FetchRequest) -> SourceDocumentInput: ...
