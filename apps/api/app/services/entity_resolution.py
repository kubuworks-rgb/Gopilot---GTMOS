from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from enum import StrEnum

from apps.api.app.services.company_identity import registrable_domain


class EntityRelation(StrEnum):
    SAME_ENTITY = "SAME_ENTITY"
    PRODUCT_OF = "PRODUCT_OF"
    SUBSIDIARY_OF = "SUBSIDIARY_OF"
    PARENT_OF = "PARENT_OF"
    SISTER_BRAND = "SISTER_BRAND"
    REBRAND_OF = "REBRAND_OF"
    ACQUIRED_BY = "ACQUIRED_BY"
    PARTNER_OF = "PARTNER_OF"
    UNRELATED = "UNRELATED"
    UNKNOWN = "UNKNOWN"


class ClaimScope(StrEnum):
    COMPANY_LEVEL = "COMPANY_LEVEL"
    PRODUCT_LEVEL = "PRODUCT_LEVEL"
    PARENT_LEVEL = "PARENT_LEVEL"
    SUBSIDIARY_LEVEL = "SUBSIDIARY_LEVEL"
    MARKET_LEVEL = "MARKET_LEVEL"
    PARTNER_LEVEL = "PARTNER_LEVEL"


class AttachmentDecision(StrEnum):
    ATTACHED = "ATTACHED"
    UNATTACHED_ENTITY_AMBIGUOUS = "UNATTACHED_ENTITY_AMBIGUOUS"
    RELATED_ENTITY_ONLY = "RELATED_ENTITY_ONLY"


class BriefState(StrEnum):
    FOUNDER_READY = "FOUNDER_READY"
    RESEARCH_CANDIDATE = "RESEARCH_CANDIDATE"
    MONITOR = "MONITOR"
    DO_NOT_TARGET = "DO_NOT_TARGET"
    IDENTITY_REVIEW_REQUIRED = "IDENTITY_REVIEW_REQUIRED"


@dataclass(frozen=True)
class VerifiedAlias:
    name: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class VerifiedEntityRelationship:
    subject_domain: str
    object_domain: str
    relation: EntityRelation
    evidence_ids: tuple[str, ...]

    @property
    def verified(self) -> bool:
        return bool(self.evidence_ids) and self.relation not in {
            EntityRelation.UNKNOWN,
            EntityRelation.UNRELATED,
        }


@dataclass(frozen=True)
class CompanyIdentityRecord:
    canonical_company_name: str
    canonical_registrable_domain: str
    verified_official_domains: tuple[str, ...]
    known_aliases: tuple[VerifiedAlias, ...] = ()
    legal_name: str | None = None
    product_names: tuple[VerifiedAlias, ...] = ()
    product_domains: tuple[str, ...] = ()
    parent_organization: str | None = None
    subsidiaries: tuple[str, ...] = ()
    relationships: tuple[VerifiedEntityRelationship, ...] = ()
    relationship_evidence_ids: tuple[str, ...] = ()
    identity_confidence: float = 0
    unresolved_identity_warnings: tuple[str, ...] = ()

    def as_persisted_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceAttachmentAssessment:
    source_domain: str | None
    subject_entity: str | None
    canonical_subject_domain: str | None
    relation: EntityRelation
    claim_scope: ClaimScope
    identity_compatible: bool
    claim_scope_compatible: bool
    entity_match_confidence: float
    decision: AttachmentDecision
    reason: str

    def as_persisted_dict(self) -> dict[str, object]:
        return asdict(self)


_DOMAIN_PATTERN = re.compile(
    r"(?<![a-z0-9-])(?:https?://)?(?:www\.)?"
    r"([a-z0-9][a-z0-9-]*(?:\.[a-z0-9][a-z0-9-]*)+)",
    re.IGNORECASE,
)
_CORPORATE_SUFFIXES = {
    "inc",
    "incorporated",
    "llc",
    "ltd",
    "limited",
    "pvt",
    "private",
    "corp",
    "corporation",
    "company",
    "technologies",
    "technology",
}


