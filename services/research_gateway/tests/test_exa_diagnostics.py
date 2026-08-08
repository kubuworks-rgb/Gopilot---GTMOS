from __future__ import annotations

import httpx
import pytest

from services.research_gateway.app.adapters.search import (
    _exa_http_error,
    _mcp_result,
)
from services.research_gateway.app.errors import GatewayAdapterError
from services.research_gateway.app.providers.exa_diagnostics import (
    diagnostic_from_exception,
    diagnostic_from_response,
    exa_error_category,
    safe_token,
)


@pytest.mark.parametrize(
    ("status", "tag", "expected"),
    [
        (400, "", "EXA_INVALID_REQUEST"),
        (401, "INVALID_API_KEY", "EXA_INVALID_API_KEY"),
        (402, "NO_MORE_CREDITS", "EXA_NO_MORE_CREDITS"),
        (402, "API_KEY_BUDGET_EXCEEDED", "EXA_API_KEY_BUDGET_EXCEEDED"),
        (402, "TEAM_BUDGET_EXCEEDED", "EXA_TEAM_BUDGET_EXCEEDED"),
        (403, "ACCESS_DENIED", "EXA_ACCESS_DENIED"),
        (403, "FEATURE_DISABLED", "EXA_FEATURE_DISABLED"),
        (403, "CONTENT_FILTER_ERROR", "EXA_CONTENT_FILTERED"),
        (422, "", "EXA_REQUEST_UNPROCESSABLE"),
        (429, "", "EXA_RATE_LIMITED"),
        (503, "", "EXA_PROVIDER_SERVER_ERROR"),
    ],
)
def test_exa_http_failures_are_typed(
    status: int, tag: str, expected: str
) -> None:
    assert (
        exa_error_category(
            http_status=status,
            error_tag=tag,
            transport="rest",
        )
        == expected
    )


@pytest.mark.parametrize(
    ("exception", "transport", "expected"),
    [
        (httpx.ConnectTimeout("bounded"), "rest", "EXA_CONNECT_TIMEOUT"),
        (httpx.ReadTimeout("bounded"), "rest", "EXA_READ_TIMEOUT"),
        (httpx.ProxyError("proxy"), "rest", "EXA_PROXY_FAILURE"),
        (ValueError("invalid json"), "rest", "EXA_RESPONSE_INVALID"),
        (RuntimeError("protocol"), "mcp", "EXA_MCP_TRANSPORT_FAILURE"),
    ],
)
def test_exa_transport_failures_are_typed(
    exception: BaseException, transport: str, expected: str
) -> None:
    assert (
        diagnostic_from_exception(
            exception,
            transport=transport,
            endpoint_class=f"exa_{transport}",
            latency_ms=12,
        ).error_category
        == expected
    )


def test_response_diagnostic_retains_only_safe_fields() -> None:
    response = httpx.Response(
        401,
        headers={
            "content-type": "application/json; charset=utf-8",
            "x-request-id": "request-safe-123",
            "x-api-key": "must-never-appear",
            "set-cookie": "must-never-appear",
        },
        json={
            "error": {
                "tag": "INVALID_API_KEY",
                "message": "raw provider response must never persist",
            }
        },
    )

    diagnostic = diagnostic_from_response(
        response,
        transport="rest",
        endpoint_class="exa_search",
        latency_ms=7,
        success_category="EXA_REST_AUTHENTICATED_PASS",
    ).as_dict()

    assert set(diagnostic) == {
        "provider",
        "transport",
        "endpoint_class",
        "http_status",
        "error_tag",
        "error_category",
        "request_id",
        "latency_ms",
        "response_content_type",
        "authenticated_request_attempted",
        "timestamp",
    }
    assert diagnostic["error_category"] == "EXA_INVALID_API_KEY"
    assert diagnostic["request_id"] == "request-safe-123"
    assert "must-never-appear" not in repr(diagnostic)
    assert "raw provider response" not in repr(diagnostic)


def test_authenticated_rest_success_is_recorded_without_headers(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_key = "test-only-key-material"
    response = httpx.Response(
        200,
        headers={
            "content-type": "application/json",
            "x-api-key": fake_key,
        },
        json={
            "requestId": "request-safe-200",
            "results": [
                {"title": "Public result", "url": "https://example.com"}
            ],
        },
    )

    diagnostic = diagnostic_from_response(
        response,
        transport="rest",
        endpoint_class="exa_search",
        latency_ms=9,
        success_category="EXA_REST_AUTHENTICATED_PASS",
    ).as_dict()

    assert diagnostic["http_status"] == 200
    assert diagnostic["error_category"] == "EXA_REST_AUTHENTICATED_PASS"
    assert diagnostic["request_id"] == "request-safe-200"
    assert fake_key not in repr(diagnostic)
    assert fake_key not in caplog.text


def test_request_identifier_and_secret_like_values_are_redacted() -> None:
    assert safe_token("request-safe-123") == "request-safe-123"
    assert safe_token("Bearer secret-material") == "unavailable"
    assert safe_token("api_key=secret-material") == "unavailable"


@pytest.mark.parametrize(
    ("status", "tag", "expected"),
    [
        (401, "INVALID_API_KEY", "EXA_INVALID_API_KEY"),
        (402, "NO_MORE_CREDITS", "EXA_NO_MORE_CREDITS"),
        (403, "ACCESS_DENIED", "EXA_ACCESS_DENIED"),
        (422, "", "EXA_REQUEST_UNPROCESSABLE"),
        (429, "", "EXA_RATE_LIMITED"),
    ],
)
def test_production_mcp_http_failures_use_typed_safe_codes(
    status: int, tag: str, expected: str
) -> None:
    response = httpx.Response(
        status,
        json={
            "error": {
                "tag": tag,
                "message": "provider body must not enter the application error",
            }
        },
    )

    error = _exa_http_error(response)

    assert error.code == expected
    assert "provider body" not in str(error)


def test_mcp_protocol_error_does_not_persist_raw_provider_message() -> None:
    secret_marker = "raw-sensitive-provider-message"
    response = httpx.Response(
        200,
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "error": {"code": -32603, "message": secret_marker},
        },
    )

    with pytest.raises(GatewayAdapterError) as caught:
        _mcp_result(response, expected_id=2)

    assert caught.value.code == "EXA_MCP_TRANSPORT_FAILURE"
    assert secret_marker not in str(caught.value)
