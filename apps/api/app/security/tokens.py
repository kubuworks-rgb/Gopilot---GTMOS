"""Bearer-token verification.

Fails closed: any parsing, key, signature, or claim problem raises `AuthError`, and
no caller path treats a verification failure as an anonymous or default principal.
"""

from __future__ import annotations

from dataclasses import dataclass

import jwt
from jwt.algorithms import RSAAlgorithm, ECAlgorithm

from apps.api.app.config import SUPPORTED_JWT_ALGORITHMS, Settings, settings
from apps.api.app.security.jwks import JwksCache, JwksError


class AuthError(Exception):
    """Authentication failed. The message is safe to return to the caller."""


@dataclass(frozen=True)
class VerifiedToken:
    subject: str
    issuer: str
    audience: str
    claims: dict[str, object]


_cache: JwksCache | None = None


def jwks_cache(config: Settings | None = None) -> JwksCache:
    """Process-wide JWKS cache, built lazily from configuration."""

    global _cache
    config = config or settings
    if _cache is None or _cache.url != config.jwks_url:
        if not config.jwks_url:
            raise AuthError("Authentication is not configured")
        _cache = JwksCache(
            url=config.jwks_url, ttl_seconds=config.jwks_cache_ttl_seconds
        )
    return _cache


def reset_jwks_cache() -> None:
    """Drop the cached keys. Used by tests and by configuration reloads."""

    global _cache
    _cache = None


def bearer_token(header_value: str | None) -> str:
    """Extract a bearer token, rejecting anything that is not exactly one."""

    if not header_value:
        raise AuthError("Authorization header is required")
    parts = header_value.split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise AuthError("Authorization header must be a bearer token")
    return parts[1].strip()


def _public_key(jwk: dict[str, object], algorithm: str):  # type: ignore[no-untyped-def]
    key_type = str(jwk.get("kty") or "").upper()
    if key_type == "RSA" and algorithm.startswith(("RS", "PS")):
        return RSAAlgorithm.from_jwk(jwk)  # type: ignore[arg-type]
    if key_type == "EC" and algorithm.startswith("ES"):
        return ECAlgorithm.from_jwk(jwk)  # type: ignore[arg-type]
    raise AuthError("Token signing key is not recognised")


async def verify_bearer_token(
    header_value: str | None, config: Settings | None = None
) -> VerifiedToken:
    config = config or settings
    token = bearer_token(header_value)

    algorithms = [
        algorithm
        for algorithm in config.jwt_algorithms
        if algorithm in SUPPORTED_JWT_ALGORITHMS
    ]
    if not algorithms:
        raise AuthError("Authentication is not configured")
    if not (config.jwt_issuer and config.jwt_audience):
        raise AuthError("Authentication is not configured")

    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise AuthError("Token header could not be read") from exc

    # Pin the algorithm from the allowlist, never from the token. An unsigned token
    # ("alg": "none") and an HMAC token both fail here rather than reaching verify.
    algorithm = str(header.get("alg") or "")
    if algorithm not in algorithms:
        raise AuthError("Token algorithm is not allowed")

    kid = header.get("kid")
    if not kid:
        raise AuthError("Token is missing a key identifier")

    try:
        jwk = await jwks_cache(config).get_key(str(kid))
    except JwksError as exc:
        raise AuthError(str(exc)) from exc

    key = _public_key(jwk, algorithm)

    try:
        claims = jwt.decode(
            token,
            key=key,
            algorithms=[algorithm],
            issuer=config.jwt_issuer,
            audience=config.jwt_audience,
            options={
                "require": ["exp", "iss", "aud", "sub"],
                "verify_signature": True,
                "verify_exp": True,
                "verify_nbf": True,
                "verify_iat": True,
                "verify_aud": True,
                "verify_iss": True,
            },
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("Token has expired") from exc
    except jwt.ImmatureSignatureError as exc:
        raise AuthError("Token is not yet valid") from exc
    except jwt.InvalidIssuerError as exc:
        raise AuthError("Token issuer is not accepted") from exc
    except jwt.InvalidAudienceError as exc:
        raise AuthError("Token audience is not accepted") from exc
    except jwt.PyJWTError as exc:
        raise AuthError("Token could not be verified") from exc

    subject = str(claims.get("sub") or "").strip()
    if not subject:
        raise AuthError("Token subject is missing")

    return VerifiedToken(
        subject=subject,
        issuer=str(claims.get("iss") or ""),
        audience=str(config.jwt_audience),
        claims=dict(claims),
    )