def normalized_entity_name(value: str) -> str:
    tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", value.lower())
        if token not in _CORPORATE_SUFFIXES
    ]
    return " ".join(tokens)


def _mentions_name(text: str, name: str) -> bool:
    normalized = normalized_entity_name(name)
    if len(normalized) < 4:
        return False
    haystack = normalized_entity_name(text)
    return re.search(
        rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])",
        haystack,
    ) is not None


def domains_in_text(text: str) -> set[str]:
    domains: set[str] = set()
    for match in _DOMAIN_PATTERN.finditer(text.lower()):
        domain = registrable_domain(match.group(1))
        if domain:
            domains.add(domain)
    return domains


def infer_claim_scope(text: str) -> ClaimScope:
    lowered = text.lower()
    if any(
        marker in lowered
        for marker in (
            "partnered with",
            "partnership",
            "in partnership with",
            "collaboration with",
        )
    ):
        return ClaimScope.PARTNER_LEVEL
    if any(marker in lowered for marker in ("subsidiary", "business unit")):
        return ClaimScope.SUBSIDIARY_LEVEL
    if any(marker in lowered for marker in ("parent company", "holding company")):
        return ClaimScope.PARENT_LEVEL
    if any(
        marker in lowered
        for marker in (
            "market size",
            "industry trend",
            "market report",
            "sector growth",
        )
    ):
        return ClaimScope.MARKET_LEVEL
    if any(
        marker in lowered
        for marker in (
            "product launch",
            "launched",
            "new product",
            "platform release",
            "software release",
        )
    ):
        return ClaimScope.PRODUCT_LEVEL
    return ClaimScope.COMPANY_LEVEL


def _relationship_for_domain(
    identity: CompanyIdentityRecord,
    source_domain: str | None,
) -> EntityRelation:
    if source_domain in identity.verified_official_domains:
        return EntityRelation.SAME_ENTITY
    for relationship in identity.relationships:
        if (
            relationship.subject_domain == source_domain
            and relationship.object_domain == identity.canonical_registrable_domain
            and relationship.verified
        ):
            return relationship.relation
    return EntityRelation.UNKNOWN


def claim_scope_is_compatible(
    relation: EntityRelation,
    scope: ClaimScope,
) -> bool:
    if relation in {EntityRelation.SAME_ENTITY, EntityRelation.REBRAND_OF}:
        return scope not in {
            ClaimScope.PARENT_LEVEL,
            ClaimScope.SUBSIDIARY_LEVEL,
        }
    if relation == EntityRelation.PRODUCT_OF:
        return scope == ClaimScope.PRODUCT_LEVEL
    return False


