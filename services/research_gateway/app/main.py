from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException

from services.research_gateway.app.adapters.github import GitHubAdapter
from services.research_gateway.app.adapters.rss import RSSAdapter
from services.research_gateway.app.adapters.search import SearchAdapter
from services.research_gateway.app.adapters.webpage import WebPageAdapter
from services.research_gateway.app.adapters.youtube import YouTubeAdapter
from services.research_gateway.app.agent_reach import agent_reach_report
from services.research_gateway.app.config import settings
from services.research_gateway.app.errors import GatewayAdapterError
from services.research_gateway.app.schemas import (
    AdapterHealth,
    CapabilityHealth,
    FetchRequest,
    GatewayError,
    GitHubRequest,
    RSSRequest,
    ResultStatus,
    SearchRequest,
    SearchResponse,
    SourceResponse,
    YouTubeRequest,
)
from services.research_gateway.app.security.url_policy import (
    UnsafeUrlError,
    validate_public_url,
)


app = FastAPI(title="GTM Research Gateway", version="1.0.0")
search_adapter = SearchAdapter()
webpage_adapter = WebPageAdapter()
github_adapter = GitHubAdapter()
rss_adapter = RSSAdapter(webpage_adapter)
youtube_adapter = YouTubeAdapter()


def require_internal_token(
    x_gateway_token: Annotated[str | None, Header()] = None,
) -> None:
    expected = settings.internal_token
    if expected and (
        not x_gateway_token or not hmac.compare_digest(x_gateway_token, expected)
    ):
        raise HTTPException(status_code=401, detail="Gateway authentication required")


Internal = Annotated[None, Depends(require_internal_token)]


def _error(exc: GatewayAdapterError) -> GatewayError:
    return GatewayError(
        code=exc.code,
        message=exc.safe_message,
        retryable=exc.retryable,
    )


@app.get("/internal/v1/health", response_model=AdapterHealth)
async def health(_: Internal) -> AdapterHealth:
    agent_reach, ignored_channels = await agent_reach_report()
    del ignored_channels
    return agent_reach


@app.get("/internal/v1/capabilities", response_model=list[CapabilityHealth])
async def capabilities(_: Internal) -> list[CapabilityHealth]:
    agent_health, agent_channels = await agent_reach_report()
    direct = await asyncio_gather_health()
    return [
        CapabilityHealth(
            channel="agent-reach",
            status=agent_health.status,
            backend=agent_health.backend,
            version=agent_health.version,
            detail=agent_health.detail,
        ),
        *agent_channels,
        *[
            CapabilityHealth(
                channel=item.adapter,
                status=item.status,
                backend=item.backend,
                version=item.version,
                detail=item.detail,
            )
            for item in direct
        ],
    ]


async def asyncio_gather_health() -> list[AdapterHealth]:
    import asyncio

    return list(
        await asyncio.gather(
            search_adapter.health(),
            webpage_adapter.health(),
            github_adapter.health(),
            rss_adapter.health(),
            youtube_adapter.health(),
        )
    )


@app.post("/internal/v1/search", response_model=SearchResponse)
async def search(request: SearchRequest, _: Internal) -> SearchResponse:
    try:
        results, diagnostics = await search_adapter.search(request)
        return SearchResponse(
            status="completed",
            backend=search_adapter.backend,
            results=results,
            diagnostics=diagnostics,
        )
    except GatewayAdapterError as exc:
        return SearchResponse(status="failed", errors=[_error(exc)])


@app.post("/internal/v1/fetch", response_model=SourceResponse)
async def fetch(request: FetchRequest, _: Internal) -> SourceResponse:
    try:
        return SourceResponse(
            status="completed", source=await webpage_adapter.fetch(request)
        )
    except GatewayAdapterError as exc:
        return SourceResponse(status="failed", errors=[_error(exc)])


@app.post("/internal/v1/github", response_model=SourceResponse)
async def github(request: GitHubRequest, _: Internal) -> SourceResponse:
    try:
        return SourceResponse(
            status="completed", source=await github_adapter.fetch(request)
        )
    except GatewayAdapterError as exc:
        return SourceResponse(status="failed", errors=[_error(exc)])


@app.post("/internal/v1/rss", response_model=SourceResponse)
async def rss(request: RSSRequest, _: Internal) -> SourceResponse:
    try:
        return SourceResponse(
            status="completed", sources=await rss_adapter.fetch(request)
        )
    except GatewayAdapterError as exc:
        return SourceResponse(status="failed", errors=[_error(exc)])


@app.post("/internal/v1/youtube", response_model=SourceResponse)
async def youtube(request: YouTubeRequest, _: Internal) -> SourceResponse:
    try:
        source = await youtube_adapter.fetch(request)
        errors = []
        status: ResultStatus = "completed"
        if source.metadata.get("transcript_status") == "YOUTUBE_TRANSCRIPT_UNAVAILABLE":
            errors = [
                GatewayError(
                    code="YOUTUBE_TRANSCRIPT_UNAVAILABLE",
                    message="Public transcript was unavailable; metadata was retained",
                )
            ]
            status = "partial"
        return SourceResponse(status=status, source=source, errors=errors)
    except GatewayAdapterError as exc:
        return SourceResponse(status="failed", errors=[_error(exc)])


@app.post("/internal/v1/fetch/validate")
def validate_fetch(request: FetchRequest, _: Internal) -> dict[str, str]:
    try:
        url = validate_public_url(str(request.url))
    except UnsafeUrlError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "allowed", "url": url}
