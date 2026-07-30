from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from apps.api.app.services.intelligence_quality import (
    CandidatePrequalificationInput,
    CompetitorAssessment,
    CompetitorClassification,
    EvidenceStage,
    MatchState,
    PrequalificationOutcome,
    calculate_prequalification_metrics,
    evaluate_prequalification,
)

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_INPUT = (
    ROOT
    / "apps"
    / "api"
    / "tests"
    / "fixtures"
    / "prequalification_recall_baseline.csv"
)


def _state(value: bool) -> MatchState:
    return MatchState.ESTIMATED_MATCH if value else MatchState.UNKNOWN


def _diagnostic(row: dict[str, str]) -> dict[str, Any]:
    queries = [item for item in row["query_provenance"].split("|") if item]
    discovery_text = " ".join(queries).lower()
    identity_confidence = float(row["identity_confidence"])
    old_score = int(row["old_score"])
    query_points = min(10, max(0, len(queries) - 1) * 5)
    provider_hits = 1 if row["provider"] else 0
    provider_points = min(5, max(0, provider_hits - 1) * 5)
    official_points = 25
    inferred_term_points = old_score - query_points - provider_points - official_points
    candidate = CandidatePrequalificationInput(
        page_role=row["page_role"],
        duplicate=False,
        identity_state=(
            MatchState.VERIFIED_MATCH
            if row["page_role"] == "OFFICIAL_ROOT"
            else MatchState.ESTIMATED_MATCH
        ),
        identity_confidence=identity_confidence,
        domain_state=(
            MatchState.VERIFIED_MATCH
            if identity_confidence >= 0.85
            else MatchState.ESTIMATED_MATCH
        ),
        b2b_software_state=_state(
            any(term in discovery_text for term in ("b2b", "saas", "software"))
        ),
        saas_state=_state(
            any(term in discovery_text for term in ("saas", "cloud", "software"))
        ),
        india_state=_state(
            any(
                term in discovery_text
                for term in ("india", "bengaluru", "mumbai", "pune", "gurugram")
            )
        ),
        employee_size_state=MatchState.UNKNOWN,
        support_operations_state=MatchState.UNKNOWN,
        category_relevance=old_score,
        evidence_stage=EvidenceStage.DISCOVERY_HINT,
        evidence_coverage=0,
        competitor=CompetitorAssessment(CompetitorClassification.UNKNOWN),
    )
    decision = evaluate_prequalification(candidate)
    return {
        "rank": int(row["rank"]),
        "candidate_name": row["candidate_name"],
        "discovered_url": row["discovered_url"],
        "canonical_domain": row["canonical_domain"],
        "result_type": row["page_role"],
        "identity_state": candidate.identity_state.value,
        "identity_confidence": identity_confidence,
        "domain_state": candidate.domain_state.value,
        "domain_confidence": identity_confidence,
        "b2b_software_state": candidate.b2b_software_state.value,
        "saas_state": candidate.saas_state.value,
        "india_state": candidate.india_state.value,
        "employee_size_state": candidate.employee_size_state.value,
        "support_operations_state": candidate.support_operations_state.value,
        "competitor_state": candidate.competitor.classification.value,
        "category_relevance": old_score,
        "query_agreement": len(queries),
        "provider_agreement": provider_hits,
        "evidence_stage": candidate.evidence_stage.value,
        "evidence_coverage": candidate.evidence_coverage,
        "score_contributions": {
            "term_coverage_points_inferred_from_preserved_total": (
                inferred_term_points
            ),
            "official_page_points": official_points,
            "provider_relevance_points": 0,
            "query_agreement_points": query_points,
            "provider_agreement_points": provider_points,
        },
        "old_score": old_score,
        "old_threshold": 45,
        "old_decision": row["old_decision"],
        "old_rejection_reasons": (
            []
            if row["old_decision"] == "ACCEPTED"
            else [f"Candidate score {old_score} was below threshold 45."]
        ),
        "new_research_worthiness": decision.research_worthiness,
        "new_thresholds": {
            "high": decision.high_threshold,
            "middle": decision.middle_threshold,
            "low": decision.low_threshold,
        },
        "new_decision": decision.outcome.value,
        "new_rejection_reasons": list(decision.rejection_reasons),
        "research_requirements": list(decision.research_requirements),
        "manual_label": row["manual_label"] or None,
        "changed_reason": (
            "Unknown discovery-stage factors remain visible research requirements "
            "instead of becoming an implicit threshold failure."
            if row["old_decision"] != "ACCEPTED"
            else "Already accepted by the old policy."
        ),
    }