def assess_evidence_attachment(
    identity: CompanyIdentityRecord,
    *,
    source_url: str,
    source_role: str,
    source_title: str,
    passage: str,
    subject_entity: str | None = None,
    subject_domain: str | None = None,
    claim_scope: ClaimScope | None = None,
    conflicting_entities: tuple[str, ...] = (),
) -> EvidenceAttachmentAssessment:
    source_domain = registrable_domain(source_url)
    scope = claim_scope or infer_claim_scope(passage)
    relation = _relationship_for_domain(identity, source_domain)
    subject = subject_entity or source_title or None
    canonical_subject_domain = (
        registrable_domain(subject_domain) if subject_domain else source_domain
    )
    scope_compatible = claim_scope_is_compatible(relation, scope)

    if relation == EntityRelation.SAME_ENTITY and scope_compatible:
        return EvidenceAttachmentAssessment(
            source_domain=source_domain,
            subject_entity=subject,
            canonical_subject_domain=identity.canonical_registrable_domain,
            relation=relation,
            claim_scope=scope,
            identity_compatible=True,
            claim_scope_compatible=True,
            entity_match_confidence=1.0,
            decision=AttachmentDecision.ATTACHED,
            reason="Source domain is a verified official account domain.",
        )

    if relation not in {EntityRelation.UNKNOWN, EntityRelation.UNRELATED}:
        if scope_compatible:
            return EvidenceAttachmentAssessment(
                source_domain=source_domain,
                subject_entity=subject,
                canonical_subject_domain=canonical_subject_domain,
                relation=relation,
                claim_scope=scope,
                identity_compatible=True,
                claim_scope_compatible=True,
                entity_match_confidence=0.95,
                decision=AttachmentDecision.ATTACHED,
                reason="Verified entity relationship and claim scope are compatible.",
            )
        return EvidenceAttachmentAssessment(
            source_domain=source_domain,
            subject_entity=subject,
            canonical_subject_domain=canonical_subject_domain,
            relation=relation,
            claim_scope=scope,
            identity_compatible=True,
            claim_scope_compatible=False,
            entity_match_confidence=0.9,
            decision=AttachmentDecision.RELATED_ENTITY_ONLY,
            reason="Verified related entity exists, but claim scope is not account-level.",
        )

    if source_role == "FIRST_PARTY" and source_domain:
        return EvidenceAttachmentAssessment(
            source_domain=source_domain,
            subject_entity=subject,
            canonical_subject_domain=source_domain,
            relation=EntityRelation.UNKNOWN,
            claim_scope=scope,
            identity_compatible=False,
            claim_scope_compatible=False,
            entity_match_confidence=0.0,
            decision=AttachmentDecision.UNATTACHED_ENTITY_AMBIGUOUS,
            reason="Different first-party domain has no verified account relationship.",
        )

    combined_text = f"{source_title} {passage}"
    explicit_domains = domains_in_text(combined_text)
    conflicting_domains = explicit_domains - set(identity.verified_official_domains)
    conflicting_name = next(
        (
            item
            for item in conflicting_entities
            if item and _mentions_name(combined_text, item)
        ),
        None,
    )
    unverified_alias = next(
        (
            alias.name
            for alias in identity.known_aliases
            if not alias.evidence_ids and _mentions_name(combined_text, alias.name)
        ),
        None,
    )
    if conflicting_name or conflicting_domains or unverified_alias:
        return EvidenceAttachmentAssessment(
            source_domain=source_domain,
            subject_entity=conflicting_name or unverified_alias or subject,
            canonical_subject_domain=(
                sorted(conflicting_domains)[0] if conflicting_domains else None
            ),
            relation=EntityRelation.UNKNOWN,
            claim_scope=scope,
            identity_compatible=False,
            claim_scope_compatible=False,
            entity_match_confidence=0.0,
            decision=AttachmentDecision.UNATTACHED_ENTITY_AMBIGUOUS,
            reason="Source text identifies a conflicting or unresolved entity.",
        )

    verified_names = (
        identity.canonical_company_name,
        *(alias.name for alias in identity.known_aliases if alias.evidence_ids),
    )
    if any(_mentions_name(combined_text, name) for name in verified_names):
        external_relation = EntityRelation.SAME_ENTITY
        external_scope_compatible = claim_scope_is_compatible(
            external_relation, scope
        )
        if external_scope_compatible:
            return EvidenceAttachmentAssessment(
                source_domain=source_domain,
                subject_entity=identity.canonical_company_name,
                canonical_subject_domain=identity.canonical_registrable_domain,
                relation=external_relation,
                claim_scope=scope,
                identity_compatible=True,
                claim_scope_compatible=True,
                entity_match_confidence=0.85,
                decision=AttachmentDecision.ATTACHED,
                reason="Independent source explicitly names the verified account entity.",
            )

    return EvidenceAttachmentAssessment(
        source_domain=source_domain,
        subject_entity=subject,
        canonical_subject_domain=canonical_subject_domain,
        relation=EntityRelation.UNKNOWN,
        claim_scope=scope,
        identity_compatible=False,
        claim_scope_compatible=False,
        entity_match_confidence=0.0,
        decision=AttachmentDecision.UNATTACHED_ENTITY_AMBIGUOUS,
        reason="Account identity or verified alias is not established by the source.",
    )


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
