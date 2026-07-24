from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class GatewaySettings:
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
    gdelt_endpoint: str = os.getenv(
        "GDELT_SEARCH_ENDPOINT",
        "https://api.gdeltproject.org/api/v2/doc/doc",
    )
    gdelt_min_interval_seconds: float = float(
        os.getenv("GDELT_MIN_INTERVAL_SECONDS", "6")
    )
    gdelt_max_attempts: int = int(os.getenv("GDELT_MAX_ATTEMPTS", "3"))


settings = GatewaySettings()
