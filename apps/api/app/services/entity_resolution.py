"""GoPilot's use of the entity-safety gate, plus the GTM state machine.

The gate itself -- identities, the ten relationship types, claim scopes, and the
attachment decision -- was extracted to `packages/entity-safety`, because none
of it is about sales. It takes a claimed entity, a passage, and known
relationships, and answers whether the passage may support a claim about that
entity. Anyone building a retrieval or agent pipeline has that problem.

What stays here is what is genuinely GoPilot's: `BriefState` and
`decide_brief_state` speak in accounts, ICPs, qualification and competitors, and
mean nothing outside a GTM product. They never called into the attachment logic,
which is why the split was a clean cut rather than an untangling.

The gate's names are re-exported so existing call sites keep working and the
extraction stays provably behaviour-preserving; new code can import from
`entity_safety` directly.
"""

from __future__ import annotations

from enum import StrEnum

from entity_safety import (
    AttachmentDecision,
    ClaimScope,
    CompanyIdentityRecord,
    EntityRelation,
    EvidenceAttachmentAssessment,
    VerifiedAlias,
    VerifiedEntityRelationship,
    assess_evidence_attachment,
    claim_scope_is_compatible,
    domains_in_text,
    infer_claim_scope,
    normalized_entity_name,
)


__all__ = [
    "AttachmentDecision",
    "BriefState",
    "ClaimScope",
    "CompanyIdentityRecord",
    "EntityRelation",
    "EvidenceAttachmentAssessment",
    "IMPORT_PENDING_IDENTITY_WARNING",
    "VerifiedAlias",
    "VerifiedEntityRelationship",
    "assess_evidence_attachment",
    "claim_scope_is_compatible",
    "decide_brief_state",
    "domains_in_text",
    "infer_claim_scope",
    "normalized_entity_name",
]


# Written at import time and cleared once research verifies the supplied domain.
# Import and research must agree on the exact string, so it lives in one place.
IMPORT_PENDING_IDENTITY_WARNING = "User-supplied domain has not yet been verified."


class BriefState(StrEnum):
    """Where an account sits in the GTM review pipeline.

    Product-specific by design: FOUNDER_READY is a statement about outreach
    readiness, which is why it belongs here and not in the entity-safety
    package.
    """

    FOUNDER_READY = "FOUNDER_READY"
    RESEARCH_CANDIDATE = "RESEARCH_CANDIDATE"
    MONITOR = "MONITOR"
    DO_NOT_TARGET = "DO_NOT_TARGET"
    IDENTITY_REVIEW_REQUIRED = "IDENTITY_REVIEW_REQUIRED"


def decide_brief_state(
    *,
    identity_verified: bool,
    unresolved_identity_warnings: tuple[str, ...],
    qualification_status: str,
    has_supported_icp_fact: bool,
    has_actionable_signal: bool,
    supported_important_claims: bool,
    direct_competitor_conflict: bool,
) -> BriefState:
    """Unresolved identity outranks everything: it is a refusal to guess."""
    if unresolved_identity_warnings:
        return BriefState.IDENTITY_REVIEW_REQUIRED
    if qualification_status == "DISQUALIFIED" or direct_competitor_conflict:
        return BriefState.DO_NOT_TARGET
    if (
        identity_verified
        and qualification_status == "QUALIFIED"
        and has_supported_icp_fact
        and has_actionable_signal
        and supported_important_claims
    ):
        return BriefState.FOUNDER_READY
    if has_supported_icp_fact and not has_actionable_signal:
        return BriefState.MONITOR
    return BriefState.RESEARCH_CANDIDATE
