from __future__ import annotations

import os
from dataclasses import dataclass


# Asymmetric signature algorithms only; see Settings.jwt_algorithms.
SUPPORTED_JWT_ALGORITHMS = frozenset(
    {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "PS256", "PS384", "PS512"}
)


@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "development")
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://gtm:gtm@127.0.0.1:5432/gtm"
    )
    redis_url: str = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    research_mode: str = os.getenv("RESEARCH_MODE", "fixture")
    demo_auth_enabled: bool = os.getenv("DEMO_AUTH_ENABLED", "true").lower() == "true"
    auth_mode: str = os.getenv("AUTH_MODE", "demo").lower()
    jwt_issuer: str | None = os.getenv("JWT_ISSUER") or None
    jwt_audience: str | None = os.getenv("JWT_AUDIENCE") or None
    jwks_url: str | None = os.getenv("JWKS_URL") or None
    jwks_cache_ttl_seconds: int = int(os.getenv("JWKS_CACHE_TTL_SECONDS", "600"))
    # Asymmetric only. Allowing an HMAC algorithm alongside JWKS public keys would
    # let a caller sign a token with the published public key as the shared secret.
    jwt_algorithms: tuple[str, ...] = tuple(
        item.strip().upper()
        for item in os.getenv("JWT_ALGORITHMS", "RS256").split(",")
        if item.strip()
    )
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
    candidate_prequalification_high_threshold: int = int(
        os.getenv("CANDIDATE_PREQUALIFICATION_HIGH_THRESHOLD", "35")
    )
    candidate_prequalification_middle_threshold: int = int(
        os.getenv("CANDIDATE_PREQUALIFICATION_MIDDLE_THRESHOLD", "30")
    )
    candidate_prequalification_low_threshold: int = int(
        os.getenv("CANDIDATE_PREQUALIFICATION_LOW_THRESHOLD", "25")
    )
    max_research_searches: int = int(os.getenv("MAX_RESEARCH_SEARCHES", "60"))
    max_research_documents: int = int(os.getenv("MAX_RESEARCH_DOCUMENTS", "100"))
    max_account_candidates: int = int(os.getenv("MAX_ACCOUNT_CANDIDATES", "40"))
    max_accounts_researched: int = int(os.getenv("MAX_ACCOUNTS_RESEARCHED", "15"))
    max_elapsed_seconds: int = int(os.getenv("MAX_RESEARCH_ELAPSED_SECONDS", "900"))
    # --- Private alpha -----------------------------------------------------
    # Invite-only access and bounded usage. Every limit is configurable rather
    # than hard-coded, and every one returns an explicit error instead of
    # silently truncating the user's input.
    private_alpha_enabled: bool = (
        os.getenv("PRIVATE_ALPHA_ENABLED", "false").lower() == "true"
    )
    private_alpha_allowed_subjects: tuple[str, ...] = tuple(
        item.strip()
        for item in os.getenv("PRIVATE_ALPHA_ALLOWED_SUBJECTS", "").split(",")
        if item.strip()
    )
    private_alpha_allowed_emails: tuple[str, ...] = tuple(
        item.strip().lower()
        for item in os.getenv("PRIVATE_ALPHA_ALLOWED_EMAILS", "").split(",")
        if item.strip()
    )
    allow_experimental_discovery: bool = (
        os.getenv("ALLOW_EXPERIMENTAL_DISCOVERY", "false").lower() == "true"
    )
    max_accounts_per_import: int = int(os.getenv("MAX_ACCOUNTS_PER_IMPORT", "100"))
    max_accounts_per_workspace: int = int(
        os.getenv("MAX_ACCOUNTS_PER_WORKSPACE", "500")
    )
    max_imports_per_day: int = int(os.getenv("MAX_IMPORTS_PER_DAY", "20"))
    max_concurrent_research_runs: int = int(
        os.getenv("MAX_CONCURRENT_RESEARCH_RUNS", "2")
    )
    max_workspaces_per_user: int = int(os.getenv("MAX_WORKSPACES_PER_USER", "3"))
    max_export_rows: int = int(os.getenv("MAX_EXPORT_ROWS", "1000"))
    # Retention. Research data becomes *eligible* for deletion after this window;
    # nothing is deleted automatically. Enforcement is an operator-run, dry-run-first
    # command, because silently discarding a customer's evidence would be worse than
    # keeping it too long. See docs/security/PRIVATE_ALPHA_DATA_HANDLING.md.
    research_retention_days: int = int(os.getenv("RESEARCH_RETENTION_DAYS", "180"))
    retention_auto_delete: bool = (
        os.getenv("RETENTION_AUTO_DELETE", "false").lower() == "true"
    )
    max_pages_per_account: int = int(os.getenv("MAX_PAGES_PER_ACCOUNT", "8"))
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
        if self.auth_mode not in {"demo", "oidc"}:
            raise RuntimeError("AUTH_MODE must be demo or oidc")
        if self.app_env == "production" and (
            self.demo_auth_enabled or self.research_mode == "fixture"
        ):
            raise RuntimeError(
                "Production forbids demo authentication and fixture research"
            )
        if self.app_env == "production" and self.auth_mode != "oidc":
            raise RuntimeError("Production requires AUTH_MODE=oidc")
        if self.auth_mode == "oidc":
            missing = [
                name
                for name, value in (
                    ("JWT_ISSUER", self.jwt_issuer),
                    ("JWT_AUDIENCE", self.jwt_audience),
                    ("JWKS_URL", self.jwks_url),
                )
                if not value
            ]
            if missing:
                raise RuntimeError(
                    f"AUTH_MODE=oidc requires {', '.join(missing)}"
                )
            if not self.jwt_algorithms:
                raise RuntimeError("JWT_ALGORITHMS must not be empty")
            unsupported = [
                algorithm
                for algorithm in self.jwt_algorithms
                if algorithm not in SUPPORTED_JWT_ALGORITHMS
            ]
            if unsupported:
                raise RuntimeError(
                    "JWT_ALGORITHMS allows only asymmetric algorithms "
                    f"({', '.join(sorted(SUPPORTED_JWT_ALGORITHMS))}); "
                    f"rejected: {', '.join(unsupported)}"
                )
            if self.jwks_cache_ttl_seconds <= 0:
                raise RuntimeError("JWKS_CACHE_TTL_SECONDS must be positive")
        # TLS. Nothing in the stack can prove a proxy terminated TLS correctly, but
        # a production deployment that never mentions https is one that was never
        # configured for it, and it would otherwise serve plaintext in silence.
        # JWKS is the sharpest case: fetched over http, anyone on the path can
        # substitute the signing keys and mint tokens the API will accept.
        if self.app_env == "production":
            insecure = [
                name
                for name, value in (
                    ("JWT_ISSUER", self.jwt_issuer),
                    ("JWKS_URL", self.jwks_url),
                    ("AGENT_REACH_GATEWAY_URL", self.research_gateway_url),
                )
                if value and value.startswith("http://")
            ]
            if insecure:
                raise RuntimeError(
                    f"Production forbids plaintext http:// for {', '.join(insecure)}. "
                    "Token signing keys fetched over http can be substituted in "
                    "transit by anyone on the path, which forges any identity."
                )
            plaintext_origins = [
                origin
                for origin in self.cors_origins
                if origin.startswith("http://")
                and not origin.startswith(("http://127.0.0.1", "http://localhost"))
            ]
            if plaintext_origins:
                raise RuntimeError(
                    "Production forbids plaintext CORS_ALLOWED_ORIGINS: "
                    f"{', '.join(plaintext_origins)}. Serve the web app over https "
                    "through the reverse proxy (see docs/operations/DEPLOYMENT.md)."
                )
        if self.private_alpha_enabled and not (
            self.private_alpha_allowed_subjects or self.private_alpha_allowed_emails
        ):
            raise RuntimeError(
                "PRIVATE_ALPHA_ENABLED requires PRIVATE_ALPHA_ALLOWED_SUBJECTS or "
                "PRIVATE_ALPHA_ALLOWED_EMAILS; an empty invite list would admit no "
                "one and is more likely a misconfiguration than an intent"
            )
        for name, value in (
            ("MAX_ACCOUNTS_PER_IMPORT", self.max_accounts_per_import),
            ("MAX_ACCOUNTS_PER_WORKSPACE", self.max_accounts_per_workspace),
            ("MAX_IMPORTS_PER_DAY", self.max_imports_per_day),
            ("MAX_CONCURRENT_RESEARCH_RUNS", self.max_concurrent_research_runs),
            ("MAX_WORKSPACES_PER_USER", self.max_workspaces_per_user),
            ("MAX_EXPORT_ROWS", self.max_export_rows),
            ("MAX_PAGES_PER_ACCOUNT", self.max_pages_per_account),
            ("RESEARCH_RETENTION_DAYS", self.research_retention_days),
        ):
            if value <= 0:
                raise RuntimeError(f"{name} must be positive")
        if self.retention_auto_delete:
            raise RuntimeError(
                "RETENTION_AUTO_DELETE is not implemented. Retention is enforced by "
                "running scripts/apply_retention.py, which previews before it "
                "deletes. Automatic deletion needs an explicit product decision on "
                "the window first."
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
            (
                "CANDIDATE_PREQUALIFICATION_HIGH_THRESHOLD",
                self.candidate_prequalification_high_threshold,
            ),
            (
                "CANDIDATE_PREQUALIFICATION_MIDDLE_THRESHOLD",
                self.candidate_prequalification_middle_threshold,
            ),
            (
                "CANDIDATE_PREQUALIFICATION_LOW_THRESHOLD",
                self.candidate_prequalification_low_threshold,
            ),
        ):
            if value <= 0:
                raise RuntimeError(f"{name} must be positive")
        if not (
            self.candidate_prequalification_low_threshold
            <= self.candidate_prequalification_middle_threshold
            <= self.candidate_prequalification_high_threshold
        ):
            raise RuntimeError(
                "Candidate prequalification thresholds must satisfy low <= middle "
                "<= high"
            )


settings = Settings()
