"""Authentication must fail closed on every malformed or untrusted token.

All keys here are generated in-process for the test run. No real credential,
issuer, or tenant is involved.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm

from apps.api.app.config import Settings
from apps.api.app.main import app
from apps.api.app.security.jwks import JwksCache, JwksError
from apps.api.app.security.tokens import (
    AuthError,
    bearer_token,
    reset_jwks_cache,
    verify_bearer_token,
)


ISSUER = "https://issuer.test/"
AUDIENCE = "gopilot-test"
KID = "test-key-1"
ROTATED_KID = "test-key-2"


def _keypair() -> tuple[Any, str]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(RSAAlgorithm.to_jwk(private.public_key()))
    return private, public_jwk


PRIVATE_A, JWK_A = _keypair()
PRIVATE_B, JWK_B = _keypair()


def _jwks(*entries: tuple[dict[str, Any], str]) -> dict[str, Any]:
    keys = []
    for jwk, kid in entries:
        item = dict(jwk)
        item.update({"kid": kid, "alg": "RS256", "use": "sig"})
        keys.append(item)
    return {"keys": keys}


class _StubCache(JwksCache):
    """JwksCache with the network replaced; refresh semantics stay real."""

    def __init__(self, document: dict[str, Any], **kwargs: Any) -> None:
        super().__init__(url="https://issuer.test/jwks", **kwargs)
        self.document = document
        self.fetches = 0

    async def _fetch(self) -> None:  # type: ignore[override]
        self.fetches += 1
        keys = self.document.get("keys")
        if not keys:
            raise JwksError("Signing keys are unavailable")
        self._keys = {str(key["kid"]): key for key in keys}
        import time

        self._fetched_at = time.monotonic()


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "auth_mode": "oidc",
        "jwt_issuer": ISSUER,
        "jwt_audience": AUDIENCE,
        "jwks_url": "https://issuer.test/jwks",
        "jwt_algorithms": ("RS256",),
    }
    base.update(overrides)
    return Settings(**base)


def _token(
    *,
    private: Any = PRIVATE_A,
    kid: str = KID,
    algorithm: str = "RS256",
    issuer: str = ISSUER,
    audience: str = AUDIENCE,
    subject: str | None = "user-abc",
    expires_in: timedelta = timedelta(minutes=10),
    not_before: timedelta | None = None,
) -> str:
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "iss": issuer,
        "aud": audience,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_in).timestamp()),
    }
    if subject is not None:
        claims["sub"] = subject
    if not_before is not None:
        claims["nbf"] = int((now + not_before).timestamp())
    return jwt.encode(claims, private, algorithm=algorithm, headers={"kid": kid})


@pytest.fixture(autouse=True)
def _install_cache(monkeypatch: pytest.MonkeyPatch) -> _StubCache:
    reset_jwks_cache()
    cache = _StubCache(_jwks((JWK_A, KID)))
    monkeypatch.setattr(
        "apps.api.app.security.tokens.jwks_cache", lambda config=None: cache
    )
    return cache


async def _verify(token: str, **overrides: Any) -> Any:
    return await verify_bearer_token(f"Bearer {token}", _settings(**overrides))


# --------------------------------------------------------------------------- happy


@pytest.mark.asyncio
async def test_valid_token_is_accepted() -> None:
    verified = await _verify(_token())
    assert verified.subject == "user-abc"
    assert verified.issuer == ISSUER


# ------------------------------------------------------------------- claim checks


@pytest.mark.asyncio
async def test_expired_token_is_rejected() -> None:
    with pytest.raises(AuthError, match="expired"):
        await _verify(_token(expires_in=timedelta(minutes=-5)))


@pytest.mark.asyncio
async def test_not_yet_valid_token_is_rejected() -> None:
    with pytest.raises(AuthError, match="not yet valid"):
        await _verify(_token(not_before=timedelta(minutes=5)))


@pytest.mark.asyncio
async def test_wrong_issuer_is_rejected() -> None:
    with pytest.raises(AuthError, match="issuer"):
        await _verify(_token(issuer="https://attacker.test/"))


@pytest.mark.asyncio
async def test_wrong_audience_is_rejected() -> None:
    with pytest.raises(AuthError, match="audience"):
        await _verify(_token(audience="some-other-app"))


@pytest.mark.asyncio
async def test_missing_subject_is_rejected() -> None:
    with pytest.raises(AuthError):
        await _verify(_token(subject=None))


# ------------------------------------------------------------------ signature/keys


@pytest.mark.asyncio
async def test_signature_from_an_unknown_key_is_rejected() -> None:
    """Signed with key B but presented under key A's kid."""
    with pytest.raises(AuthError, match="could not be verified"):
        await _verify(_token(private=PRIVATE_B, kid=KID))


@pytest.mark.asyncio
async def test_unknown_key_id_is_rejected() -> None:
    with pytest.raises(AuthError, match="not recognised"):
        await _verify(_token(kid="never-issued"))


@pytest.mark.asyncio
async def test_token_without_key_id_is_rejected() -> None:
    token = jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": "user-abc",
            "exp": int((datetime.now(UTC) + timedelta(minutes=5)).timestamp()),
        },
        PRIVATE_A,
        algorithm="RS256",
    )
    with pytest.raises(AuthError, match="key identifier"):
        await _verify(token)


# ------------------------------------------------------------------ algorithm safety


