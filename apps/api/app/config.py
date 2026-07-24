from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "development")
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://gtm:gtm@127.0.0.1:5432/gtm"
    )
    redis_url: str = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    research_mode: str = os.getenv("RESEARCH_MODE", "fixture")
    demo_auth_enabled: bool = os.getenv("DEMO_AUTH_ENABLED", "true").lower() == "true"
    research_gateway_url: str = os.getenv(
        "AGENT_REACH_GATEWAY_URL", "http://127.0.0.1:8010"
    ).rstrip("/")
    gateway_internal_token: str | None = os.getenv("RESEARCH_GATEWAY_TOKEN") or None
    research_gateway_timeout_seconds: float = float(
        os.getenv("RESEARCH_GATEWAY_TIMEOUT_SECONDS", "120")
    )
    agent_reach_enabled: bool = (
        os.getenv("AGENT_REACH_ENABLED", "false").lower() == "true"
    )
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY") or None
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")
    github_token: str | None = os.getenv("GITHUB_TOKEN") or None
    firmographic_provider: str = os.getenv(
        "FIRMOGRAPHIC_PROVIDER", "public_evidence"
    )
    firmographic_api_key: str | None = os.getenv("FIRMOGRAPHIC_API_KEY") or None
    candidate_prequalification_floor: int = int(
        os.getenv("CANDIDATE_PREQUALIFICATION_FLOOR", "45")
    )
    max_research_searches: int = int(os.getenv("MAX_RESEARCH_SEARCHES", "60"))
    max_research_documents: int = int(os.getenv("MAX_RESEARCH_DOCUMENTS", "100"))
    max_account_candidates: int = int(os.getenv("MAX_ACCOUNT_CANDIDATES", "40"))
    max_accounts_researched: int = int(os.getenv("MAX_ACCOUNTS_RESEARCHED", "15"))
    max_elapsed_seconds: int = int(os.getenv("MAX_RESEARCH_ELAPSED_SECONDS", "900"))
    cors_origins: tuple[str, ...] = tuple(
        item.strip()
        for item in os.getenv(
            "CORS_ALLOWED_ORIGINS", "http://127.0.0.1:3000,http://localhost:3000"
        ).split(",")
        if item.strip()
    )

    def validate(self) -> None:
        if self.research_mode not in {"fixture", "live"}:
            raise RuntimeError("RESEARCH_MODE must be fixture or live")
        if self.app_env == "production" and (
            self.demo_auth_enabled or self.research_mode == "fixture"
        ):
            raise RuntimeError(
                "Production forbids demo authentication and fixture research"
            )
        if self.research_mode == "live":
            if not self.database_url.startswith(
                ("postgresql+asyncpg://", "postgresql://")
            ):
                raise RuntimeError("Live research requires PostgreSQL DATABASE_URL")
            if not self.redis_url.startswith(("redis://", "rediss://")):
                raise RuntimeError("Live research requires a Redis REDIS_URL")
            if not self.research_gateway_url.startswith(("http://", "https://")):
                raise RuntimeError("Live research requires AGENT_REACH_GATEWAY_URL")
        for name, value in (
            ("MAX_RESEARCH_SEARCHES", self.max_research_searches),
            ("MAX_RESEARCH_DOCUMENTS", self.max_research_documents),
            ("MAX_ACCOUNT_CANDIDATES", self.max_account_candidates),
            ("MAX_ACCOUNTS_RESEARCHED", self.max_accounts_researched),
            ("MAX_RESEARCH_ELAPSED_SECONDS", self.max_elapsed_seconds),
            ("CANDIDATE_PREQUALIFICATION_FLOOR", self.candidate_prequalification_floor),
        ):
            if value <= 0:
                raise RuntimeError(f"{name} must be positive")


settings = Settings()
