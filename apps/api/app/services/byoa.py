from __future__ import annotations

import csv
import io
import ipaddress
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast
from urllib.parse import urlsplit

from apps.api.app.domain.models import (
    AccountImportIssue,
    AccountImportPayload,
    AccountImportRecord,
    AccountImportRow,
    AccountImportSource,
    AccountImportSummary,
    AccountImportValidation,
    ImportRowVerdict,
    ProductModeAvailability,
)
from apps.api.app.services.company_identity import (
    EXCLUDED_COMPANY_HOSTS,
    registrable_domain,
)


_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_LOCAL_SUFFIXES = (".local", ".internal", ".localhost", ".home", ".lan")
_RESERVED_SUFFIXES = (".example", ".test", ".invalid")
_TAG_SPLIT = re.compile(r"[;|]")
_CSV_FIELDS = {
    "company_name",
    "domain",
    "industry",
    "country",
    "employee_band",
    "notes",
    "crm_id",
    "owner",
    "tags",
}


@dataclass(frozen=True)
class CanonicalDomain:
    submitted: str
    canonical_domain: str
    canonical_url: str


class DomainValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def neutralize_formula(value: object) -> str:
    text = "" if value is None else str(value)
    return f"'{text}" if text.startswith(_FORMULA_PREFIXES) else text


def search_provider_configured(
    environ: Mapping[str, str] | None = None,
) -> bool:
    values = environ if environ is not None else os.environ
    return bool(values.get("EXA_API_KEY") or values.get("TAVILY_API_KEY"))


def product_mode_availability(
    environ: Mapping[str, str] | None = None,
) -> ProductModeAvailability:
    values = environ if environ is not None else os.environ
    exa = bool(values.get("EXA_API_KEY"))
    tavily = bool(values.get("TAVILY_API_KEY"))
    return ProductModeAvailability(
        autonomous_discovery_experimental=(
            "AVAILABLE" if exa or tavily else "CONFIGURATION_REQUIRED"
        ),
        search_provider_configured=exa or tavily,
        primary_provider="EXA" if exa else "TAVILY" if tavily else "NONE",
        message=(
            "Account research is available. Automatic account discovery requires "
            "a configured search provider."
        ),
    )


def canonicalize_public_company_domain(value: str) -> CanonicalDomain:
    submitted = value.strip()
    if not submitted:
        raise DomainValidationError("EMPTY_DOMAIN", "Domain is required")
    if submitted.startswith(_FORMULA_PREFIXES):
        raise DomainValidationError(
            "FORMULA_INJECTION",
            "Domain cannot begin with a spreadsheet formula prefix",
        )
    candidate = submitted if "://" in submitted else f"https://{submitted}"
    parsed = urlsplit(candidate)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise DomainValidationError(
            "UNSAFE_SCHEME", "Only http and https company URLs are accepted"
        )
    if parsed.username or parsed.password:
        raise DomainValidationError(
            "URL_CREDENTIALS", "Company URLs cannot contain credentials"
        )
    try:
        port = parsed.port
    except ValueError as exc:
        raise DomainValidationError("MALFORMED_PORT", "URL port is malformed") from exc
    if port not in {None, 80, 443}:
        raise DomainValidationError(
            "UNSAFE_PORT", "Company URLs may use only standard web ports"
        )
    host = (parsed.hostname or "").lower().strip(".").removeprefix("www.")
    if not host:
        raise DomainValidationError("MALFORMED_DOMAIN", "Domain host is missing")
    if host == "localhost" or host.endswith(_LOCAL_SUFFIXES):
        raise DomainValidationError(
            "PRIVATE_DESTINATION", "Private and local destinations are not accepted"
        )
    if host.endswith(_RESERVED_SUFFIXES):
        raise DomainValidationError(
            "NON_PUBLIC_DOMAIN", "A public registrable company domain is required"
        )
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        raise DomainValidationError(
            "IP_DESTINATION", "IP address destinations are not accepted"
        )
    canonical = registrable_domain(host)
    if not canonical or "." not in canonical:
        raise DomainValidationError(
            "NON_PUBLIC_DOMAIN", "A public registrable company domain is required"
        )
    if canonical in EXCLUDED_COMPANY_HOSTS:
        raise DomainValidationError(
            "NON_COMPANY_DOMAIN",
            "Directory, social, and job-board domains are not company domains",
        )
    return CanonicalDomain(
        submitted=submitted,
        canonical_domain=canonical,
        canonical_url=f"https://{canonical}/",
    )


