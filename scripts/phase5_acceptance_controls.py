from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from time import monotonic

import httpx

from apps.api.app.services.live_research import _news_result_matches_company
from services.research_gateway.app.adapters.search import SearchAdapter, _is_exa_relevant
from services.research_gateway.app.errors import GatewayAdapterError
from services.research_gateway.app.providers.exa_diagnostics import (
    diagnostic_from_exception,
    diagnostic_from_response,
)
from services.research_gateway.app.schemas import SearchRequest


RELIABILITY_QUERIES = (
    "OpenAI Agents SDK GitHub",
    "Indian B2B SaaS customer support software",
    "India SaaS customer success hiring",
    "B2B SaaS enterprise expansion India",
    "customer support automation market India",
)
POSITIVE_QUERY = "Freshworks launched new product enterprise expansion customer support"


def _result_count(response: httpx.Response) -> int:
    try:
        payload = response.json()
    except ValueError:
        return 0
    results = payload.get("results") if isinstance(payload, dict) else None
    return len(results) if isinstance(results, list) else 0


async def _rest_control() -> dict[str, object]:
    started = monotonic()
    try:
        async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
            response = await client.post(
                "https://api.exa.ai/search",
                headers={
                    "x-api-key": os.environ["EXA_API_KEY"],
                    "Content-Type": "application/json",
                },
                json={
                    "query": RELIABILITY_QUERIES[0],
                    "numResults": 3,
                    "contents": {"text": {"maxCharacters": 1000}},
                },
            )
        diagnostic = diagnostic_from_response(
            response,
            transport="rest",
            endpoint_class="exa_search",
            latency_ms=int((monotonic() - started) * 1000),
            success_category="EXA_REST_AUTHENTICATED_PASS",
        )
        return {
            "passed": response.status_code == 200 and _result_count(response) > 0,
            "result_count": _result_count(response),
            "diagnostic": diagnostic.as_dict(),
        }
    except Exception as exc:
        diagnostic = diagnostic_from_exception(
            exc,
            transport="rest",
            endpoint_class="exa_search",
            latency_ms=int((monotonic() - started) * 1000),
        )
        return {
            "passed": False,
            "result_count": 0,
            "diagnostic": diagnostic.as_dict(),
        }


async def _mcp_query(
    adapter: SearchAdapter,
    query: str,
    *,
    run_id: str,
    limit: int = 5,
) -> dict[str, object]:
    started = monotonic()
    try:
        results, diagnostics = await adapter.search(
            SearchRequest(
                workspace_id="phase5-acceptance",
                research_run_id=run_id,
                query=query,
                limit=limit,
                purpose="market_research",
            )
        )
    except GatewayAdapterError as exc:
        return {
            "passed": False,
            "query": query,
            "result_count": 0,
            "relevant_result_count": 0,
            "latency_ms": int((monotonic() - started) * 1000),
            "safe_provider_category": exc.code,
            "provider_attempts": [],
            "fixture_fallback": False,
        }
    attempts = [item.model_dump(mode="json") for item in diagnostics.provider_attempts]
    authenticated_exa = any(
        item.get("provider") == "exa"
        and item.get("authenticated") is True
        and item.get("outcome") == "completed"
        for item in attempts
    )
    relevant = sum(
        _is_exa_relevant(query, f"{item.title} {item.snippet}") for item in results
    )
    return {
        "passed": bool(results) and authenticated_exa,
        "query": query,
        "result_count": len(results),
        "relevant_result_count": relevant,
        "latency_ms": int((monotonic() - started) * 1000),
        "safe_provider_category": (
            "EXA_MCP_AUTHENTICATED_PASS"
            if authenticated_exa
            else "EXA_MCP_AUTHENTICATION_NOT_PROVEN"
        ),
        "provider_attempts": attempts,
        "fixture_fallback": False,
    }


async def _positive_control(adapter: SearchAdapter) -> dict[str, object]:
    result = await _mcp_query(
        adapter,
        POSITIVE_QUERY,
        run_id="phase5-positive-control",
        limit=8,
    )
    if not result["passed"]:
        return {**result, "event_detected": False, "entity_match": False}
    results, diagnostics = await adapter.search(
        SearchRequest(
            workspace_id="phase5-acceptance",
            research_run_id="phase5-positive-control-evidence",
            query=POSITIVE_QUERY,
            limit=8,
            freshness_days=730,
            purpose="market_research",
        )
    )
    matched = [
        item
        for item in results
        if _news_result_matches_company(
            item,
            company_name="Freshworks",
            domain="freshworks.com",
        )
    ]
    return {
        "passed": bool(matched),
        "query": POSITIVE_QUERY,
        "event_detected": bool(matched),
        "entity_match": bool(matched),
        "result_count": len(results),
        "matched_result_count": len(matched),
        "precision_percent": (
            round(len(matched) / len(results) * 100, 2) if results else None
        ),
        "recall_percent": 100.0 if matched else 0.0,
        "provider_attempts": [
            item.model_dump(mode="json") for item in diagnostics.provider_attempts
        ],
        "evidence_candidates": [
            {
                "title": item.title[:240],
                "url": str(item.url),
                "published_at": (
                    item.published_at.isoformat() if item.published_at else None
                ),
            }
            for item in matched[:5]
        ],
        "fixture_fallback": False,
    }


