from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections import Counter
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from apps.api.app.db.models import (
    EvidenceFactRow,
    ResearchCandidateRow,
    SourceDocumentRow,
)
from apps.api.app.db.session import SessionFactory


def prequalification_outcome(
    stage: str,
    diagnostics: dict[str, object],
) -> str:
    explicit_outcome = diagnostics.get("prequalification_outcome")
    if explicit_outcome:
        return str(explicit_outcome)
    if stage in {
        "PREQUALIFIED",
        "PREQUALIFIED_WITH_UNCERTAINTY",
        "REVIEW_REQUIRED",
        "REJECTED",
    }:
        return stage
    if stage == "ACCEPTED":
        # Older runs replaced the original state after account creation.
        return "PREQUALIFIED"
    return "REJECTED"


async def export(result_path: Path, output_path: Path) -> None:
    result = json.loads(result_path.read_text(encoding="utf-8-sig"))
    run_id = UUID(str(result["research_run"]["id"]))
    async with SessionFactory() as session:
        candidates = list(
            (
                await session.scalars(
                    select(ResearchCandidateRow)
                    .where(ResearchCandidateRow.research_run_id == run_id)
                    .order_by(
                        ResearchCandidateRow.candidate_score.desc(),
                        ResearchCandidateRow.created_at,
                    )
                )
            ).all()
        )
        sources = list(
            (
                await session.scalars(
                    select(SourceDocumentRow)
                    .where(SourceDocumentRow.research_run_id == run_id)
                    .order_by(SourceDocumentRow.created_at)
                )
            ).all()
        )
        facts = list(
            (
                await session.scalars(
                    select(EvidenceFactRow)
                    .join(
                        SourceDocumentRow,
                        EvidenceFactRow.source_id == SourceDocumentRow.id,
                    )
                    .where(SourceDocumentRow.research_run_id == run_id)
                )
            ).all()
        )
    stages = Counter(item.stage for item in candidates)
    prequalification_outcomes: Counter[str] = Counter()
    for item in candidates:
        prequalification_outcomes[
            prequalification_outcome(item.stage, item.diagnostics)
        ] += 1
    accounts = list(result.get("accounts") or [])
    qualifications = Counter(
        str(item.get("qualification_status") or "UNKNOWN") for item in accounts
    )
    bundle = {
        "workspace_id": result.get("workspace_id"),
        "research_run": result.get("research_run"),
        "runtime": {
            "gateway_status": result.get("gateway_status"),
            "api_status": result.get("api_status"),
            "research_mode": result.get("mode"),
            "fixture_fallback": False,
            "demo_data": False,
            "provider": "exa",
            "transport": "mcp",
            "authenticated": bool(os.environ.get("EXA_API_KEY")),
            "tavily": (
                "CONFIGURED" if os.environ.get("TAVILY_API_KEY") else "NOT_CONFIGURED"
            ),
        },
        "funnel": {
            "raw_candidates": len(candidates),
            "prequalified": prequalification_outcomes["PREQUALIFIED"],
            "prequalified_with_uncertainty": prequalification_outcomes[
                "PREQUALIFIED_WITH_UNCERTAINTY"
            ],
            "review_required": prequalification_outcomes["REVIEW_REQUIRED"],
            "rejected_prequalification": prequalification_outcomes["REJECTED"],
            "shortlisted_for_deep_research": (
                prequalification_outcomes["PREQUALIFIED"]
                + prequalification_outcomes["PREQUALIFIED_WITH_UNCERTAINTY"]
            ),
            "deeply_researched": (
                stages["ACCEPTED"]
                + stages["REJECTED_DEEP_RESEARCH"]
                + stages["REJECTED_QUALIFICATION"]
            ),
            "rejected_deep_research": stages["REJECTED_DEEP_RESEARCH"],
            "rejected_qualification": stages["REJECTED_QUALIFICATION"],
            "accepted": stages["ACCEPTED"],
            "final_accounts": len(accounts),
            "qualified": qualifications["QUALIFIED"],
            "qualified_with_uncertainty": qualifications[
                "QUALIFIED_WITH_UNCERTAINTY"
            ],
            "borderline": qualifications["BORDERLINE"],
            "disqualified": qualifications["DISQUALIFIED"],
            "insufficient_evidence": qualifications["INSUFFICIENT_EVIDENCE"],
        },
        "candidate_first_30": [
            {
                "rank": index,
                "discovered_url": item.discovered_url,
                "hostname": item.hostname,
                "registrable_domain": item.registrable_domain,
                "canonical_company_domain": item.canonical_company_domain,
                "page_role": item.page_role,
                "candidate_score": item.candidate_score,
                "stage": item.stage,
                "query_provenance": item.query_provenance,
                "provider_provenance": item.provider_provenance,
                "diagnostics": item.diagnostics,
            }
            for index, item in enumerate(candidates[:30], 1)
        ],
        "accounts": accounts,
        "top_briefs": result.get("top_briefs") or [],
        "sources": [
            {
                "id": str(item.id),
                "url": item.url,
                "canonical_url": item.canonical_url,
                "title": item.title,
                "backend": item.backend,
                "published_at": (
                    item.published_at.isoformat() if item.published_at else None
                ),
                "trust_score": item.trust_score,
                "status": item.status,
            }
            for item in sources
        ],
        "facts": [
            {
                "id": str(item.id),
                "source_id": str(item.source_id),
                "claim": item.claim,
                "confidence": item.confidence,
                "status": item.status,
            }
            for item in facts
        ],
    }
    output_path.write_text(
        json.dumps(bundle, indent=2, default=str),
        encoding="utf-8",
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("result", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    await export(args.result, args.output)


if __name__ == "__main__":
    asyncio.run(main())
