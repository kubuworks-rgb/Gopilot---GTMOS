from __future__ import annotations

import importlib
import json
import subprocess
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


def test_phase5_runner_normalizes_case_colliding_path_before_children() -> None:
    runner = (ROOT / "scripts" / "phase5_secure_acceptance.ps1").read_text(
        encoding="utf-8"
    )

    normalize_call = runner.index("Normalize-ProcessPath")
    prompt = runner.index('Read-Host "Paste rotated EXA_API_KEY"')
    assert normalize_call < prompt
    assert (
        '[Environment]::SetEnvironmentVariable("PATH", $null, "Process")'
        in runner
    )
    assert (
        '[Environment]::SetEnvironmentVariable("Path", $processPath, "Process")'
        in runner
    )
    assert "-m scripts.phase5_acceptance_controls" in runner
    assert "-m scripts.phase5_holdout_export" in runner
    assert "& $python -m scripts.evaluate_supportpilot_v2" in runner
    assert 'Join-Path $root "scripts\\phase5_acceptance_controls.py"' not in runner
    assert 'Join-Path $root "scripts\\phase5_holdout_export.py"' not in runner


def test_phase5_mock_orchestration_reaches_every_stage(tmp_path: Path) -> None:
    diagnostics = tmp_path / "phase5-mock.json"
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts" / "phase5_secure_acceptance.ps1"),
            "-Mode",
            "Mock",
            "-DiagnosticsPath",
            str(diagnostics),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(diagnostics.read_text(encoding="utf-8-sig"))
    assert payload["all_passed"] is True
    assert payload["credential_prompted"] is False
    assert payload["credential_persisted"] is False
    assert payload["cleanup_contract"] == "outermost_finally"
    assert payload["stage_history"] == [
        "AUTHENTICATED_REST_CONTROL",
        "AUTHENTICATED_MCP_PREFLIGHT",
        "PROVIDER_RELIABILITY",
        "CANDIDATE_PRECISION",
        "POSITIVE_SIGNAL_CONTROL",
        "CLEAN_SUPPORTPILOT_V2_HOLDOUT",
        "DISCOVERY_FUNNEL_REPORTING",
        "TOP10_MANUAL_QA",
        "EVIDENCE_LINK_VALIDATION",
        "OPPORTUNITY_BRIEF_USEFULNESS",
        "FOUNDER_VALUE_EVALUATION",
        "FINAL_ENGINEERING_GATES",
        "SECRET_SCAN",
        "COMPLETE",
    ]


def test_phase5_failure_cleanup_preserves_only_redacted_status() -> None:
    failure_status = ROOT / "tmp" / "phase5-acceptance-last-status.json"
    failure_status.unlink(missing_ok=True)
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts" / "phase5_secure_acceptance.ps1"),
            "-Mode",
            "Mock",
            "-InjectMockFailure",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    try:
        assert completed.returncode == 1
        payload = json.loads(failure_status.read_text(encoding="utf-8-sig"))
        assert payload["failure_code"] == "INJECTED_MOCK_FAILURE"
        assert payload["failure_stage"] == "AUTHENTICATED_REST_CONTROL"
        assert payload["cleanup_complete"] is True
        assert payload["credential_remaining"] is False
        assert not (ROOT / "tmp" / "phase5-acceptance").exists()
    finally:
        failure_status.unlink(missing_ok=True)