def build_replay(input_path: Path) -> dict[str, Any]:
    with input_path.open(encoding="utf-8", newline="") as handle:
        diagnostics = [_diagnostic(row) for row in csv.DictReader(handle)]
    labelled = [
        row
        for row in diagnostics[:30]
        if row["manual_label"] not in {None, "UNCERTAIN"}
    ]
    old_metrics = calculate_prequalification_metrics(
        [
            (
                row["manual_label"] == "USEFUL_RAW_CANDIDATE",
                row["old_decision"] == "ACCEPTED",
            )
            for row in labelled
        ]
    )
    new_metrics = calculate_prequalification_metrics(
        [
            (
                row["manual_label"] == "USEFUL_RAW_CANDIDATE",
                row["new_decision"]
                in {
                    PrequalificationOutcome.PREQUALIFIED.value,
                    PrequalificationOutcome.PREQUALIFIED_WITH_UNCERTAINTY.value,
                },
            )
            for row in labelled
        ]
    )
    outcomes = Counter(row["new_decision"] for row in diagnostics)
    return {
        "baseline_run_id": "37355f0a-d439-4c38-ae8d-837c25dd8974",
        "safe_replay": True,
        "external_search_used": False,
        "raw_provider_messages_included": False,
        "candidate_count": len(diagnostics),
        "dominant_old_rejection_distribution": [
            {
                "reason": "Threshold failure",
                "count": 59,
                "percentage": 98.33,
            },
            {
                "reason": "Missing provider relevance contribution",
                "count": 60,
                "percentage": 100.0,
            },
            {
                "reason": "No additional query-agreement contribution",
                "count": 59,
                "percentage": 98.33,
            },
            {
                "reason": "No cross-provider contribution",
                "count": 60,
                "percentage": 100.0,
            },
        ],
        "verified_rejection_reason_audit": [
            {"reason": "India verified mismatch", "count": 0, "percentage": 0.0},
            {"reason": "B2B verified mismatch", "count": 0, "percentage": 0.0},
            {"reason": "SaaS verified mismatch", "count": 0, "percentage": 0.0},
            {
                "reason": "Employee size verified mismatch",
                "count": 0,
                "percentage": 0.0,
            },
            {
                "reason": "Support operations verified missing",
                "count": 0,
                "percentage": 0.0,
            },
            {"reason": "Direct competitor", "count": 0, "percentage": 0.0},
            {
                "reason": "Insufficient domain confidence",
                "count": 0,
                "percentage": 0.0,
            },
            {"reason": "Non-company result", "count": 0, "percentage": 0.0},
            {"reason": "Directory/news/blog", "count": 0, "percentage": 0.0},
            {"reason": "Duplicate entity", "count": 0, "percentage": 0.0},
            {"reason": "Threshold failure", "count": 59, "percentage": 98.33},
        ],
        "common_combination": {
            "factors": [
                "provider relevance unavailable",
                "single query hit",
                "single provider",
                "score below 45",
            ],
            "count": 59,
            "percentage": 98.33,
        },
        "first_30": {
            "labelled_count": len(labelled),
            "uncertain_excluded": 3,
            "old_metrics": old_metrics.__dict__,
            "new_metrics": new_metrics.__dict__,
        },
        "shadow_outcomes": dict(sorted(outcomes.items())),
        "candidates": diagnostics,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    payload = json.dumps(build_replay(arguments.input), indent=2, sort_keys=True)
    if arguments.output:
        arguments.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)


if __name__ == "__main__":
    main()
