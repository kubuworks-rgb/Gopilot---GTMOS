"""Registrable-domain extraction.

`optivian.ai` and `optivian.cloud` are different registrable domains and must
never be treated as one entity; `blog.optivian.ai` and `optivian.ai` are the
same one and must never be treated as two. Everything downstream depends on
getting that boundary right, so it lives on its own.

tldextract is used when available, because the public suffix list is the only
correct way to know that `co.uk` is a suffix and `ai` is not. The fallback
handles the common multi-label suffixes so an environment without the
dependency degrades to something usable rather than to nonsense.
"""

from __future__ import annotations

from urllib.parse import urlsplit

try:
    import tldextract  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover - environment dependent
    tldextract = None  # type: ignore[assignment]


_extract = (
    tldextract.TLDExtract(cache_dir=None, suffix_list_urls=()) if tldextract else None
)

_FALLBACK_MULTILABEL_SUFFIXES = {
    "co.in",
    "co.uk",
    "com.au",
    "com.br",
    "co.jp",
    "co.nz",
    "co.za",
    "com.sg",
    "com.mx",
    "com.tr",
    "com.cn",
    "com.hk",
    "com.tw",
    "com.my",
    "com.ph",
    "com.pk",
    "com.bd",
    "com.np",
    "org.uk",
    "net.au",
    "org.au",
}

# Reserved for documentation and testing (RFC 2606 / 6761). tldextract does not
# treat them as public suffixes, but a test fixture using example.test should
# still resolve rather than returning None.
_RESERVED_TEST_TLDS = {"test", "example", "invalid", "localhost"}


def registrable_domain(value: str) -> str | None:
    """The registrable domain for a URL or bare host, or None if there isn't one.

    >>> registrable_domain("https://blog.optivian.ai/post")
    'optivian.ai'
    >>> registrable_domain("optivian.cloud")
    'optivian.cloud'
    """
    parsed = urlsplit(value if "://" in value else f"https://{value}")
    host = (parsed.hostname or "").lower().strip(".")
    if not host:
        return None
    if _extract is not None:
        extracted = _extract(host)
        registered = extracted.top_domain_under_public_suffix
        if registered:
            return registered.lower()
        labels = host.split(".")
        if len(labels) >= 2 and labels[-1] in _RESERVED_TEST_TLDS:
            return ".".join(labels[-2:])
        return None
    labels = host.split(".")
    if len(labels) < 2:
        return None
    suffix_length = 2 if ".".join(labels[-2:]) in _FALLBACK_MULTILABEL_SUFFIXES else 1
    if len(labels) <= suffix_length:
        return None
    return ".".join(labels[-(suffix_length + 1) :])