@pytest.mark.asyncio
async def test_unsigned_token_is_rejected() -> None:
    token = jwt.encode(
        {"iss": ISSUER, "aud": AUDIENCE, "sub": "user-abc"},
        key=None,
        algorithm="none",
        headers={"kid": KID},
    )
    with pytest.raises(AuthError, match="algorithm is not allowed"):
        await _verify(token)


@pytest.mark.asyncio
async def test_hmac_algorithm_confusion_is_rejected() -> None:
    """The classic attack: sign with the published public key as an HMAC secret.

    Forged by hand because PyJWT refuses to build it — the point is that our
    verifier rejects it on arrival, not that a library declined to create it.
    """
    public_pem = PRIVATE_A.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    def segment(payload: dict[str, Any]) -> bytes:
        return base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":")).encode()
        ).rstrip(b"=")

    signing_input = b".".join(
        (
            segment({"alg": "HS256", "typ": "JWT", "kid": KID}),
            segment(
                {
                    "iss": ISSUER,
                    "aud": AUDIENCE,
                    "sub": "attacker",
                    "exp": int((datetime.now(UTC) + timedelta(minutes=5)).timestamp()),
                }
            ),
        )
    )
    signature = base64.urlsafe_b64encode(
        hmac.new(public_pem, signing_input, hashlib.sha256).digest()
    ).rstrip(b"=")
    token = b".".join((signing_input, signature)).decode()

    with pytest.raises(AuthError, match="algorithm is not allowed"):
        await _verify(token)


def test_hmac_algorithms_cannot_be_configured() -> None:
    with pytest.raises(RuntimeError, match="asymmetric"):
        _settings(jwt_algorithms=("HS256",)).validate()


# ------------------------------------------------------------------- header parsing


@pytest.mark.parametrize(
    "header",
    [None, "", "Token abc", "Bearer", "Bearer ", "abc", "Bearer a b"],
)
def test_malformed_authorization_headers_are_rejected(header: str | None) -> None:
    with pytest.raises(AuthError):
        bearer_token(header)


def test_bearer_scheme_is_case_insensitive() -> None:
    assert bearer_token("bearer abc.def.ghi") == "abc.def.ghi"


# ------------------------------------------------------------------------ JWKS behaviour


@pytest.mark.asyncio
async def test_jwks_is_cached_across_verifications(_install_cache: _StubCache) -> None:
    await _verify(_token())
    await _verify(_token())
    assert _install_cache.fetches == 1


@pytest.mark.asyncio
async def test_jwks_rotation_is_picked_up(_install_cache: _StubCache) -> None:
    await _verify(_token())
    # Issuer rotates: the old key is retired and a new one published.
    _install_cache.document = _jwks((JWK_B, ROTATED_KID))
    _install_cache.min_refresh_interval_seconds = 0.0

    verified = await _verify(_token(private=PRIVATE_B, kid=ROTATED_KID))

    assert verified.subject == "user-abc"
    assert _install_cache.fetches == 2


@pytest.mark.asyncio
async def test_unavailable_jwks_fails_closed(_install_cache: _StubCache) -> None:
    _install_cache.document = {"keys": []}
    _install_cache.clear()
    with pytest.raises(AuthError, match="unavailable"):
        await _verify(_token())


@pytest.mark.asyncio
async def test_unknown_kid_refresh_is_rate_limited(_install_cache: _StubCache) -> None:
    """A flood of bogus key IDs must not amplify requests against the issuer."""
    await _verify(_token())
    before = _install_cache.fetches
    for _ in range(5):
        with pytest.raises(AuthError):
            await _verify(_token(kid="bogus"))
    assert _install_cache.fetches == before


# ------------------------------------------------------------------ configuration gates


def test_production_requires_oidc() -> None:
    with pytest.raises(RuntimeError, match="AUTH_MODE=oidc"):
        Settings(
            app_env="production",
            research_mode="live",
            demo_auth_enabled=False,
            auth_mode="demo",
        ).validate()


def test_production_rejects_demo_auth() -> None:
    with pytest.raises(RuntimeError, match="Production forbids"):
        Settings(
            app_env="production",
            research_mode="live",
            demo_auth_enabled=True,
            auth_mode="oidc",
        ).validate()


def test_oidc_mode_requires_issuer_audience_and_jwks() -> None:
    with pytest.raises(RuntimeError, match="JWT_ISSUER"):
        Settings(auth_mode="oidc").validate()


def test_demo_mode_remains_valid_for_local_development() -> None:
    Settings(app_env="development", auth_mode="demo").validate()


# ------------------------------------------------------------------- route enforcement


def test_oidc_mode_rejects_requests_without_a_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "apps.api.app.api.dependencies.settings", _settings(), raising=False
    )
    response = TestClient(app).get("/api/v1/bootstrap")
    assert response.status_code == 401


def test_oidc_mode_ignores_the_demo_user_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The spoofable header must not survive as an identity source under OIDC."""
    monkeypatch.setattr(
        "apps.api.app.api.dependencies.settings", _settings(), raising=False
    )
    response = TestClient(app).get(
        "/api/v1/bootstrap", headers={"X-Demo-User": "anyone-at-all"}
    )
    assert response.status_code == 401
    assert "workspace" not in response.text.lower()


def test_demo_mode_still_serves_local_development() -> None:
    response = TestClient(app).get(
        "/api/v1/bootstrap", headers={"X-Demo-User": "demo-user"}
    )
    assert response.status_code == 200
