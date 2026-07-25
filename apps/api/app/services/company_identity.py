from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit

try:
    import tldextract  # type: ignore[import-not-found]
except ModuleNotFoundError:  # Local sandbox may not permit dependency installation.
    tldextract = None  # type: ignore[assignment]


_extract = tldextract.TLDExtract(suffix_list_urls=()) if tldextract else None
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
_RESERVED_TEST_TLDS = {"example", "test", "invalid", "localhost"}


class ResultPageRole(StrEnum):
    OFFICIAL_ROOT = "OFFICIAL_ROOT"
    OFFICIAL_SUBDOMAIN = "OFFICIAL_SUBDOMAIN"
    DIRECTORY = "DIRECTORY"
    NEWS = "NEWS"
    SOCIAL = "SOCIAL"
    VENDOR_MARKETING = "VENDOR_MARKETING"
    OTHER = "OTHER"


EXCLUDED_COMPANY_HOSTS = {
    "linkedin.com",
    "crunchbase.com",
    "tracxn.com",
    "zoominfo.com",
    "pitchbook.com",
    "g2.com",
    "capterra.com",
    "twitter.com",
    "x.com",
    "facebook.com",
    "instagram.com",
    "youtube.com",
    "github.com",
    "medium.com",
    "substack.com",
}

NEWS_DOMAINS = {
    "reuters.com",
    "bloomberg.com",
    "techcrunch.com",
    "economictimes.indiatimes.com",
    "business-standard.com",
    "yourstory.com",
    "inc42.com",
}


@dataclass(frozen=True)
class CompanyDomainIdentity:
    discovered_url: str
    hostname: str
    registrable_domain: str
    canonical_company_domain: str | None
    official_subdomains: tuple[str, ...]
    confidence: float
    page_role: ResultPageRole


def registrable_domain(value: str) -> str | None:
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


def _matches_domain(host: str, domain: str) -> bool:
    return host == domain or host.endswith(f".{domain}")


def classify_result_page(url: str) -> ResultPageRole:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    registered = registrable_domain(url)
    if not host or not registered:
        return ResultPageRole.OTHER
    if any(_matches_domain(host, domain) for domain in EXCLUDED_COMPANY_HOSTS):
        if registered in {"linkedin.com", "twitter.com", "x.com", "facebook.com", "instagram.com"}:
            return ResultPageRole.SOCIAL
        return ResultPageRole.DIRECTORY
    if any(_matches_domain(host, domain) for domain in NEWS_DOMAINS):
        return ResultPageRole.NEWS
    return (
        ResultPageRole.OFFICIAL_ROOT
        if host in {registered, f"www.{registered}"}
        else ResultPageRole.OFFICIAL_SUBDOMAIN
    )


def resolve_company_identity(
    discovered_url: str,
    *,
    verified_official_hosts: tuple[str, ...] = (),
) -> CompanyDomainIdentity:
    parsed = urlsplit(
        discovered_url if "://" in discovered_url else f"https://{discovered_url}"
    )
    host = (parsed.hostname or "").lower().strip(".").removeprefix("www.")
    registered = registrable_domain(discovered_url) or ""
    role = classify_result_page(discovered_url)
    verified = tuple(
        sorted(
            {
                item.lower().strip(".").removeprefix("www.")
                for item in verified_official_hosts
                if item
            }
        )
    )
    canonical: str | None = None
    confidence = 0.0
    if role in {ResultPageRole.OFFICIAL_ROOT, ResultPageRole.OFFICIAL_SUBDOMAIN}:
        canonical = registered
        confidence = 0.88 if role == ResultPageRole.OFFICIAL_ROOT else 0.80
        if host in verified or registered in verified:
            confidence = 0.99
    official_subdomains = tuple(
        item for item in ({host, *verified} if canonical else set()) if item != canonical
    )
    return CompanyDomainIdentity(
        discovered_url=discovered_url,
        hostname=host,
        registrable_domain=registered,
        canonical_company_domain=canonical,
        official_subdomains=tuple(sorted(official_subdomains)),
        confidence=confidence,
        page_role=role,
    )