def _development_precision(root: Path) -> dict[str, object]:
    payload = json.loads(
        (root / "docs/qa/history/PREQUALIFICATION_RECALL_REPLAY.json").read_text(
            encoding="utf-8"
        )
    )
    first_30 = payload["first_30"]
    metrics = {
        "old": first_30["old_metrics"],
        "new": first_30["new_metrics"],
        "labelled_count": first_30["labelled_count"],
        "uncertain_excluded": first_30["uncertain_excluded"],
    }
    new_metrics = metrics["new"]
    return {
        "passed": new_metrics["recall"] >= 0.85
        and new_metrics["precision"] >= 0.70
        and new_metrics["false_negative_rate"] <= 0.15,
        "dataset": "preserved first-30 development labels",
        "metrics": metrics,
    }


def _mock_payload(root: Path) -> dict[str, object]:
    attempt = {
        "provider": "exa",
        "authenticated": True,
        "outcome": "completed",
        "result_count": 5,
        "error_code": None,
        "latency_ms": 1,
    }
    reliability = [
        {
            "passed": True,
            "query": query,
            "result_count": 5,
            "relevant_result_count": 5,
            "latency_ms": 1,
            "safe_provider_category": "MOCK_EXA_MCP_AUTHENTICATED_PASS",
            "provider_attempts": [attempt],
            "fixture_fallback": False,
        }
        for query in RELIABILITY_QUERIES
    ]
    return {
        "mode": "mock",
        "rest_control": {
            "passed": True,
            "result_count": 3,
            "diagnostic": {
                "provider": "exa",
                "transport": "rest",
                "error_category": "MOCK_EXA_REST_AUTHENTICATED_PASS",
                "authenticated_request_attempted": True,
            },
        },
        "mcp_preflight": reliability[0],
        "reliability": reliability,
        "candidate_precision": _development_precision(root),
        "positive_signal_control": {
            "passed": True,
            "event_detected": True,
            "entity_match": True,
            "precision_percent": 100.0,
            "recall_percent": 100.0,
            "provider_attempts": [attempt],
            "fixture_fallback": False,
        },
        "provider": {
            "primary": "exa",
            "authenticated": True,
            "anonymous_mcp_capacity": False,
            "tavily": "NOT_CONFIGURED",
        },
    }


async def _live_payload(root: Path) -> dict[str, object]:
    if not os.environ.get("EXA_API_KEY"):
        raise RuntimeError("EXA_API_KEY is required for live controls")
    adapter = SearchAdapter()
    rest = await _rest_control()
    reliability = [
        await _mcp_query(adapter, query, run_id=f"phase5-reliability-{index}")
        for index, query in enumerate(RELIABILITY_QUERIES, 1)
    ]
    attempts = [
        attempt
        for item in reliability
        for attempt in item.get("provider_attempts", [])
    ]
    authenticated_exa = bool(attempts) and all(
        attempt.get("provider") == "exa"
        and attempt.get("authenticated") is True
        for attempt in attempts
        if attempt.get("outcome") != "not_configured"
    )
    return {
        "mode": "live",
        "rest_control": rest,
        "mcp_preflight": reliability[0],
        "reliability": reliability,
        "candidate_precision": _development_precision(root),
        "positive_signal_control": await _positive_control(adapter),
        "provider": {
            "primary": "exa",
            "authenticated": authenticated_exa,
            "anonymous_mcp_capacity": not authenticated_exa,
            "tavily": (
                "CONFIGURED" if os.environ.get("TAVILY_API_KEY") else "NOT_CONFIGURED"
            ),
        },
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("live", "mock"), default="live")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    payload = (
        _mock_payload(root)
        if args.mode == "mock"
        else await _live_payload(root)
    )
    payload["all_passed"] = (
        payload["rest_control"]["passed"]
        and payload["mcp_preflight"]["passed"]
        and all(item["passed"] for item in payload["reliability"])
        and payload["candidate_precision"]["passed"]
        and payload["positive_signal_control"]["passed"]
        and payload["provider"]["authenticated"]
        and not payload["provider"]["anonymous_mcp_capacity"]
    )
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0 if payload["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
