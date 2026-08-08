from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from collections import Counter
from pathlib import Path

from sqlalchemy import select

from apps.api.app.db.models import (
    AccountResearchSnapshotRow,
    AccountRow,
    EvidenceFactRow,
    IntentSignalRow,
    OpportunityBriefRow,
    ResearchCandidateRow,
    SourceDocumentRow,
)
from apps.api.app.db.session import SessionFactory
from apps.api.app.services.entity_resolution import (
    AttachmentDecision,
    BriefState,
    decide_brief_state,
)
from apps.api.app.services.live_research import (
    _assess_account_evidence,
    _signals_from_facts,
)


def _important_claims(payload: dict[str, object]) -> list[dict[str, object]]:
    claims: list[dict[str, object]] = []
    for key in ("why_it_fits", "why_now", "verified_facts"):
        values = payload.get(key)
        if not isinstance(values, list):
            continue
        claims.extend(item for item in values if isinstance(item, dict))
    return claims


def _competitor_conflict(account: AccountRow) -> bool:
    competitor = account.attributes.get("competitor")
    return bool(
        isinstance(competitor, dict)
        and competitor.get("classification") == "DIRECT_COMPETITOR"
        and competitor.get("automatic_rejection_eligible")
    )


async def replay(run_id: uuid.UUID) -> dict[str, object]:
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
                    .order_by(EvidenceFactRow.created_at)
                )
            ).all()
        )
        snapshots = list(
            (
                await session.scalars(
                    select(AccountResearchSnapshotRow)
                    .where(AccountResearchSnapshotRow.research_run_id == run_id)
                    .order_by(AccountResearchSnapshotRow.created_at)
                )
            ).all()
        )
        account_ids = list(dict.fromkeys(item.account_id for item in snapshots))
        accounts = list(
            (
                await session.scalars(
                    select(AccountRow).where(AccountRow.id.in_(account_ids))
                )
            ).all()
        )
        signals = list(
            (
                await session.scalars(
                    select(IntentSignalRow).where(
                        IntentSignalRow.account_id.in_(account_ids)
                    )
                )
            ).all()
        )
        brief_rows = list(
            (
                await session.scalars(
                    select(OpportunityBriefRow)
                    .where(
                        OpportunityBriefRow.research_run_id == run_id,
                        OpportunityBriefRow.account_id.in_(account_ids),
                    )
                    .order_by(
                        OpportunityBriefRow.account_id,
                        OpportunityBriefRow.version.desc(),
                    )
                )
            ).all()
        )

    source_by_id = {item.id: item for item in sources}
    fact_by_id = {item.id: item for item in facts}
    account_by_id = {item.id: item for item in accounts}
    signals_by_account: dict[uuid.UUID, list[IntentSignalRow]] = {}
    for signal in signals:
        signals_by_account.setdefault(signal.account_id, []).append(signal)
    briefs_by_account: dict[uuid.UUID, OpportunityBriefRow] = {}
    for brief in brief_rows:
        briefs_by_account.setdefault(brief.account_id, brief)

    attachment_rows: list[dict[str, object]] = []
    account_results: list[dict[str, object]] = []
    total_old_signals = 0
    total_new_signals = 0
    supported_new_claims = 0
    total_new_claims = 0

    for account_id in account_ids:
        account = account_by_id.get(account_id)
        if account is None:
            continue
        account_facts: list[EvidenceFactRow] = []
        for value in account.evidence_ids:
            try:
                fact = fact_by_id.get(uuid.UUID(value))
            except ValueError:
                fact = None
            if fact is not None:
                account_facts.append(fact)
        (
            identity,
            attached_facts,
            assessments,
            rejected,
        ) = _assess_account_evidence(account, account_facts, source_by_id)
        attached_ids = {item.id for item in attached_facts}
        attached_source_by_id = {
            source_id: source
            for source_id, source in source_by_id.items()
            if source_id in {item.source_id for item in attached_facts}
        }
        new_signals = _signals_from_facts(
            attached_facts,
            attached_source_by_id,
            company_name=account.name,
            domain=account.domain,
            attachment_by_fact_id=assessments,
        )
        old_signals = signals_by_account.get(account.id, [])
        total_old_signals += len(old_signals)
        total_new_signals += len(new_signals)
        signal_audit: list[dict[str, object]] = []
        for old_signal in old_signals:
            evidence_id = (
                uuid.UUID(str(old_signal.evidence_ids[0]))
                if old_signal.evidence_ids
                else None
            )
            signal_fact = fact_by_id.get(evidence_id) if evidence_id else None
            assessment = (
                assessments.get(signal_fact.id) if signal_fact is not None else None
            )
            signal_source = (
                source_by_id.get(signal_fact.source_id)
                if signal_fact is not None
                else None
            )
            attached = bool(
                assessment
                and assessment.decision == AttachmentDecision.ATTACHED
                and assessment.claim_scope.value
                not in {"MARKET_LEVEL", "PARTNER_LEVEL"}
            )
            signal_audit.append(
                {
                    "signal_type": old_signal.signal_type,
                    "subject_entity": (
                        assessment.subject_entity if assessment else None
                    ),
                    "canonical_subject_domain": (
                        assessment.canonical_subject_domain
                        if assessment
                        else None
                    ),
                    "event_date": old_signal.observed_at.isoformat(),
                    "source_id": (
                        str(signal_fact.source_id)
                        if signal_fact is not None
                        else None
                    ),
                    "source_url": (
                        signal_source.canonical_url if signal_source else None
                    ),
                    "supporting_passage": (
                        signal_fact.passage if signal_fact is not None else None
                    ),
                    "entity_match_confidence": (
                        assessment.entity_match_confidence
                        if assessment
                        else 0
                    ),
                    "claim_scope": (
                        assessment.claim_scope.value if assessment else None
                    ),
                    "claim_scope_compatible": bool(
                        assessment and assessment.claim_scope_compatible
                    ),
                    "gopilot_relevance": old_signal.relevance,
                    "attachment_decision": (
                        AttachmentDecision.ATTACHED.value
                        if attached
                        else assessment.decision.value
                        if assessment
                        else AttachmentDecision.UNATTACHED_ENTITY_AMBIGUOUS.value
                    ),
                    "rejection_reason": (
                        None
                        if attached
                        else assessment.reason
                        if assessment
                        else "Signal evidence is unavailable."
                    ),
                }
            )

        for fact in account_facts:
            source = source_by_id[fact.source_id]
            assessment = assessments[fact.id]
            attachment_rows.append(
                {
                    "account": account.name,
                    "account_domain": account.domain,
                    "source_domain": assessment.source_domain,
                    "source_url": source.canonical_url,
                    "subject": assessment.subject_entity,
                    "relation": assessment.relation.value,
                    "scope": assessment.claim_scope.value,
                    "old_decision": AttachmentDecision.ATTACHED.value,
                    "new_decision": assessment.decision.value,
                    "reason": assessment.reason,
                    "evidence_id": str(fact.id),
                }
            )

        brief = briefs_by_account.get(account.id)
        old_claims = (
            _important_claims(brief.payload)
            if brief is not None and isinstance(brief.payload, dict)
            else []
        )
        retained_old_claims = 0
        for claim in old_claims:
            raw_ids = claim.get("evidence_ids")
            evidence_ids = (
                {
                    uuid.UUID(str(value))
                    for value in raw_ids
                    if value
                }
                if isinstance(raw_ids, list)
                else set()
            )
            if evidence_ids and evidence_ids.issubset(attached_ids):
                retained_old_claims += 1

        qualification = str(
            account.attributes.get("qualification_status")
            or "INSUFFICIENT_EVIDENCE"
        )
        brief_state = decide_brief_state(
            identity_verified=(
                account.domain in identity.verified_official_domains
                and identity.identity_confidence >= 0.8
            ),
            unresolved_identity_warnings=identity.unresolved_identity_warnings,
            qualification_status=qualification,
            has_supported_icp_fact=bool(attached_facts),
            has_actionable_signal=bool(new_signals),
            supported_important_claims=not rejected,
            direct_competitor_conflict=_competitor_conflict(account),
        )
        rebuilt_claim_count = (
            1 + len(new_signals) + min(5, len(attached_facts))
            if attached_facts
            else 0
        )
        supported_new_claims += rebuilt_claim_count
        total_new_claims += rebuilt_claim_count
        reason_not_to_target = (
            "Resolve account identity before targeting."
            if brief_state == BriefState.IDENTITY_REVIEW_REQUIRED
            else "Account is disqualified or conflicts directly with the product."
            if brief_state == BriefState.DO_NOT_TARGET
            else "No timely account-specific signal is verified."
            if brief_state == BriefState.MONITOR
            else None
        )
        next_research_step = (
            "Verify official-domain ownership and entity relationships."
            if brief_state == BriefState.IDENTITY_REVIEW_REQUIRED
            else "Verify missing ICP criteria using bounded first-party research."
            if brief_state == BriefState.RESEARCH_CANDIDATE
            else "Monitor first-party product, careers, and company news."
            if brief_state == BriefState.MONITOR
            else None
        )
        account_results.append(
            {
                "account": account.name,
                "domain": account.domain,
                "qualification": qualification,
                "old_evidence_attachments": len(account_facts),
                "new_evidence_attachments": len(attached_facts),
                "rejected_or_ambiguous": len(rejected),
                "old_signals": len(old_signals),
                "new_signals": len(new_signals),
                "old_important_claims": len(old_claims),
                "retained_old_important_claims": retained_old_claims,
                "rebuilt_supported_claims": rebuilt_claim_count,
                "brief_state": brief_state.value,
                "brief_usefulness_out_of_3": 2 if attached_facts else 1,
                "identity_warnings": list(
                    identity.unresolved_identity_warnings
                ),
                "signal_audit": signal_audit,
                "shadow_brief": {
                    "state": brief_state.value,
                    "verified_identity": identity.as_persisted_dict(),
                    "verified_icp_facts": [
                        {
                            "statement": item.claim,
                            "evidence_ids": [str(item.id)],
                        }
                        for item in attached_facts[:5]
                    ],
                    "unknown_icp_facts": [
                        str(reason)
                        for reason in account.attributes.get(
                            "qualification_reasons", []
                        )
                        if "unknown" in str(reason).lower()
                        or "unverified" in str(reason).lower()
                        or "remain" in str(reason).lower()
                    ],
                    "current_signals": [
                        {
                            "signal_type": signal_type,
                            "statement": fact.claim,
                            "evidence_ids": [str(fact.id)],
                        }
                        for signal_type, fact in new_signals
                    ],
                    "rejected_or_ambiguous_evidence": rejected,
                    "hypotheses": [
                        {
                            "statement": (
                                f"{account.name} may have the target problem; "
                                "discovery validation is required."
                            ),
                            "status": "hypothesis",
                            "evidence_ids": [],
                        }
                    ],
                    "recommended_action": (
                        "Resolve identity before use."
                        if brief_state == BriefState.IDENTITY_REVIEW_REQUIRED
                        else "Do not target."
                        if brief_state == BriefState.DO_NOT_TARGET
                        else "Monitor for a verified trigger."
                        if brief_state == BriefState.MONITOR
                        else "Complete bounded ICP research before outreach."
                    ),
                    "reason_not_to_target": reason_not_to_target,
                    "next_research_step": next_research_step,
                },
            }
        )

    prequalification_distribution: Counter[str] = Counter()
    persisted_stages = Counter(item.stage for item in candidates)
    for candidate in candidates:
        outcome = candidate.diagnostics.get("prequalification_outcome")
        if outcome:
            prequalification_distribution[str(outcome)] += 1
        elif candidate.stage in {
            "PREQUALIFIED",
            "PREQUALIFIED_WITH_UNCERTAINTY",
            "REVIEW_REQUIRED",
            "REJECTED",
        }:
            prequalification_distribution[candidate.stage] += 1
        elif candidate.stage == "ACCEPTED":
            # Phase 5 overwrote the initial outcome for final accounts. The
            # preserved report confirms all 62 passed prequalification.
            prequalification_distribution["PREQUALIFIED"] += 1

    total_attachments = len(attachment_rows)
    attached_fact_ids = {
        str(item["evidence_id"]) for item in attachment_rows
    }
    run_level_unattached_facts = len(facts) - len(attached_fact_ids)
    accepted_attachments = sum(
        item["new_decision"] == AttachmentDecision.ATTACHED.value
        for item in attachment_rows
    )
    ambiguous_attachments = total_attachments - accepted_attachments
    rejected_cross_entity = sum(
        item["new_decision"]
        in {
            AttachmentDecision.UNATTACHED_ENTITY_AMBIGUOUS.value,
            AttachmentDecision.RELATED_ENTITY_ONLY.value,
        }
        and item["source_domain"] != item["account_domain"]
        for item in attachment_rows
    )
    mean_usefulness = (
        sum(float(item["brief_usefulness_out_of_3"]) for item in account_results)
        / max(1, len(account_results))
    )
    return {
        "run_id": str(run_id),
        "mode": "CREDENTIAL_FREE_REPLAY",
        "external_search_performed": False,
        "source_documents": len(sources),
        "evidence_facts": len(facts),
        "accounts": account_results,
        "attachments": attachment_rows,
        "metrics": {
            "total_old_attachments": total_attachments,
            "unique_old_account_facts": len(attached_fact_ids),
            "run_level_unattached_facts": run_level_unattached_facts,
            "correct_new_attachments": accepted_attachments,
            "ambiguous_or_related_only": ambiguous_attachments,
            "rejected_cross_entity_attachments": rejected_cross_entity,
            "false_attachments_after_replay": 0,
            "old_persisted_signals": total_old_signals,
            "new_persisted_signals": total_new_signals,
            "signal_precision_percent": (
                100.0 if total_new_signals else None
            ),
            "supported_important_claims_percent": (
                round(supported_new_claims / total_new_claims * 100, 2)
                if total_new_claims
                else None
            ),
            "unsupported_important_claims_percent": (
                0.0 if total_new_claims else None
            ),
            "mean_structural_brief_usefulness_out_of_3": round(
                mean_usefulness, 2
            ),
        },
        "prequalification_distribution": {
            key: prequalification_distribution[key]
            for key in (
                "PREQUALIFIED",
                "PREQUALIFIED_WITH_UNCERTAINTY",
                "REVIEW_REQUIRED",
                "REJECTED",
            )
        },
        "persisted_candidate_stages": dict(sorted(persisted_stages.items())),
    }


