from __future__ import annotations

import importlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_positive_control_entity_match_helper_comes_from_live_research() -> None:
    module = importlib.import_module("apps.api.app.services.live_research")

    helper = getattr(module, "_news_result_matches_company")

    assert callable(helper)
    search_adapter = importlib.import_module(
        "services.research_gateway.app.adapters.search"
    )
    assert not hasattr(search_adapter, "_news_result_matches_company")


def test_v2_acceptance_limits_are_preserved_by_inner_harness() -> None:
    wrapper = (ROOT / "scripts" / "supportpilot_v2_acceptance.ps1").read_text(
        encoding="utf-8"
    )
    harness = (ROOT / "scripts" / "supportpilot_acceptance.ps1").read_text(
        encoding="utf-8"
    )

    assert '$env:MAX_ACCOUNT_CANDIDATES = "60"' in wrapper
    assert '$env:MAX_ACCOUNTS_RESEARCHED = "20"' in wrapper
    assert "if (-not $env:MAX_ACCOUNT_CANDIDATES)" in harness
    assert "if (-not $env:MAX_ACCOUNTS_RESEARCHED)" in harness
