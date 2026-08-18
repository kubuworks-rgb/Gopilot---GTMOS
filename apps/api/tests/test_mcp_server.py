"""The MCP server must expose useful capability without exposing action.

GoPilot's central guarantee is that it never acts: no outreach is sent, and
FOUNDER_READY is earned from evidence rather than granted. Putting the product
behind an agent protocol is exactly where that guarantee would quietly erode,
so it is asserted here from the outside rather than trusted to review.
"""

from __future__ import annotations

import io
import json

import pytest

from services.mcp_server import main as mcp


def _roundtrip(messages: list[dict]) -> list[dict]:
    stdin = io.StringIO("\n".join(json.dumps(m) for m in messages) + "\n")
    stdout = io.StringIO()
    mcp.serve(stdin=stdin, stdout=stdout)
    return [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]


def test_initialize_handshake() -> None:
    [response] = _roundtrip([{"jsonrpc": "2.0", "id": 1, "method": "initialize"}])
    assert response["result"]["serverInfo"]["name"] == "gopilot"
    assert "tools" in response["result"]["capabilities"]


def test_notifications_get_no_reply() -> None:
    assert _roundtrip([{"jsonrpc": "2.0", "method": "notifications/initialized"}]) == []


def test_tools_are_advertised_without_their_handlers() -> None:
    [response] = _roundtrip([{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}])
    tools = response["result"]["tools"]
    assert {tool["name"] for tool in tools} == {
        "check_entity_attachment",
        "list_accounts",
        "get_account_brief",
    }
    for tool in tools:
        assert "handler" not in tool, "internal callable leaked into the protocol"
        assert tool["description"] and tool["inputSchema"]


# --------------------------------------------------------------- the never-acts gate

# Checked against tool *names* only. The words legitimately appear in prose --
# a description may explain that approving is a human action this server cannot
# perform -- but a tool named for an action is a tool that performs one.
ACTION_WORDS = (
    "approve", "reject", "send", "email", "outreach", "campaign",
    "promote", "founder_ready", "delete", "update", "create", "import",
    "review", "write", "set_", "patch", "post",
)


@pytest.mark.parametrize("tool", mcp.advertised_tools(), ids=lambda t: t["name"])
def test_no_tool_is_named_for_an_action(tool: dict) -> None:
    offenders = [word for word in ACTION_WORDS if word in tool["name"].lower()]
    assert not offenders, (
        f"{tool['name']} looks like a write operation ({offenders}). "
        "This server is read-only; actions stay human."
    )


def test_the_server_can_only_issue_get_requests() -> None:
    """The transport itself is read-only, not merely used carefully."""
    assert mcp.ALLOWED_HTTP_METHODS == ("GET",)


def test_no_mutating_verb_appears_in_the_source() -> None:
    """A future tool cannot quietly add a write without this failing."""
    import pathlib

    source = pathlib.Path(mcp.__file__).read_text(encoding="utf-8")
    for verb in ('method="POST"', 'method="PATCH"', 'method="DELETE"', 'method="PUT"'):
        assert verb not in source, f"MCP server gained a mutating request: {verb}"


# ------------------------------------------------------------- the differentiator


def test_entity_attachment_refuses_a_different_domain_with_the_same_name() -> None:
    """The optivian.ai / optivian.cloud case, through the protocol."""
    [response] = _roundtrip([
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "check_entity_attachment",
                "arguments": {
                    "target_name": "Optivian",
                    "target_domain": "optivian.ai",
                    "source_url": "https://optivian.cloud/press/series-b",
                    "source_role": "FIRST_PARTY",
                    "source_title": "Optivian raises Series B",
                    "passage": "Optivian today announced a $40M Series B.",
                },
            },
        }
    ])
    payload = json.loads(response["result"]["content"][0]["text"])
    assert response["result"]["isError"] is False
    assert payload["decision"] == "UNATTACHED_ENTITY_AMBIGUOUS"
    assert payload["identity_compatible"] is False
    assert payload["reason"]


def test_entity_attachment_accepts_the_verified_official_domain() -> None:
    [response] = _roundtrip([
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "check_entity_attachment",
                "arguments": {
                    "target_name": "Optivian",
                    "target_domain": "optivian.ai",
                    "source_url": "https://optivian.ai/about",
                    "source_role": "FIRST_PARTY",
                    "passage": "Optivian builds developer tooling.",
                },
            },
        }
    ])
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["decision"] == "ATTACHED"


def test_entity_attachment_needs_no_running_service() -> None:
    """The differentiated tool must work with nothing else running."""
    result = mcp.tool_check_entity_attachment({
        "target_name": "Acme",
        "target_domain": "acme.com",
        "source_url": "https://acme.io/about",
    })
    assert result["decision"] == "UNATTACHED_ENTITY_AMBIGUOUS"


def test_unknown_tool_is_a_protocol_error() -> None:
    [response] = _roundtrip([
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "send_outreach", "arguments": {}}}
    ])
    assert response["error"]["code"] == -32602


def test_bad_arguments_are_reported_not_raised() -> None:
    [response] = _roundtrip([
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "check_entity_attachment", "arguments": {}}}
    ])
    assert response["result"]["isError"] is True
