from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit


class UnsafeUrlError(ValueError):
    pass


@dataclass(frozen=True)
class ResolvedTarget:
    """A URL that passed policy, plus the exact addresses it resolved to.

    Callers must connect to one of `addresses` rather than re-resolving the
    hostname. Re-resolution reopens the DNS-rebinding window: the name can answer
    with a public address during validation and a private one microseconds later.
    """

    url: str
    hostname: str
    port: int
    scheme: str
    addresses: tuple[str, ...]

    def pinned_url(self, address: str) -> str:
        """The same URL with `address` substituted for the hostname."""
        parts = urlsplit(self.url)
        literal = f"[{address}]" if ":" in address else address
        netloc = f"{literal}:{parts.port}" if parts.port else literal
        return urlunsplit(
            (parts.scheme, netloc, parts.path, parts.query, parts.fragment)
        )

    @property
    def host_header(self) -> str:
        default = 443 if self.scheme == "https" else 80
        return self.hostname if self.port == default else f"{self.hostname}:{self.port}"


BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "metadata",
}
NAT64_WELL_KNOWN_PREFIX = ipaddress.ip_network("64:ff9b::/96")


def _is_blocked_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip in NAT64_WELL_KNOWN_PREFIX:
        translated = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
        return _is_blocked_ip(str(translated))
    return any(
        (
            ip.is_private,
            ip.is_loopback,
            ip.is_link_local,
            ip.is_multicast,
            ip.is_reserved,
            ip.is_unspecified,
        )
    ) or ip in ipaddress.ip_network("169.254.169.254/32")


def resolve_public_url(
    url: str,
    resolver: Callable[..., list[tuple[Any, ...]]] | None = None,
) -> ResolvedTarget:
    """Apply URL policy and return the addresses the caller must connect to."""

    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeUrlError("Only HTTP and HTTPS are allowed")
    if parsed.username or parsed.password:
        raise UnsafeUrlError("URL credentials are not allowed")
    hostname = (parsed.hostname or "").rstrip(".").lower()
    if not hostname or hostname in BLOCKED_HOSTS or hostname.endswith(".localhost"):
        raise UnsafeUrlError("Blocked hostname")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    try:
        if _is_blocked_ip(hostname):
            raise UnsafeUrlError("Blocked IP address")
        # A literal address needs no DNS, so there is no rebinding window.
        return ResolvedTarget(
            url=url,
            hostname=hostname,
            port=port,
            scheme=parsed.scheme,
            addresses=(hostname,),
        )
    except ValueError:
        pass

    try:
        resolve = resolver or socket.getaddrinfo
        records = resolve(hostname, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise UnsafeUrlError("DNS resolution failed") from exc
    addresses = tuple(dict.fromkeys(str(record[4][0]) for record in records))
    if not addresses or any(_is_blocked_ip(address) for address in addresses):
        raise UnsafeUrlError("Hostname resolves to a blocked address")
    return ResolvedTarget(
        url=url,
        hostname=hostname,
        port=port,
        scheme=parsed.scheme,
        addresses=addresses,
    )


def validate_public_url(
    url: str,
    resolver: Callable[..., list[tuple[Any, ...]]] | None = None,
) -> str:
    """Policy check only. Prefer `resolve_public_url` when you will connect."""

    return resolve_public_url(url, resolver).url


def validate_exact_domain(url: str, allowed: set[str]) -> str:
    hostname = (urlsplit(url).hostname or "").rstrip(".").lower()
    normalized = {item.lower() for item in allowed}
    if hostname not in normalized:
        raise UnsafeUrlError("Hostname is not allowlisted")
    return url
