from __future__ import annotations

import os
from dataclasses import dataclass


MINIMUM_GATEWAY_TOKEN_LENGTH = 32


@dataclass(frozen=True)
class GatewaySettings:
    app_env: str = os.getenv("APP_ENV", "development")
    internal_token: str | None = os.getenv("RESEARCH_GATEWAY_TOKEN") or None
    agent_reach_enabled: bool = (
        os.getenv("AGENT_REACH_ENABLED", "false").lower() == "true"
    )
    github_token: str | None = os.getenv("GITHUB_TOKEN") or None
    fetch_timeout_seconds: float = float(
        os.getenv("GATEWAY_FETCH_TIMEOUT_SECONDS", "20")
    )
    max_redirects: int = int(os.getenv("GATEWAY_MAX_REDIRECTS", "4"))
    default_max_bytes: int = int(os.getenv("GATEWAY_MAX_BYTES", "1500000"))
    user_agent: str = os.getenv(
        "GATEWAY_USER_AGENT",
        "GoPilotResearch/1.0 (+https://github.com/kubuworks-rgb/Gopilot---GTMOS)",
    )
    search_backend: str = os.getenv("SEARCH_BACKEND", "exa_mcp")
    search_endpoint: str = os.getenv("SEARCH_ENDPOINT", "https://www.bing.com/search")
    exa_mcp_endpoint: str = os.getenv("EXA_MCP_ENDPOINT", "https://mcp.exa.ai/mcp")
    exa_api_key: str | None = os.getenv("EXA_API_KEY") or None
    exa_context_max_characters: int = int(
        os.getenv("EXA_CONTEXT_MAX_CHARACTERS", "4000")
    )
    exa_min_interval_seconds: float = float(os.getenv("EXA_MIN_INTERVAL_SECONDS", "2"))
    secondary_search_provider: str = os.getenv(
        "SECONDARY_SEARCH_PROVIDER", "tavily"
    ).lower()
    tavily_api_key: str | None = os.getenv("TAVILY_API_KEY") or None
    tavily_endpoint: str = os.getenv(
        "TAVILY_SEARCH_ENDPOINT", "https://api.tavily.com/search"
    )
    minimum_general_search_results: int = int(
        os.getenv("MINIMUM_GENERAL_SEARCH_RESULTS", "3")
    )
    production_acceptance: bool = (
        os.getenv("PRODUCTION_ACCEPTANCE", "false").lower() == "true"
    )
    gdelt_endpoint: str = os.getenv(
        "GDELT_SEARCH_ENDPOINT",
        "https://api.gdeltproject.org/api/v2/doc/doc",
    )
    gdelt_min_interval_seconds: float = float(
        os.getenv("GDELT_MIN_INTERVAL_SECONDS", "6")
    )
    gdelt_max_attempts: int = int(os.getenv("GDELT_MAX_ATTEMPTS", "3"))

    @property
    def authentication_required(self) -> bool:
        return bool(self.internal_token)

    def validate(self) -> None:
        """Refuse to start in a configuration that would expose an open fetcher.

        The gateway retrieves arbitrary public URLs on request. Without a token it
        is an unauthenticated fetch service for anyone who can reach the port, so
        production must not run that way.
        """

        if self.app_env == "production" and not self.internal_token:
            raise RuntimeError(
                "Production requires RESEARCH_GATEWAY_TOKEN; the gateway will not "
                "start as an unauthenticated fetch service"
            )
        if self.internal_token and len(self.internal_token) < MINIMUM_GATEWAY_TOKEN_LENGTH:
            raise RuntimeError(
                "RESEARCH_GATEWAY_TOKEN must be at least "
                f"{MINIMUM_GATEWAY_TOKEN_LENGTH} characters"
            )
        if self.max_redirects < 0:
            raise RuntimeError("GATEWAY_MAX_REDIRECTS must not be negative")
        if self.default_max_bytes <= 0:
            raise RuntimeError("GATEWAY_MAX_BYTES must be positive")
        if self.fetch_timeout_seconds <= 0:
            raise RuntimeError("GATEWAY_FETCH_TIMEOUT_SECONDS must be positive")


settings = GatewaySettings()
