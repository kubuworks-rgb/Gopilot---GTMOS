from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.app.main import app


client = TestClient(app)


def test_complete_demo_acceptance_flow() -> None:
    user = "acceptance-user"
    workspace_response = client.post(
        "/api/v1/workspaces",
        headers={"X-Demo-User": user},
        json={"name": "Kubu Works GTM"},
    )
    assert workspace_response.status_code == 201
    workspace_id = workspace_response.json()["id"]
    headers = {"X-Demo-User": user, "X-Workspace-Id": workspace_id}

    product_response = client.post(
        "/api/v1/products",
        headers=headers,
        json={
            "company_name": "Kubu Works",
            "website": "https://kubu.example",
            "product": "Evidence-backed GTM intelligence platform",
            "target_market": "Founder-led B2B SaaS companies in India",
        },
    )
    assert product_response.status_code == 201

    start = client.post(
        "/api/v1/research-runs",
        params={"product_id": product_response.json()["id"]},
        headers=headers,
    )
    assert start.status_code == 202
    run = client.get(f"/api/v1/research-runs/{start.json()['id']}", headers=headers).json()
    assert run["status"] == "awaiting_icp"
    assert {item["category"] for item in run["findings"]} == {"market", "competitor", "pain_point", "buying_trigger"}
    assert all(item["evidence_ids"] or item["status"] == "hypothesis" for item in run["findings"])

    icps = client.get("/api/v1/icps", headers=headers).json()
    assert len(icps) == 3
    selected = client.post(f"/api/v1/icps/{icps[0]['id']}/select", headers=headers)
    assert selected.status_code == 200
    assert selected.json()["selected"] is True

    accounts = client.get("/api/v1/accounts", headers=headers).json()
    assert len(accounts) == 3
    assert accounts == sorted(accounts, key=lambda item: item["scores"]["priority"], reverse=True)
    account = accounts[0]
    assert all(name in account["scores"] for name in ("fit", "intent", "confidence", "priority"))
    feedback = client.post(
        "/api/v1/feedback",
        headers=headers,
        json={
            "target_type": "account",
            "target_id": account["id"],
            "rating": "GOOD_ACCOUNT",
            "reason": "Acceptance feedback persistence check",
        },
    )
    assert feedback.status_code == 201
    assert feedback.json()["rating"] == "GOOD_ACCOUNT"

    brief_response = client.get(f"/api/v1/accounts/{account['id']}/opportunity-brief", headers=headers)
    assert brief_response.status_code == 200
    brief = brief_response.json()
    evidence_ids = {item["id"] for item in brief["evidence"]}
    for claim in brief["why_it_fits"] + brief["why_now"]:
        assert set(claim["evidence_ids"]).issubset(evidence_ids)
    assert all(source["demo_data"] for source in brief["sources"])

    campaign_id = brief["campaign"]["id"]
    edited = client.patch(f"/api/v1/campaigns/{campaign_id}", headers=headers, json={"action": "edit", "subject": "Edited subject", "body": "Edited, human-reviewed body."})
    assert edited.json()["subject"] == "Edited subject"
    approved = client.patch(f"/api/v1/campaigns/{campaign_id}", headers=headers, json={"action": "approve"})
    assert approved.json()["status"] == "approved"
    export = client.get("/api/v1/exports/accounts.csv", headers=headers)
    assert export.status_code == 200
    assert account["name"] in export.text

    events = {item["event_type"] for item in client.get("/api/v1/audit", headers=headers).json()}
    assert {"workspace_created", "product_confirmed", "research_run_started", "icp_selected", "opportunity_brief_viewed", "campaign_draft_approved", "account_exported"}.issubset(events)


def test_selecting_another_icp_refreshes_fixture_accounts() -> None:
    headers = {"X-Demo-User": "demo-user"}
    bootstrap = client.get("/api/v1/bootstrap", headers=headers).json()
    original_accounts = {item["id"] for item in bootstrap["accounts"]}
    alternative = next(item for item in bootstrap["icps"] if not item["selected"])

    selected = client.post(
        f"/api/v1/icps/{alternative['id']}/select",
        headers=headers,
    )

    assert selected.status_code == 200
    assert selected.json()["selected"] is True
    refreshed = client.get("/api/v1/bootstrap", headers=headers).json()
    assert {item["id"] for item in refreshed["accounts"]}.isdisjoint(original_accounts)
    assert {item["icp_id"] for item in refreshed["accounts"]} == {alternative["id"]}
