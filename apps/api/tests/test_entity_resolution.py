from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from apps.api.app.services.entity_resolution import (
    AttachmentDecision,
    BriefState,
    ClaimScope,
    CompanyIdentityRecord,
    EntityRelation,
    VerifiedAlias,
    VerifiedEntityRelationship,
    assess_evidence_attachment,
    decide_brief_state,
)
from apps.api.app.services.live_research import _signals_from_facts
from scripts.phase5_holdout_export import prequalification_outcome


def _identity(
    *,
    name: str = "Acme",
    domain: str = "acme.com",
    official_domains: tuple[str, ...] | None = None,
    aliases: tuple[VerifiedAlias, ...] = (),
    relationships: tuple[VerifiedEntityRelationship, ...] = (),
) -> CompanyIdentityRecord:
    return CompanyIdentityRecord(
        canonical_company_name=name,
        canonical_registrable_domain=domain,
        verified_official_domains=official_domains or (domain,),
        known_aliases=aliases,
        relationships=relationships,
        identity_confidence=0.99,
    )


def _assess(
    identity: CompanyIdentityRecord,
    *,
    url: str,
    role: str = "FIRST_PARTY",
    title: str = "Acme",
    passage: str = "Acme announced a company update.",
    scope: ClaimScope | None = None,
):
    return assess_evidence_attachment(
        identity,
        source_url=url,
        source_role=role,
        source_title=title,
        passage=passage,
        claim_scope=scope,
    )


def _relationship(
    subject: str,
    object_: str,
    relation: EntityRelation,
    *,
    verified: bool = True,
) -> VerifiedEntityRelationship:
    return VerifiedEntityRelationship(
        subject_domain=subject,
        object_domain=object_,
        relation=relation,
        evidence_ids=("evidence-1",) if verified else (),
    )


def test_same_brand_prefix_different_domain_is_not_same_entity() -> None:
    decision = _assess(
        _identity(name="Northstar", domain="northstar.cloud"),
        url="https://northstar.ai/news",
        title="Northstar AI",
    )

    assert decision.decision == AttachmentDecision.UNATTACHED_ENTITY_AMBIGUOUS
    assert decision.relation == EntityRelation.UNKNOWN


def test_verified_secondary_domain_is_same_entity() -> None:
    decision = _assess(
        _identity(official_domains=("acme.com", "acme.co")),
        url="https://news.acme.co/launch",
        passage="Acme launched a product.",
    )

    assert decision.decision == AttachmentDecision.ATTACHED
    assert decision.relation == EntityRelation.SAME_ENTITY


def test_verified_product_domain_accepts_only_product_scope() -> None:
    identity = _identity(
        relationships=(
            _relationship("widget.dev", "acme.com", EntityRelation.PRODUCT_OF),
        )
    )

    accepted = _assess(
        identity,
        url="https://widget.dev/releases",
        passage="Widget launched a product release.",
        scope=ClaimScope.PRODUCT_LEVEL,
    )
    rejected = _assess(
        identity,
        url="https://widget.dev/company",
        passage="Widget hired a new sales leader.",
        scope=ClaimScope.COMPANY_LEVEL,
    )

    assert accepted.decision == AttachmentDecision.ATTACHED
    assert rejected.decision == AttachmentDecision.RELATED_ENTITY_ONLY


def test_unverified_product_relationship_is_ambiguous() -> None:
    identity = _identity(
        relationships=(
            _relationship(
                "widget.dev",
                "acme.com",
                EntityRelation.PRODUCT_OF,
                verified=False,
            ),
        )
    )

    decision = _assess(identity, url="https://widget.dev/releases")

    assert decision.decision == AttachmentDecision.UNATTACHED_ENTITY_AMBIGUOUS


@pytest.mark.parametrize(
    "relation",
    [
        EntityRelation.SUBSIDIARY_OF,
        EntityRelation.PARENT_OF,
        EntityRelation.SISTER_BRAND,
        EntityRelation.ACQUIRED_BY,
    ],
)
def test_related_company_evidence_is_not_promoted_to_account(
    relation: EntityRelation,
) -> None:
    identity = _identity(
        relationships=(_relationship("related.com", "acme.com", relation),)
    )

    decision = _assess(
        identity,
        url="https://related.com/news",
        scope=ClaimScope.COMPANY_LEVEL,
    )

    assert decision.decision == AttachmentDecision.RELATED_ENTITY_ONLY


def test_partner_event_is_related_only_and_not_buying_intent() -> None:
    identity = _identity(
        relationships=(
            _relationship("partner.com", "acme.com", EntityRelation.PARTNER_OF),
        )
    )

    decision = _assess(
        identity,
        url="https://partner.com/news",
        passage="Partner announced a partnership with Acme.",
        scope=ClaimScope.PARTNER_LEVEL,
    )

    assert decision.decision == AttachmentDecision.RELATED_ENTITY_ONLY
    assert decision.claim_scope_compatible is False


def test_verified_rebrand_can_support_company_scope() -> None:
    identity = _identity(
        relationships=(
            _relationship("old-acme.com", "acme.com", EntityRelation.REBRAND_OF),
        )
    )

    decision = _assess(
        identity,
        url="https://old-acme.com/history",
        scope=ClaimScope.COMPANY_LEVEL,
    )

    assert decision.decision == AttachmentDecision.ATTACHED


