from __future__ import annotations

from typing import Any

import httpx
from pydantic import HttpUrl

from apps.api.app.config import settings
from services.research_gateway.app.schemas import (
    CapabilityHealth,
    FetchRequest,
    SearchRequest,
    SearchResponse,
    SourceDocumentInput,
    SourceResponse,
)


class GatewayProviderError(RuntimeError):
    def __init__(self, category: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.category = category
        self.safe_message = message
        self.retryable = retryable


class LiveResearchProvider:
    """Typed client for the isolated public-source gateway."""

    def __init__(
        self,
        base_url: str = settings.research_gateway_url,
        token: str | None = settings.gateway_internal_token,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {"X-Gateway-Token": token} if token else {}

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                timeout=settings.research_gateway_timeout_seconds
            ) as client:
                response = await client.post(
                    f"{self.base_url}{path}",
                    json=payload,
                    headers=self.headers,
                )
        except httpx.TimeoutException as exc:
            raise GatewayProviderError(
                "FETCH_TIMEOUT", "Research gateway timed out", retryable=True
            ) from exc
        except httpx.NetworkError as exc:
            raise GatewayProviderError(
                "GATEWAY_UNAVAILABLE",
                "Research gateway is unavailable",
                retryable=True,
            ) from exc
        if response.status_code == 401:
            raise GatewayProviderError(
                "GATEWAY_AUTH_FAILED", "Research gateway authentication failed"
            )
        if response.status_code >= 400:
            raise GatewayProviderError(
                "GATEWAY_ERROR",
                f"Research gateway returned HTTP {response.status_code}",
                retryable=response.status_code >= 500,
            )
        value = response.json()
        if not isinstance(value, dict):
            raise GatewayProviderError(
                "GATEWAY_INVALID_RESPONSE", "Research gateway returned invalid JSON"
            )
        return value

    @staticmethod
    def _raise_errors(payload: SearchResponse | SourceResponse) -> None:
        if payload.status != "failed":
            return
        error = payload.errors[0] if payload.errors else None
        raise GatewayProviderError(
            error.code if error else "SOURCE_UNAVAILABLE",
            error.message if error else "Source request failed",
            retryable=error.retryable if error else False,
        )

    async def capabilities(self) -> list[CapabilityHealth]:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(
                    f"{self.base_url}/internal/v1/capabilities",
                    headers=self.headers,
                )
                response.raise_for_status()
        except (httpx.HTTPError, ValueError) as exc:
            raise GatewayProviderError(
                "GATEWAY_UNAVAILABLE", "Research capabilities are unavailable"
            ) from exc
        return [CapabilityHealth.model_validate(item) for item in response.json()]

    async def search(
        self,
        *,
        workspace_id: str,
        research_run_id: str,
        query: str,
        limit: int = 5,
        freshness_days: int | None = 365,
        purpose: str = "market_research",
    ) -> SearchResponse:
        request = SearchRequest(
            workspace_id=workspace_id,
            research_run_id=research_run_id,
            query=query,
            limit=limit,
            freshness_days=freshness_days,
            purpose=purpose,
        )
        result = SearchResponse.model_validate(
            await self._post("/internal/v1/search", request.model_dump(mode="json"))
        )
        self._raise_errors(result)
        return result

    async def fetch(
        self,
        *,
        workspace_id: str,
        research_run_id: str,
        url: str,
    ) -> SourceDocumentInput:
        request = FetchRequest(
            workspace_id=workspace_id,
            research_run_id=research_run_id,
            url=HttpUrl(url),
        )
        result = SourceResponse.model_validate(
            await self._post("/internal/v1/fetch", request.model_dump(mode="json"))
        )
        self._raise_errors(result)
        if result.source is None:
            raise GatewayProviderError(
                "SOURCE_UNAVAILABLE", "Gateway returned no source document"
            )
        return result.source
