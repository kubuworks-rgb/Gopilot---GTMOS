from __future__ import annotations

import re
import ssl
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import httpx


_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9._:/-]{1,160}$")
_TAG_CATEGORIES = {
    "INVALID_API_KEY": "EXA_INVALID_API_KEY",
    "NO_MORE_CREDITS": "EXA_NO_MORE_CREDITS",
    "API_KEY_BUDGET_EXCEEDED": "EXA_API_KEY_BUDGET_EXCEEDED",
    "TEAM_BUDGET_EXCEEDED": "EXA_TEAM_BUDGET_EXCEEDED",
    "ACCESS_DENIED": "EXA_ACCESS_DENIED",
    "FEATURE_DISABLED": "EXA_FEATURE_DISABLED",
    "CONTENT_FILTER_ERROR": "EXA_CONTENT_FILTERED",
}


@dataclass(frozen=True)
class ExaSafeDiagnostic:
    provider: str
    transport: str
    endpoint_class: str
    http_status: int
    error_tag: str
    error_category: str
    request_id: str
    latency_ms: int
    response_content_type: str
    authenticated_request_attempted: bool
    timestamp: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def safe_token(value: object, *, fallback: str = "unavailable") -> str:
    candidate = str(value or "").strip()
    if not _SAFE_TOKEN.fullmatch(candidate):
        return fallback
    lowered = candidate.lower()
    if any(marker in lowered for marker in ("api_key", "apikey", "bearer", "cookie")):
        return fallback
    return candidate


def exa_error_tag(payload: object) -> str:
    if not isinstance(payload, dict):
        return "unavailable"
    candidates: list[object] = [
        payload.get("tag"),
        payload.get("errorTag"),
        payload.get("code"),
    ]
    error = payload.get("error")
    if isinstance(error, dict):
        candidates.extend(
            [error.get("tag"), error.get("errorTag"), error.get("code")]
        )
    for candidate in candidates:
        value = str(candidate or "").strip().upper()
        if value in _TAG_CATEGORIES:
            return value
    return "unavailable"


def exa_error_category(
    *,
    http_status: int = 0,
    error_tag: str = "unavailable",
    exception: BaseException | None = None,
    transport: str,
) -> str:
    normalized_tag = str(error_tag or "").strip().upper()
    if normalized_tag in _TAG_CATEGORIES:
        return _TAG_CATEGORIES[normalized_tag]
    if http_status == 400:
        return "EXA_INVALID_REQUEST"
    if http_status == 401:
        return "EXA_INVALID_API_KEY"
    if http_status == 402:
        return "EXA_NO_MORE_CREDITS"
    if http_status == 403:
        return "EXA_ACCESS_DENIED"
    if http_status == 422:
        return "EXA_REQUEST_UNPROCESSABLE"
    if http_status == 429:
        return "EXA_RATE_LIMITED"
    if 500 <= http_status <= 599:
        return "EXA_PROVIDER_SERVER_ERROR"
    if exception is None:
        return "EXA_UNKNOWN_FAILURE"
    if isinstance(exception, httpx.ConnectTimeout):
        return "EXA_CONNECT_TIMEOUT"
    if isinstance(exception, httpx.ReadTimeout):
        return "EXA_READ_TIMEOUT"
    if isinstance(exception, httpx.ProxyError):
        return "EXA_PROXY_FAILURE"
    if isinstance(exception, (ssl.SSLError, httpx.ConnectError)):
        detail = str(exception).lower()
        if any(marker in detail for marker in ("certificate", "ssl", "tls")):
            return "EXA_TLS_FAILURE"
        if any(marker in detail for marker in ("dns", "name resolution", "getaddrinfo")):
            return "EXA_DNS_FAILURE"
    if isinstance(exception, (ValueError, TypeError)):
        return "EXA_RESPONSE_INVALID"
    if transport == "mcp":
        return "EXA_MCP_TRANSPORT_FAILURE"
    return "EXA_UNKNOWN_FAILURE"


def diagnostic_from_response(
    response: httpx.Response,
    *,
    transport: str,
    endpoint_class: str,
    latency_ms: int,
    success_category: str,
) -> ExaSafeDiagnostic:
    payload: Any = None
    try:
        payload = response.json()
    except ValueError:
        pass
    tag = exa_error_tag(payload)
    request_id: object = response.headers.get("x-request-id")
    if isinstance(payload, dict):
        request_id = payload.get("requestId") or request_id
    category = (
        success_category
        if response.status_code == 200
        else exa_error_category(
            http_status=response.status_code,
            error_tag=tag,
            transport=transport,
        )
    )
    return ExaSafeDiagnostic(
        provider="exa",
        transport=transport,
        endpoint_class=endpoint_class,
        http_status=response.status_code,
        error_tag=tag,
        error_category=category,
        request_id=safe_token(request_id),
        latency_ms=max(0, latency_ms),
        response_content_type=safe_token(
            response.headers.get("content-type", "").split(";", 1)[0],
        ),
        authenticated_request_attempted=True,
        timestamp=datetime.now(UTC).isoformat(),
    )


def diagnostic_from_exception(
    exception: BaseException,
    *,
    transport: str,
    endpoint_class: str,
    latency_ms: int,
) -> ExaSafeDiagnostic:
    return ExaSafeDiagnostic(
        provider="exa",
        transport=transport,
        endpoint_class=endpoint_class,
        http_status=0,
        error_tag="unavailable",
        error_category=exa_error_category(
            exception=exception,
            transport=transport,
        ),
        request_id="unavailable",
        latency_ms=max(0, latency_ms),
        response_content_type="unavailable",
        authenticated_request_attempted=True,
        timestamp=datetime.now(UTC).isoformat(),
    )
