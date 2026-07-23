from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from apps.api.app.config import Settings
from apps.api.app.main import app
from apps.api.app.services.scoring import score_account, signal_decay
from apps.api.app.workflows.research_graph import STAGES, build_research_graph


client = TestClient(app)


def test_cross_workspace_access_is_forbidden() -> None:
    workspace = client.post(
        "/api/v1/workspaces",
        headers={"X-Demo-User": "owner-a"},
        json={"name": "Tenant A"},
    ).json()
    response = client.get("/api/v1/bootstrap", headers={"X-Demo-User": "attacker-b", "X-Workspace-Id": workspace["id"]})
    assert response.status_code == 403


def test_scoring_is_deterministic_and_fit_is_separate_from_intent() -> None:
    def calculate_score():
        return score_account(
            industry_match=90,
            size_match=80,
            geography_match=100,
            signal_strength=60,
            signal_recency=70,
            evidence_coverage=85,
            source_quality=90,
            fit_evidence=["fit"],
            signal_evidence=["intent"],
        )

    first = calculate_score()
    second = calculate_score()
    assert first == second
    assert first.fit.score != first.intent.score
    assert first.priority == round((first.fit.score * .55 + first.intent.score * .45) * first.confidence.score / 100)


def test_old_signals_decay() -> None:
    recent = signal_decay(datetime.now(UTC) - timedelta(days=1))
    old = signal_decay(datetime.now(UTC) - timedelta(days=90))
    assert recent > old
    assert old == pytest.approx(.25, abs=.01)


def test_production_rejects_demo_and_fixtures() -> None:
    with pytest.raises(RuntimeError, match="Production forbids"):
        Settings(app_env="production", research_mode="fixture", demo_auth_enabled=True).validate()


def test_csv_formula_injection_is_neutralized() -> None:
    from apps.api.app.api.routes import _csv_safe

    assert _csv_safe("=HYPERLINK('bad')").startswith("'")
    assert _csv_safe("Normal Co") == "Normal Co"


def test_langgraph_workflow_is_bounded_and_deterministic() -> None:
    graph = build_research_graph(checkpointed=False)
    result = graph.invoke({"workflow_run_id": "run_test", "workspace_id": "ws_test", "completed_stages": [], "status": "queued"})
    assert result["completed_stages"] == list(STAGES)
    assert result["status"] == "completed"
