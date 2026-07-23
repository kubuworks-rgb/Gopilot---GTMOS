from __future__ import annotations

import hashlib
import re
from html import unescape
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


TRACKING_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "source",
}


def canonicalize_url(url: str) -> str:
    parsed = urlsplit(url.strip())
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").rstrip(".").lower()
    port = parsed.port
    netloc = hostname
    if port and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
        netloc = f"{hostname}:{port}"
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    query = urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in TRACKING_KEYS
        )
    )
    return urlunsplit((scheme, netloc, path, query, ""))


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(text)).strip()


def content_hash(text: str) -> str:
    normalized = normalize_whitespace(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
