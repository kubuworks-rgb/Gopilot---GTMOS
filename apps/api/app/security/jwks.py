"""JWKS retrieval and caching for provider-neutral OIDC verification.

Deliberately vendor-agnostic: any issuer publishing a standard JWKS document works.
Vendor choice lives in configuration, never in domain logic.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import httpx


class JwksError(RuntimeError):
    """The signing keys could not be obtained or did not contain the key."""


@dataclass
class JwksCache:
    """Caches an issuer's signing keys and refreshes them on rotation.

    An unknown `kid` is the normal signal that the issuer rotated keys, so one
    refresh is attempted before rejecting. The refresh is rate-limited so a stream
    of tokens bearing bogus key IDs cannot be turned into a request amplifier
    against the issuer.
    """

    url: str
    ttl_seconds: int = 600
    min_refresh_interval_seconds: float = 10.0
    timeout_seconds: float = 10.0

    _keys: dict[str, dict[str, Any]] = field(default_factory=dict)
    _fetched_at: float = 0.0
    _last_attempt_at: float = 0.0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def _expired(self, now: float) -> bool:
        return not self._keys or (now - self._fetched_at) >= self.ttl_seconds

    async def _fetch(self) -> None:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(self.url)
                response.raise_for_status()
                document = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            # Never surface issuer transport detail to the caller.
            raise JwksError("Signing keys are unavailable") from exc

        keys = document.get("keys") if isinstance(document, dict) else None
        if not isinstance(keys, list) or not keys:
            raise JwksError("Signing key document is empty or malformed")

        parsed = {
            str(key["kid"]): key
            for key in keys
            if isinstance(key, dict) and key.get("kid")
        }
        if not parsed:
            raise JwksError("Signing key document contained no usable key IDs")
        self._keys = parsed
        self._fetched_at = time.monotonic()

    async def get_key(self, kid: str) -> dict[str, Any]:
        """Return the JWK for `kid`, refreshing across a rotation if needed."""

        now = time.monotonic()
        async with self._lock:
            if self._expired(now):
                self._last_attempt_at = now
                await self._fetch()
            key = self._keys.get(kid)
            if key is not None:
                return key

            # Unknown kid: the issuer may have rotated inside the TTL window.
            if (time.monotonic() - self._last_attempt_at) < self.min_refresh_interval_seconds:
                raise JwksError("Token signing key is not recognised")
            self._last_attempt_at = time.monotonic()
            await self._fetch()
            key = self._keys.get(kid)
            if key is None:
                raise JwksError("Token signing key is not recognised")
            return key

    def clear(self) -> None:
        self._keys = {}
        self._fetched_at = 0.0
        self._last_attempt_at = 0.0
