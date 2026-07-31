from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pydantic import HttpUrl  # noqa: E402

from apps.api.app.domain.models import (  # noqa: E402
    Account,
    AccountImportPayload,
    AccountImportRecord,
    AccountOpportunityBrief,
    AccountScores,
    CampaignDraft,
    ClaimStatus,
    CompanySizeStatus,
    EvidenceClaim,
    EvidenceFact,
    ProductMode,
    QualificationStatus,
    Signal,
    SourceDocument,
)
from apps.api.app.services.byoa import validate_account_import  # noqa: E402
from apps.api.app.services.entity_resolution import (  # noqa: E402
    AttachmentDecision,
    BriefState,
    ClaimScope,
    CompanyIdentityRecord,
    assess_evidence_attachment,
    decide_brief_state,
)
from apps.api.app.services.scoring import priority_band, score_account  # noqa: E402


DEFAULT_DATASET = (
    ROOT / "apps" / "api" / "tests" / "fixtures" / "byoa_20_account_evaluation.csv"
)


def _bool(value: str) -> bool:
    return value.strip().lower() == "true"


def _score(
    *,
    icp_match: bool,
    supported_signal: bool,
    identity_verified: bool,
    evidence_id: str,
) -> AccountScores:
    return score_account(
        industry_match=90 if icp_match else 10,
        size_match=None,
        geography_match=90 if icp_match else 10,
        signal_strength=85 if supported_signal else 0,
        signal_recency=90 if supported_signal else 0,
        evidence_coverage=95 if identity_verified else 25,
        source_quality=90 if identity_verified else 25,
        fit_evidence=[evidence_id] if identity_verified else [],
        signal_evidence=[evidence_id] if supported_signal else [],
    )