def _sanitized_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return neutralize_formula(stripped) if stripped else None


def _record_from_mapping(
    row: Mapping[str, object], row_number: int
) -> tuple[AccountImportRecord | None, list[AccountImportIssue]]:
    issues: list[AccountImportIssue] = []
    raw_name = str(row.get("company_name") or "").strip()
    raw_domain = str(row.get("domain") or "").strip()
    if raw_name.startswith(_FORMULA_PREFIXES):
        issues.append(
            AccountImportIssue(
                row=row_number,
                field="company_name",
                code="FORMULA_INJECTION",
                message="Company name cannot begin with a spreadsheet formula prefix",
            )
        )
    if len(raw_name) < 2:
        issues.append(
            AccountImportIssue(
                row=row_number,
                field="company_name",
                code="REQUIRED",
                message="company_name is required",
            )
        )
    try:
        canonical = canonicalize_public_company_domain(raw_domain)
    except DomainValidationError as exc:
        issues.append(
            AccountImportIssue(
                row=row_number,
                field="domain",
                code=exc.code,
                message=str(exc),
            )
        )
        canonical = None
    if issues or canonical is None:
        return None, issues
    raw_tags = row.get("tags")
    if isinstance(raw_tags, list):
        tags = [neutralize_formula(str(item).strip()) for item in raw_tags if str(item).strip()]
    else:
        tags = [
            neutralize_formula(item.strip())
            for item in _TAG_SPLIT.split(str(raw_tags or ""))
            if item.strip()
        ]
    return (
        AccountImportRecord(
            company_name=raw_name,
            domain=canonical.canonical_domain,
            industry=_sanitized_optional(str(row.get("industry") or "")),
            country=_sanitized_optional(str(row.get("country") or "")),
            employee_band=_sanitized_optional(str(row.get("employee_band") or "")),
            notes=_sanitized_optional(str(row.get("notes") or "")),
            crm_id=_sanitized_optional(str(row.get("crm_id") or "")),
            owner=_sanitized_optional(str(row.get("owner") or "")),
            tags=tags[:50],
        ),
        [],
    )


def _parse_csv(csv_text: str) -> tuple[list[Mapping[str, object]], list[AccountImportIssue]]:
    try:
        reader = csv.DictReader(io.StringIO(csv_text), strict=True)
        headers = [str(item or "").strip() for item in (reader.fieldnames or [])]
        if not headers or "company_name" not in headers or "domain" not in headers:
            return [], [
                AccountImportIssue(
                    row=1,
                    field="csv",
                    code="MISSING_HEADERS",
                    message="CSV requires company_name and domain headers",
                )
            ]
        unknown = sorted(set(headers) - _CSV_FIELDS)
        if unknown:
            return [], [
                AccountImportIssue(
                    row=1,
                    field="csv",
                    code="UNKNOWN_HEADERS",
                    message=f"Unsupported CSV headers: {', '.join(unknown)}",
                )
            ]
        rows = list(reader)
    except (csv.Error, UnicodeError) as exc:
        return [], [
            AccountImportIssue(
                row=1,
                field="csv",
                code="MALFORMED_CSV",
                message=f"CSV could not be parsed: {exc}",
            )
        ]
    return cast(list[Mapping[str, object]], rows), []


def _parse_pasted(value: str) -> list[Mapping[str, object]]:
    records: list[Mapping[str, object]] = []
    for line in value.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = [item.strip() for item in stripped.split(",", maxsplit=1)]
        if len(parts) == 2:
            company_name, domain = parts
        else:
            domain = parts[0]
            canonical = registrable_domain(domain)
            label = (canonical or domain).split(".", maxsplit=1)[0]
            company_name = re.sub(r"[-_]+", " ", label).title()
        records.append({"company_name": company_name, "domain": domain})
    return records


def _submitted_domain(row: Mapping[str, object]) -> str | None:
    value = row.get("domain")
    return str(value).strip() or None if value not in (None, "") else None


def _submitted_name(row: Mapping[str, object]) -> str | None:
    value = row.get("company_name")
    return str(value).strip() or None if value not in (None, "") else None


_NAME_NOISE = {
    "inc", "llc", "ltd", "limited", "corp", "corporation", "company", "co",
    "pvt", "private", "technologies", "technology", "software", "labs", "group",
    "holdings", "solutions", "systems", "the", "and",
}