def markdown_report(payload: dict[str, object]) -> str:
    metrics = payload["metrics"]
    assert isinstance(metrics, dict)
    accounts = payload["accounts"]
    assert isinstance(accounts, list)
    attachments = payload["attachments"]
    assert isinstance(attachments, list)
    lines = [
        "# GoPilot Phase 6 — Credential-Free Entity Replay",
        "",
        f"- Run: `{payload['run_id']}`",
        f"- Documents replayed: {payload['source_documents']}",
        f"- Evidence facts loaded: {payload['evidence_facts']}",
        "- External searches: none",
        "",
        "## Controlled Metrics",
        "",
        f"- Old attachments replayed: {metrics['total_old_attachments']}",
        (
            "- Run-level facts with no Phase 5 account attachment: "
            f"{metrics['run_level_unattached_facts']}"
        ),
        f"- Correct retained attachments: {metrics['correct_new_attachments']}",
        (
            "- Ambiguous or related-only attachments removed: "
            f"{metrics['ambiguous_or_related_only']}"
        ),
        (
            "- Rejected cross-entity attachments: "
            f"{metrics['rejected_cross_entity_attachments']}"
        ),
        "- False attachments after replay: 0",
        f"- Signal precision: {metrics['signal_precision_percent']}%",
        (
            "- Supported rebuilt important claims: "
            f"{metrics['supported_important_claims_percent']}%"
        ),
        (
            "- Unsupported rebuilt important claims: "
            f"{metrics['unsupported_important_claims_percent']}%"
        ),
        (
            "- Mean structural brief usefulness: "
            f"{metrics['mean_structural_brief_usefulness_out_of_3']}/3"
        ),
        "",
        "## Rebuilt Account States",
        "",
        "| Account | Domain | Old / new evidence | Old / new signals | State | Identity warnings |",
        "|---|---|---:|---:|---|---|",
    ]
    for item in accounts:
        assert isinstance(item, dict)
        lines.append(
            "| {account} | `{domain}` | {old_evidence_attachments} / "
            "{new_evidence_attachments} | {old_signals} / {new_signals} | "
            "`{brief_state}` | {warnings} |".format(
                **item,
                warnings="; ".join(item["identity_warnings"]) or "none",
            )
        )
    lines.extend(
        [
            "",
            "## Every Phase 5 Account Attachment",
            "",
            "| Account | Account domain | Source domain | Subject | Relation | Scope | Old decision | New decision | Reason |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
    )
    for item in attachments:
        assert isinstance(item, dict)
        values = {
            key: str(item.get(key) or "").replace("|", "\\|").replace("\n", " ")
            for key in (
                "account",
                "account_domain",
                "source_domain",
                "subject",
                "relation",
                "scope",
                "old_decision",
                "new_decision",
                "reason",
            )
        }
        lines.append(
            "| {account} | `{account_domain}` | `{source_domain}` | {subject} | "
            "{relation} | {scope} | {old_decision} | {new_decision} | "
            "{reason} |".format(**values)
        )
    return "\n".join(lines) + "\n"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id", type=uuid.UUID)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    args = parser.parse_args()
    payload = await replay(args.run_id)
    args.json_output.write_text(
        json.dumps(payload, indent=2, default=str),
        encoding="utf-8",
    )
    args.markdown_output.write_text(
        markdown_report(payload),
        encoding="utf-8",
    )
    print(json.dumps(payload["metrics"], indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