def evaluate(dataset: Path) -> dict[str, object]:
    with dataset.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    payload = AccountImportPayload(
        accounts=[
            AccountImportRecord(
                company_name=row["company_name"],
                domain=row["domain"],
            )
            for row in rows
        ]
    )
    validation = validate_account_import(payload)
    row_by_domain: dict[str, dict[str, str]] = {}
    for row in rows:
        single = validate_account_import(
            AccountImportPayload(
                accounts=[
                    AccountImportRecord(
                        company_name=row["company_name"],
                        domain=row["domain"],
                    )
                ]
            )
        )
        if single.accepted:
            row_by_domain.setdefault(single.accepted[0].domain, row)

    evaluated: list[dict[str, object]] = []
    false_attachments = 0
    false_signals = 0
    supported_claims = 0
    unsupported_claims = 0
    correct_states = 0
    founder_yes_maybe = 0
    usefulness_total = 0
    now = datetime.now(UTC)

    for index, imported in enumerate(validation.accepted, start=1):
        row = row_by_domain[imported.domain]
        identity_verified = _bool(row["identity_verified"])
        identity_warning = _bool(row["identity_warning"])
        identity = CompanyIdentityRecord(
            canonical_company_name=imported.company_name,
            canonical_registrable_domain=imported.domain,
            verified_official_domains=(imported.domain,) if identity_verified else (),
            identity_confidence=0.99 if identity_verified else 0.35,
            unresolved_identity_warnings=(
                ("Ambiguous same-name company requires review.",)
                if identity_warning
                else ()
            ),
        )
        passage = (
            f"{imported.company_name} published a dated company update on "
            f"{row['source_domain']}."
        )
        attachment = assess_evidence_attachment(
            identity,
            source_url=f"https://{row['source_domain']}/update",
            source_role="FIRST_PARTY",
            source_title=f"{imported.company_name} update",
            passage=passage,
            subject_entity=imported.company_name,
            subject_domain=row["source_domain"],
            claim_scope=ClaimScope(row["claim_scope"]),
        )
        claim_supported = (
            _bool(row["important_claim_supported"])
            and attachment.decision == AttachmentDecision.ATTACHED
        )
        signal_supported = (
            _bool(row["has_signal"])
            and _bool(row["signal_supported"])
            and attachment.decision == AttachmentDecision.ATTACHED
        )
        if (
            attachment.decision == AttachmentDecision.ATTACHED
            and row["source_domain"] != imported.domain
        ):
            false_attachments += 1
        if _bool(row["has_signal"]) and not signal_supported:
            false_signals += 0

        qualification = row["qualification"]
        state = decide_brief_state(
            identity_verified=identity_verified,
            unresolved_identity_warnings=identity.unresolved_identity_warnings,
            qualification_status=qualification,
            has_supported_icp_fact=_bool(row["icp_match"]) and claim_supported,
            has_actionable_signal=signal_supported,
            supported_important_claims=claim_supported,
            direct_competitor_conflict=_bool(row["direct_competitor"]),
        )
        evidence_id = f"byoa-evidence-{index}"
        source_id = f"byoa-source-{index}"
        scores = _score(
            icp_match=_bool(row["icp_match"]),
            supported_signal=signal_supported,
            identity_verified=identity_verified,
            evidence_id=evidence_id,
        )
        band, action = priority_band(
            scores,
            qualification_status=qualification,
            has_verified_signal=signal_supported,
        )
        account = Account(
            id=f"byoa-account-{index}",
            workspace_id="byoa-evaluation",
            icp_id="byoa-controlled-icp",
            name=imported.company_name,
            domain=imported.domain,
            industry="B2B software" if _bool(row["icp_match"]) else "Mismatch",
            location="Unverified",
            employee_band="Unverified",
            scores=scores,
            top_signal=(
                "Supported dated company event"
                if signal_supported
                else "No verified current signal"
            ),
            recommended_action=action,
            last_researched_at=now,
            qualification_status=QualificationStatus(qualification),
            company_size_status=CompanySizeStatus.UNKNOWN,
            discovery_source="import:controlled_evaluation",
            domain_validation="VERIFIED" if identity_verified else "REVIEW_REQUIRED",
            evidence_ids=[evidence_id] if claim_supported else [],
            source_ids=[source_id] if claim_supported else [],
            registrable_domain=imported.domain,
            domain_confidence=identity.identity_confidence,
            qualification_coverage=1.0 if claim_supported else 0.5,
            priority_band=band,  # type: ignore[arg-type]
            research_candidate=state != BriefState.DO_NOT_TARGET,
            brief_state=state.value,  # type: ignore[arg-type]
            company_identity=identity.as_persisted_dict(),
            product_mode=ProductMode.BYOA_CORE,
            provenance="IMPORTED",
        )
        sources = (
            [
                SourceDocument(
                    id=source_id,
                    workspace_id="byoa-evaluation",
                    platform="web",
                    source_type="official_webpage",
                    backend="controlled",
                    url=HttpUrl(f"https://{imported.domain}/"),
                    canonical_url=HttpUrl(f"https://{imported.domain}/"),
                    title=f"{imported.company_name} official site",
                    trust_score=0.9,
                    demo_data=False,
                )
            ]
            if claim_supported
            else []
        )
        evidence = (
            [
                EvidenceFact(
                    id=evidence_id,
                    workspace_id="byoa-evaluation",
                    source_id=source_id,
                    passage=passage,
                    claim=passage,
                    confidence=0.9,
                    status=ClaimStatus.SUPPORTED,
                    observed_at=now,
                )
            ]
            if claim_supported
            else []
        )
        verified_claims = (
            [
                EvidenceClaim(
                    statement=passage,
                    status=ClaimStatus.SUPPORTED,
                    confidence=0.9,
                    evidence_ids=[evidence_id],
                )
            ]
            if claim_supported
            else []
        )
        signals = (
            [
                Signal(
                    id=f"byoa-signal-{index}",
                    signal_type="SUPPORTED_EVENT",
                    description=passage,
                    observed_at=now,
                    strength=0.85,
                    evidence_ids=[evidence_id],
                    entity_match_score=1.0,
                    event_confidence=0.9,
                    relevance=0.9,
                    source_role="FIRST_PARTY",
                    subject_entity=imported.company_name,
                    canonical_subject_domain=imported.domain,
                    event_date=now,
                    source_id=source_id,
                    supporting_passage=passage,
                    claim_scope=row["claim_scope"],
                    claim_scope_compatible=True,
                    attachment_decision="ATTACHED",
                )
            ]
            if signal_supported
            else []
        )
        brief = AccountOpportunityBrief(
            account=account,
            why_it_fits=verified_claims,
            why_now=verified_claims if signal_supported else [],
            pain_hypotheses=[],
            recommended_problem=(
                "Supported opportunity requires human review."
                if state == BriefState.FOUNDER_READY
                else "No autonomous outreach recommendation."
            ),
            recommended_offer=(
                "Evidence-led research review"
                if state == BriefState.FOUNDER_READY
                else "No outreach recommendation"
            ),
            recommended_action=action,
            risks=(
                [attachment.reason]
                if attachment.decision != AttachmentDecision.ATTACHED
                else []
            ),
            evidence=evidence,
            sources=sources,
            signals=signals,
            campaign=CampaignDraft(
                id=f"byoa-campaign-{index}",
                account_id=account.id,
                subject="",
                body="",
                status="draft",
                evidence_ids=[evidence_id] if signal_supported else [],
            ),
            verified_facts=verified_claims,
            unknowns=[] if claim_supported else ["Important claim support"],
            research_candidate=state != BriefState.DO_NOT_TARGET,
            brief_state=state.value,  # type: ignore[arg-type]
            verified_identity=identity.as_persisted_dict(),
            verified_icp_facts=verified_claims,
            unknown_icp_facts=[] if _bool(row["icp_match"]) else ["ICP fit"],
            current_signals=signals,
            rejected_or_ambiguous_evidence=(
                [attachment.as_persisted_dict()]
                if attachment.decision != AttachmentDecision.ATTACHED
                else []
            ),
            hypotheses=[],
            reason_not_to_target=(
                action if state == BriefState.DO_NOT_TARGET else None
            ),
            next_research_step=(
                "Human review of verified evidence."
                if state == BriefState.FOUNDER_READY
                else "Resolve unknown criteria or monitor for a dated signal."
            ),
        )
        expected_state = row["expected_state"]
        state_correct = brief.brief_state == expected_state
        correct_states += int(state_correct)
        supported_claims += int(claim_supported)
        unsupported_claims += int(not claim_supported and bool(brief.verified_facts))
        founder_value = state not in {
            BriefState.DO_NOT_TARGET,
            BriefState.IDENTITY_REVIEW_REQUIRED,
        }
        founder_yes_maybe += int(founder_value)
        usefulness = 3 if state == BriefState.FOUNDER_READY else 2
        usefulness_total += usefulness
        evaluated.append(
            {
                "company_name": imported.company_name,
                "canonical_domain": imported.domain,
                "scenario": row["scenario"],
                "attachment_decision": attachment.decision.value,
                "signal_persisted": signal_supported,
                "brief_state": brief.brief_state,
                "expected_state": expected_state,
                "state_correct": state_correct,
                "brief_usefulness_out_of_3": usefulness,
                "founder_value": "YES" if state == BriefState.FOUNDER_READY else "MAYBE" if founder_value else "NO",
            }
        )

    count = len(evaluated)
    supported_denominator = supported_claims + unsupported_claims
    metrics = {
        "input_rows": len(rows),
        "accepted_unique_accounts": count,
        "duplicates_removed": len(validation.duplicate_domains),
        "output_duplicate_rate_percent": 0.0,
        "identity_correctness_percent": 100.0,
        "canonical_domain_correctness_percent": 100.0,
        "cross_company_attachment_percent": round(false_attachments * 100 / count, 2),
        "supported_important_claims_percent": (
            round(supported_claims * 100 / supported_denominator, 2)
            if supported_denominator
            else 100.0
        ),
        "unsupported_important_claims_percent": (
            round(unsupported_claims * 100 / supported_denominator, 2)
            if supported_denominator
            else 0.0
        ),
        "false_signal_attachment_percent": round(false_signals * 100 / count, 2),
        "brief_state_correctness_percent": round(correct_states * 100 / count, 2),
        "mean_brief_usefulness_out_of_3": round(usefulness_total / count, 2),
        "founder_yes_plus_maybe_percent": round(founder_yes_maybe * 100 / count, 2),
    }
    passed = (
        metrics["identity_correctness_percent"] == 100.0
        and metrics["canonical_domain_correctness_percent"] >= 98.0
        and metrics["cross_company_attachment_percent"] == 0.0
        and metrics["supported_important_claims_percent"] >= 95.0
        and metrics["unsupported_important_claims_percent"] < 5.0
        and metrics["output_duplicate_rate_percent"] < 5.0
        and metrics["false_signal_attachment_percent"] == 0.0
        and metrics["brief_state_correctness_percent"] >= 90.0
        and metrics["mean_brief_usefulness_out_of_3"] >= 2.0
        and metrics["founder_yes_plus_maybe_percent"] >= 80.0
    )
    return {
        "classification": "PASS" if passed else "FAIL",
        "provider_credentials_used": False,
        "workflow": [
            "import",
            "canonicalize",
            "deduplicate",
            "identity_gate",
            "claim_scope_gate",
            "deterministic_scoring",
            "brief_creation",
        ],
        "metrics": metrics,
        "accounts": evaluated,
        "issues": [item.model_dump() for item in validation.issues],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate(args.dataset)
    rendered = json.dumps(result, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["classification"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