def test_unverified_alias_does_not_create_entity_match() -> None:
    identity = _identity(
        aliases=(VerifiedAlias("Acme Labs", ()),),
    )

    decision = _assess(
        identity,
        url="https://independent-news.test/story",
        role="NEWS",
        title="Acme Labs raises funding",
        passage="Acme Labs announced a seed round.",
    )

    assert decision.decision == AttachmentDecision.UNATTACHED_ENTITY_AMBIGUOUS


def test_verified_alias_in_independent_source_can_attach() -> None:
    identity = _identity(
        aliases=(VerifiedAlias("Acme Labs", ("alias-proof",)),),
    )

    decision = _assess(
        identity,
        url="https://independent-news.test/story",
        role="NEWS",
        title="Acme Labs raises funding",
        passage="Acme Labs announced a seed round.",
    )

    assert decision.decision == AttachmentDecision.ATTACHED


def test_optivian_ai_does_not_attach_to_optivian_cloud() -> None:
    decision = _assess(
        _identity(name="Optivian Cloud", domain="optivian.cloud"),
        url="https://optivian.ai/insights/funding-announcement",
        title="Optivian AI funding announcement",
        passage="Optivian AI raised a pre-seed round.",
    )

    assert decision.decision == AttachmentDecision.UNATTACHED_ENTITY_AMBIGUOUS
    assert decision.entity_match_confidence == 0


def test_source_naming_target_but_owned_by_another_domain_is_ambiguous() -> None:
    decision = _assess(
        _identity(),
        url="https://other-company.com/acme",
        title="Acme partnership",
        passage="Acme announced a partnership.",
    )

    assert decision.decision == AttachmentDecision.UNATTACHED_ENTITY_AMBIGUOUS


def test_ambiguous_subject_cannot_become_signal() -> None:
    fact_id = uuid4()
    source_id = uuid4()
    fact = SimpleNamespace(
        id=fact_id,
        source_id=source_id,
        claim="Acme raised a seed round.",
        passage="Acme raised a seed round.",
        observed_at=datetime.now(UTC),
    )
    ambiguous = _assess(
        _identity(),
        url="https://other-company.com/funding",
    )

    matches = _signals_from_facts(
        [fact],
        attachment_by_fact_id={fact_id: ambiguous},
    )

    assert matches == []


def test_cross_company_evidence_stays_with_matching_account_after_deduplication() -> None:
    source_url = "https://acme.ai/news"
    acme_ai = _assess(
        _identity(name="Acme AI", domain="acme.ai"),
        url=source_url,
    )
    acme_cloud = _assess(
        _identity(name="Acme Cloud", domain="acme.cloud"),
        url=source_url,
    )

    assert acme_ai.decision == AttachmentDecision.ATTACHED
    assert acme_cloud.decision == AttachmentDecision.UNATTACHED_ENTITY_AMBIGUOUS


def test_prequalification_outcome_preserves_uncertainty_and_review_states() -> None:
    assert (
        prequalification_outcome(
            "ACCEPTED",
            {"prequalification_outcome": "PREQUALIFIED_WITH_UNCERTAINTY"},
        )
        == "PREQUALIFIED_WITH_UNCERTAINTY"
    )
    assert prequalification_outcome("REVIEW_REQUIRED", {}) == "REVIEW_REQUIRED"
    assert prequalification_outcome("ACCEPTED", {}) == "PREQUALIFIED"


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        (
            {
                "identity_verified": True,
                "unresolved_identity_warnings": (),
                "qualification_status": "QUALIFIED",
                "has_supported_icp_fact": True,
                "has_actionable_signal": True,
                "supported_important_claims": True,
                "direct_competitor_conflict": False,
            },
            BriefState.FOUNDER_READY,
        ),
        (
            {
                "identity_verified": True,
                "unresolved_identity_warnings": ("conflict",),
                "qualification_status": "QUALIFIED",
                "has_supported_icp_fact": True,
                "has_actionable_signal": True,
                "supported_important_claims": False,
                "direct_competitor_conflict": False,
            },
            BriefState.IDENTITY_REVIEW_REQUIRED,
        ),
        (
            {
                "identity_verified": True,
                "unresolved_identity_warnings": (),
                "qualification_status": "QUALIFIED_WITH_UNCERTAINTY",
                "has_supported_icp_fact": True,
                "has_actionable_signal": False,
                "supported_important_claims": True,
                "direct_competitor_conflict": False,
            },
            BriefState.MONITOR,
        ),
        (
            {
                "identity_verified": True,
                "unresolved_identity_warnings": (),
                "qualification_status": "DISQUALIFIED",
                "has_supported_icp_fact": True,
                "has_actionable_signal": False,
                "supported_important_claims": True,
                "direct_competitor_conflict": True,
            },
            BriefState.DO_NOT_TARGET,
        ),
    ],
)
def test_brief_state_gate(kwargs: dict[str, object], expected: BriefState) -> None:
    assert decide_brief_state(**kwargs) == expected  # type: ignore[arg-type]
