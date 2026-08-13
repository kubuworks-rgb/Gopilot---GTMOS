"""Production must refuse plaintext rather than serve it quietly.

Nothing in the application can prove a reverse proxy terminated TLS correctly.
What it can do is refuse to start when the configuration never mentions https at
all, which is the difference between a deployment that was configured for TLS and
one where somebody skipped a step and got a working-looking service.

JWKS is the case that matters most. Fetched over http, the signing keys can be
substituted in transit, and the API will then accept tokens minted by whoever did
the substituting -- an authentication bypass that looks like normal operation.
"""

from __future__ import annotations

import pytest

from apps.api.app.config import Settings


def _production(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "app_env": "production",
        "auth_mode": "oidc",
        "demo_auth_enabled": False,
        "research_mode": "live",
        "database_url": "postgresql+asyncpg://gtm:gtm@db:5432/gtm",
        "redis_url": "redis://redis:6379/0",
        "research_gateway_url": "https://gateway.internal",
        "jwt_issuer": "https://issuer.example.com",
        "jwt_audience": "gopilot",
        "jwks_url": "https://issuer.example.com/.well-known/jwks.json",
        "cors_origins": ("https://app.example.com",),
        "private_alpha_enabled": True,
        "private_alpha_allowed_subjects": ("founder",),
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_a_fully_https_production_configuration_starts() -> None:
    _production().validate()


@pytest.mark.parametrize(
    "field, value",
    [
        ("jwt_issuer", "http://issuer.example.com"),
        ("jwks_url", "http://issuer.example.com/.well-known/jwks.json"),
        ("research_gateway_url", "http://gateway.internal"),
    ],
)
def test_production_refuses_plaintext_urls(field: str, value: str) -> None:
    with pytest.raises(RuntimeError, match="plaintext http"):
        _production(**{field: value}).validate()


def test_the_jwks_refusal_explains_the_actual_risk() -> None:
    """An operator who does not know why will route around the check."""
    with pytest.raises(RuntimeError) as refused:
        _production(jwks_url="http://issuer.example.com/jwks.json").validate()

    message = str(refused.value)
    assert "JWKS_URL" in message
    assert "substituted in transit" in message


def test_production_refuses_a_plaintext_web_origin() -> None:
    with pytest.raises(RuntimeError, match="plaintext CORS_ALLOWED_ORIGINS"):
        _production(cors_origins=("http://app.example.com",)).validate()


def test_the_origin_refusal_points_at_the_runbook() -> None:
    with pytest.raises(RuntimeError, match="DEPLOYMENT.md"):
        _production(cors_origins=("http://app.example.com",)).validate()


def test_loopback_origins_are_allowed_for_a_proxy_on_the_same_host() -> None:
    """The proxy reaches the app over loopback; that hop never leaves the box."""
    _production(
        cors_origins=("https://app.example.com", "http://127.0.0.1:3000")
    ).validate()


def test_development_is_not_forced_onto_https() -> None:
    """Local development has no certificate and must stay runnable."""
    Settings(
        app_env="development",
        auth_mode="oidc",
        jwt_issuer="http://127.0.0.1:9000",
        jwt_audience="gopilot-local",
        jwks_url="http://127.0.0.1:9000/jwks.json",
        cors_origins=("http://localhost:3000",),
        private_alpha_enabled=True,
        private_alpha_allowed_subjects=("alpha-founder",),
    ).validate()