def _identity_review_reason(record: AccountImportRecord) -> str | None:
    """Flag rows where the supplied name and domain may not be the same company.

    Blueprint section 8: a row like "Acme AI" pointing at example-company.ai should
    be surfaced for review rather than silently researched. The rule is deliberately
    conservative and deterministic -- it flags only when the name and the domain
    share no meaningful token at all, which is the case a human should look at.
    It never rejects; the row is still imported, just marked.
    """

    brand = record.domain.split(".")[0].lower()
    name_tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", record.company_name.lower())
        if token not in _NAME_NOISE and len(token) > 2
    }
    if not name_tokens:
        return None
    # A shared token, or either string containing the other, is good enough.
    if any(token in brand or brand in token for token in name_tokens):
        return None
    joined = "".join(sorted(name_tokens))
    if brand in joined or joined in brand:
        return None
    return (
        f'"{record.company_name}" shares no name token with {record.domain}. '
        "Confirm this is the right company before relying on its research."
    )


def validate_account_import(payload: AccountImportPayload) -> AccountImportValidation:
    source = payload.import_source
    parse_issues: list[AccountImportIssue] = []
    if payload.csv_text is not None:
        source = AccountImportSource.CSV_UPLOAD
        raw_rows, parse_issues = _parse_csv(payload.csv_text)
    elif payload.pasted_domains is not None:
        source = AccountImportSource.PASTED_DOMAINS
        raw_rows = _parse_pasted(payload.pasted_domains)
    else:
        raw_rows = [item.model_dump(mode="python") for item in payload.accounts]
        if source == AccountImportSource.API and len(raw_rows) == 1:
            source = AccountImportSource.SINGLE

    accepted: list[AccountImportRecord] = []
    issues = list(parse_issues)
    duplicate_domains: list[str] = []
    rows: list[AccountImportRow] = []
    seen: set[str] = set()
    for row_number, row in enumerate(raw_rows, start=2 if payload.csv_text else 1):
        submitted = _submitted_domain(row)
        name = _submitted_name(row)
        record, row_issues = _record_from_mapping(row, row_number)
        issues.extend(row_issues)
        if record is None:
            first = row_issues[0] if row_issues else None
            rows.append(
                AccountImportRow(
                    row=row_number,
                    company_name=name,
                    submitted_domain=submitted,
                    verdict=ImportRowVerdict.INVALID,
                    code=first.code if first else "INVALID",
                    reason=first.message if first else "Row could not be validated",
                )
            )
            continue
        if record.domain in seen:
            duplicate_domains.append(record.domain)
            issues.append(
                AccountImportIssue(
                    row=row_number,
                    field="domain",
                    code="DUPLICATE_DOMAIN",
                    message="Duplicate canonical domain in this import",
                )
            )
            rows.append(
                AccountImportRow(
                    row=row_number,
                    company_name=record.company_name,
                    submitted_domain=submitted,
                    canonical_domain=record.domain,
                    verdict=ImportRowVerdict.DUPLICATE,
                    code="DUPLICATE_DOMAIN",
                    reason=f"{record.domain} already appears earlier in this import",
                )
            )
            continue
        seen.add(record.domain)
        accepted.append(record)
        review_reason = _identity_review_reason(record)
        rows.append(
            AccountImportRow(
                row=row_number,
                company_name=record.company_name,
                submitted_domain=submitted,
                canonical_domain=record.domain,
                verdict=(
                    ImportRowVerdict.NEEDS_REVIEW
                    if review_reason
                    else ImportRowVerdict.VALID
                ),
                code="POSSIBLE_IDENTITY_MISMATCH" if review_reason else None,
                reason=review_reason,
            )
        )
        if review_reason:
            issues.append(
                AccountImportIssue(
                    row=row_number,
                    field="domain",
                    code="POSSIBLE_IDENTITY_MISMATCH",
                    message=review_reason,
                )
            )
    summary = AccountImportSummary(
        total=len(rows),
        valid=sum(1 for item in rows if item.verdict is ImportRowVerdict.VALID),
        duplicate=sum(
            1 for item in rows if item.verdict is ImportRowVerdict.DUPLICATE
        ),
        invalid=sum(1 for item in rows if item.verdict is ImportRowVerdict.INVALID),
        needs_review=sum(
            1 for item in rows if item.verdict is ImportRowVerdict.NEEDS_REVIEW
        ),
    )
    return AccountImportValidation(
        import_source=source,
        accepted=accepted,
        issues=issues,
        duplicate_domains=sorted(set(duplicate_domains)),
        rows=rows,
        summary=summary,
    )
