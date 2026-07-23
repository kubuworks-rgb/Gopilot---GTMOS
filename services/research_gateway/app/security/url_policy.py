from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit


class UnsafeUrlError(ValueError):
    pass


BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "metadata",
}


def _is_blocked_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
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


def validate_public_url(
    url: str,
    resolver: Callable[..., list[tuple[Any, ...]]] | None = None,
) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeUrlError("Only HTTP and HTTPS are allowed")
    if parsed.username or parsed.password:
        raise UnsafeUrlError("URL credentials are not allowed")
    hostname = (parsed.hostname or "").rstrip(".").lower()
    if not hostname or hostname in BLOCKED_HOSTS or hostname.endswith(".localhost"):
        raise UnsafeUrlError("Blocked hostname")
    try:
        if _is_blocked_ip(hostname):
            raise UnsafeUrlError("Blocked IP address")
        return url
    except ValueError:
        pass
    try:
        resolve = resolver or socket.getaddrinfo
        records = resolve(hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except OSError as exc:
        raise UnsafeUrlError("DNS resolution failed") from exc
    addresses = {str(record[4][0]) for record in records}
    if not addresses or any(_is_blocked_ip(address) for address in addresses):
        raise UnsafeUrlError("Hostname resolves to a blocked address")
    return url


def validate_exact_domain(url: str, allowed: set[str]) -> str:
    hostname = (urlsplit(url).hostname or "").rstrip(".").lower()
    normalized = {item.lower() for item in allowed}
    if hostname not in normalized:
        raise UnsafeUrlError("Hostname is not allowlisted")
    return url
