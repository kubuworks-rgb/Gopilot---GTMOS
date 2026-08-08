"""The gateway must fail closed and must not re-resolve a validated hostname.

Covers two audit findings:
  S2 - `require_internal_token` was a no-op whenever no token was configured, so a
       tokenless deployment exposed an unauthenticated fetch service.
  S3 - `validate_public_url` resolved the hostname, then httpx resolved it again at
       connect time, leaving a DNS-rebinding window on user-supplied domains.
"""

from __future__ import annotations

import socket

import httpx
import pytest

from services.research_gateway.app.config import GatewaySettings
from services.research_gateway.app.security.url_policy import (
    UnsafeUrlError,
    resolve_public_url,
)


def _resolver_for(*addresses: str):
    def resolve(host: str, port: int, type: int = socket.SOCK_STREAM):
        return [(socket.AF_INET, type, 6, "", (address, port)) for address in addresses]

    return resolve


# --------------------------------------------------------------- startup fail-closed


def test_production_without_a_token_refuses_to_start() -> None:
    with pytest.raises(RuntimeError, match="RESEARCH_GATEWAY_TOKEN"):
        GatewaySettings(app_env="production", internal_token=None).validate()


def test_production_with_a_token_starts() -> None:
    GatewaySettings(app_env="production", internal_token="t" * 32).validate()


def test_short_tokens_are_rejected() -> None:
    with pytest.raises(RuntimeError, match="at least 32"):
        GatewaySettings(app_env="production", internal_token="short").validate()


def test_local_development_may_run_without_a_token() -> None:
    settings = GatewaySettings(app_env="development", internal_token=None)
    settings.validate()
    assert settings.authentication_required is False


def test_a_configured_token_is_always_required() -> None:
    settings = GatewaySettings(app_env="development", internal_token="t" * 32)
    assert settings.authentication_required is True


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_redirects", -1),
        ("default_max_bytes", 0),
        ("fetch_timeout_seconds", 0.0),
    ],
)
def test_nonsensical_fetch_bounds_are_rejected(field: str, value: object) -> None:
    with pytest.raises(RuntimeError):
        GatewaySettings(**{field: value}).validate()  # type: ignore[arg-type]


# ------------------------------------------------------------------- address pinning


def test_resolution_returns_every_validated_address() -> None:
    target = resolve_public_url(
        "https://company.example/about",
        resolver=_resolver_for("93.184.216.34", "93.184.216.35"),
    )

    assert target.hostname == "company.example"
    assert target.addresses == ("93.184.216.34", "93.184.216.35")
    assert target.port == 443


def test_a_single_private_address_blocks_the_whole_name() -> None:
    """A name answering with both a public and a private address must be refused."""
    with pytest.raises(UnsafeUrlError, match="blocked address"):
        resolve_public_url(
            "https://rebind.example/",
            resolver=_resolver_for("93.184.216.34", "169.254.169.254"),
        )


def test_pinned_url_substitutes_the_address_and_keeps_the_path() -> None:
    target = resolve_public_url(
        "https://company.example/about?x=1", resolver=_resolver_for("93.184.216.34")
    )

    assert target.pinned_url("93.184.216.34") == "https://93.184.216.34/about?x=1"
    assert target.host_header == "company.example"


def test_pinned_url_brackets_ipv6_literals() -> None:
    target = resolve_public_url(
        "https://company.example/x", resolver=_resolver_for("2606:2800:220:1::1")
    )

    assert target.pinned_url("2606:2800:220:1::1") == "https://[2606:2800:220:1::1]/x"


def test_non_default_port_is_preserved_in_host_header_and_url() -> None:
    target = resolve_public_url(
        "https://company.example:8443/x", resolver=_resolver_for("93.184.216.34")
    )

    assert target.host_header == "company.example:8443"
    assert target.pinned_url("93.184.216.34") == "https://93.184.216.34:8443/x"


def test_literal_addresses_need_no_dns_and_are_still_policed() -> None:
    target = resolve_public_url("https://93.184.216.34/x")
    assert target.addresses == ("93.184.216.34",)

    with pytest.raises(UnsafeUrlError):
        resolve_public_url("https://10.0.0.1/x")


@pytest.mark.asyncio
async def test_fetch_connects_to_the_pinned_address_not_a_second_lookup() -> None:
    """The transport must see the validated IP, with the original name in Host/SNI."""
    from services.research_gateway.app.adapters.webpage import _pinned_request

    target = resolve_public_url(
        "https://company.example/about", resolver=_resolver_for("93.184.216.34")
    )
    async with httpx.AsyncClient() as client:
        request = _pinned_request(client, target)

    assert request.url.host == "93.184.216.34"
    assert request.headers["Host"] == "company.example"
    assert request.extensions["sni_hostname"] == "company.example"
