from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "development")
    research_mode: str = os.getenv("RESEARCH_MODE", "fixture")
    demo_auth_enabled: bool = os.getenv("DEMO_AUTH_ENABLED", "true").lower() == "true"
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


settings = Settings()
