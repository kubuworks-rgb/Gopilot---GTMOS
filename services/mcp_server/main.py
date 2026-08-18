"""GoPilot as an MCP server: entity-safe research for agent builders.

Speaks MCP over stdio -- newline-delimited JSON-RPC 2.0. Implemented against
the standard library rather than an SDK, because the surface actually needed
(initialize, tools/list, tools/call) is small, and this repo's value is partly
that it drags no dependency tree behind it.

**Read-only by construction.** Every tool here reads. There is no tool that
approves a draft, promotes an account to FOUNDER_READY, or sends anything --
not because a check rejects the attempt, but because no such tool is defined
and the server never issues a non-GET request. `test_mcp_server.py` asserts
that from the outside: it walks the advertised tool list and the HTTP verbs the
server can emit, and fails if either grows a write.

Run it:

    python -m services.mcp_server.main

Point an MCP client at that command. `check_entity_attachment` needs nothing
running; the two research tools read from a GoPilot API, which in demo mode is
`npx gopilot -y` and needs no keys, no Docker and no database.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from entity_safety import (
    ClaimScope,
    CompanyIdentityRecord,
    EntityRelation,
    VerifiedEntityRelationship,
    assess_evidence_attachment,
)


PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "gopilot"
SERVER_VERSION = "0.1.0"

API_BASE = os.getenv("GOPILOT_API_BASE", "http://127.0.0.1:8000/api/v1")

# The only HTTP method this server is permitted to use. Kept as a constant so
# the never-acts test can assert on it rather than trusting a code review.
ALLOWED_HTTP_METHODS = ("GET",)


class ApiUnavailable(RuntimeError):
    """The GoPilot API is not reachable."""


def _get(path: str, params: dict[str, str] | None = None) -> Any:
    """Read from the GoPilot API. GET only, by construction."""
    url = f"{API_BASE}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, method=ALLOWED_HTTP_METHODS[0])
    request.add_header("Accept", "application/json")
    # Demo mode identifies the caller with a header; with OIDC enabled the
    # client supplies a bearer token instead.
    token = os.getenv("GOPILOT_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    else:
        request.add_header("X-Demo-User", os.getenv("GOPILOT_DEMO_USER", "demo-user"))
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise ApiUnavailable(
            f"Could not reach the GoPilot API at {API_BASE} ({exc}). "
            "Start it with `npx gopilot -y` -- demo mode needs no keys."
        ) from exc


# --------------------------------------------------------------------------- tools


def tool_check_entity_attachment(arguments: dict[str, Any]) -> dict[str, Any]:
    """The differentiated capability, and the only one that needs nothing running."""
    target_name = str(arguments["target_name"])
    target_domain = str(arguments["target_domain"])
    relationships = tuple(
        VerifiedEntityRelationship(
            subject_domain=str(item["domain"]),
            object_domain=target_domain,
            relation=EntityRelation(str(item["relation"])),
            # A relationship counts only when the caller says it is proven.
            evidence_ids=("caller-supplied",) if item.get("evidence_backed") else (),
        )
        for item in arguments.get("known_relationships", [])
    )
    identity = CompanyIdentityRecord(
        canonical_company_name=target_name,
        canonical_registrable_domain=target_domain,
        verified_official_domains=tuple(
            arguments.get("verified_official_domains", [target_domain])
        ),
        relationships=relationships,
    )
    scope = arguments.get("claim_scope")
    assessment = assess_evidence_attachment(
        identity,
        source_url=str(arguments["source_url"]),
        source_role=str(arguments.get("source_role", "FIRST_PARTY")),
        source_title=str(arguments.get("source_title", "")),
        passage=str(arguments.get("passage", "")),
        claim_scope=ClaimScope(scope) if scope else None,
        conflicting_entities=tuple(arguments.get("conflicting_entities", [])),
    )
    return {
        "decision": str(assessment.decision),
        "reason": assessment.reason,
        "relation": str(assessment.relation),
        "claim_scope": str(assessment.claim_scope),
        "identity_compatible": assessment.identity_compatible,
        "claim_scope_compatible": assessment.claim_scope_compatible,
        "entity_match_confidence": assessment.entity_match_confidence,
        "source_domain": assessment.source_domain,
    }


def tool_list_accounts(arguments: dict[str, Any]) -> dict[str, Any]:
    del arguments
    data = _get("/bootstrap")
    return {
        "mode": data.get("mode"),
        "demo_data": data.get("demo_data"),
        "accounts": [
            {
                "id": account["id"],
                "name": account["name"],
                "domain": account["domain"],
                "state": account.get("brief_state"),
                "priority": account["scores"]["priority"],
                "fit": account["scores"]["fit"]["score"],
                "fit_determined": account["scores"]["fit"].get("determined", True),
                "intent": account["scores"]["intent"]["score"],
                "confidence": account["scores"]["confidence"]["score"],
                "top_signal": account.get("top_signal"),
            }
            for account in data.get("accounts", [])
        ],
    }


def tool_get_account_brief(arguments: dict[str, Any]) -> dict[str, Any]:
    """The brief with its evidence, so a claim can be traced to a source."""
    account_id = str(arguments["account_id"])
    brief = _get(f"/accounts/{account_id}/opportunity-brief")
    sources = {source["id"]: source for source in brief.get("sources", [])}
    return {
        "account": {
            "name": brief["account"]["name"],
            "domain": brief["account"]["domain"],
            "state": brief.get("brief_state"),
            "scores": brief["account"]["scores"],
        },
        "recommended_action": brief.get("recommended_action"),
        "why_it_fits": brief.get("why_it_fits", []),
        "why_now": brief.get("why_now", []),
        "unknowns": brief.get("unknowns", []),
        "evidence": [
            {
                "claim": item.get("claim"),
                "passage": item.get("passage"),
                "status": item.get("status"),
                "source_url": (
                    sources.get(item.get("source_id"), {}).get("canonical_url")
                    or sources.get(item.get("source_id"), {}).get("url")
                ),
            }
            for item in brief.get("evidence", [])
        ],
        "retrieval": brief.get("retrieval"),
        "note": (
            "Read-only. Approving a draft or promoting an account to "
            "FOUNDER_READY is a human action in the GoPilot UI; this server "
            "exposes no tool that can do either."
        ),
    }


TOOLS: list[dict[str, Any]] = [
    {
        "name": "check_entity_attachment",
        "description": (
            "Decide whether a passage may support a claim about a specific "
            "company, or whether it is about a different or merely related "
            "one. Returns a decision with an auditable reason. Catches the "
            "case where two companies share a brand token on different "
            "domains. Needs no running service."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["target_name", "target_domain", "source_url"],
            "properties": {
                "target_name": {"type": "string", "description": "Company the claim is meant to be about."},
                "target_domain": {"type": "string", "description": "Its registrable domain, e.g. optivian.ai"},
                "verified_official_domains": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Domains proven to belong to the target. Defaults to target_domain.",
                },
                "source_url": {"type": "string", "description": "Where the passage came from."},
                "source_role": {
                    "type": "string", "enum": ["FIRST_PARTY", "THIRD_PARTY"],
                    "description": "FIRST_PARTY if retrieved from a company's own site.",
                },
                "source_title": {"type": "string"},
                "passage": {"type": "string", "description": "The text being attached."},
                "claim_scope": {
                    "type": "string",
                    "enum": [scope.value for scope in ClaimScope],
                    "description": "Level the claim is about. Inferred from the passage if omitted.",
                },
                "known_relationships": {
                    "type": "array",
                    "description": "Relationships to the target. Unproven ones are treated as unknown.",
                    "items": {
                        "type": "object",
                        "required": ["domain", "relation"],
                        "properties": {
                            "domain": {"type": "string"},
                            "relation": {"type": "string", "enum": [r.value for r in EntityRelation]},
                            "evidence_backed": {"type": "boolean"},
                        },
                    },
                },
                "conflicting_entities": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Names known to be confusable with the target.",
                },
            },
        },
        "handler": tool_check_entity_attachment,
    },
    {
        "name": "list_accounts",
        "description": (
            "List researched accounts with their deterministic fit, intent, "
            "confidence and priority scores. `fit_determined: false` means the "
            "dimension could not be established and was excluded from the "
            "score rather than counted as zero."
        ),
        "inputSchema": {"type": "object", "properties": {}},
        "handler": tool_list_accounts,
    },
    {
        "name": "get_account_brief",
        "description": (
            "Get an account's opportunity brief: what it claims, the evidence "
            "passage and source URL behind each claim, what remains unknown, "
            "and how much of the site was actually read."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["account_id"],
            "properties": {"account_id": {"type": "string"}},
        },
        "handler": tool_get_account_brief,
    },
]

TOOLS_BY_NAME = {tool["name"]: tool for tool in TOOLS}


def advertised_tools() -> list[dict[str, Any]]:
    return [
        {k: v for k, v in tool.items() if k != "handler"} for tool in TOOLS
    ]


# ------------------------------------------------------------------------ protocol


def handle(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    message_id = message.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": message_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }

    if method in {"notifications/initialized", "initialized"}:
        return None  # notification: no reply

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": message_id,
            "result": {"tools": advertised_tools()},
        }

    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        tool = TOOLS_BY_NAME.get(name)
        if tool is None:
            return {
                "jsonrpc": "2.0",
                "id": message_id,
                "error": {"code": -32602, "message": f"Unknown tool: {name}"},
            }
        try:
            payload = tool["handler"](params.get("arguments") or {})
            text = json.dumps(payload, indent=2, default=str)
            is_error = False
        except ApiUnavailable as exc:
            text = str(exc)
            is_error = True
        except (KeyError, ValueError) as exc:
            text = f"Invalid arguments for {name}: {exc}"
            is_error = True
        return {
            "jsonrpc": "2.0",
            "id": message_id,
            "result": {
                "content": [{"type": "text", "text": text}],
                "isError": is_error,
            },
        }

    if message_id is None:
        return None
    return {
        "jsonrpc": "2.0",
        "id": message_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def serve(stdin: Any = None, stdout: Any = None) -> None:
    source = stdin if stdin is not None else sys.stdin
    sink = stdout if stdout is not None else sys.stdout
    for line in source:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = handle(message)
        if response is None:
            continue
        sink.write(json.dumps(response) + "\n")
        sink.flush()


if __name__ == "__main__":  # pragma: no cover
    serve()
