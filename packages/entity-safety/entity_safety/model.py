"""The vocabulary of the dual gate: who an entity is, and what a claim is about.

Two independent questions have to be answered before a passage may support a
claim about a company:

1. **Identity** -- what is the relationship between the source and the target?
2. **Claim scope** -- what level is the claim actually about?

Keeping them separate is the point. A funding announcement about a *parent*
company is a real, verified, correctly-attributed claim -- and still not a
funding claim about the subsidiary you are researching. Collapsing the two
questions into one similarity score is exactly how that distinction gets lost.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum


class EntityRelation(StrEnum):
    """How a source entity relates to the target entity."""

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
    """What level of the corporate tree a claim is actually about."""

    COMPANY_LEVEL = "COMPANY_LEVEL"
    PRODUCT_LEVEL = "PRODUCT_LEVEL"
    PARENT_LEVEL = "PARENT_LEVEL"
    SUBSIDIARY_LEVEL = "SUBSIDIARY_LEVEL"
    MARKET_LEVEL = "MARKET_LEVEL"
    PARTNER_LEVEL = "PARTNER_LEVEL"


class AttachmentDecision(StrEnum):
    """The outcome of the dual gate.

    `RELATED_ENTITY_ONLY` is deliberately distinct from
    `UNATTACHED_ENTITY_AMBIGUOUS`: the first means "we know exactly who this is
    about, and it is not your target"; the second means "we could not establish
    who this is about". Collapsing them into a single rejection throws away the
    difference between a verified fact about the wrong company and an unknown.
    """

    ATTACHED = "ATTACHED"
    UNATTACHED_ENTITY_AMBIGUOUS = "UNATTACHED_ENTITY_AMBIGUOUS"
    RELATED_ENTITY_ONLY = "RELATED_ENTITY_ONLY"


# Source roles understood by `assess_evidence_attachment`. FIRST_PARTY means the
# document was retrieved from a company's own website; anything else is treated
# as third-party. A plain string is accepted so callers are not forced to import
# an enum for one value.
SOURCE_ROLE_FIRST_PARTY = "FIRST_PARTY"


@dataclass(frozen=True)
class VerifiedAlias:
    """An alternative name for an entity.

    `evidence_ids` is what separates a verified alias from a rumoured one. An
    alias with no evidence behind it is treated as a reason for suspicion, not
    as a reason to attach: an unproven alias appearing in a passage is a signal
    that the passage may be about somebody else entirely.
    """

    name: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class VerifiedEntityRelationship:
    """A claimed relationship between two domains, and what proves it."""

    subject_domain: str
    object_domain: str
    relation: EntityRelation
    evidence_ids: tuple[str, ...]

    @property
    def verified(self) -> bool:
        """Unproven, unknown and unrelated all fail closed."""
        return bool(self.evidence_ids) and self.relation not in {
            EntityRelation.UNKNOWN,
            EntityRelation.UNRELATED,
        }


@dataclass(frozen=True)
class CompanyIdentityRecord:
    """Everything known about the entity a claim is being attached to.

    Only `canonical_company_name` and `canonical_registrable_domain` are
    required. The rest narrows or widens what may attach: more verified
    relationships admit more evidence, and unverified aliases actively push
    toward rejection.
    """

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
    """A decision, plus every input that produced it.

    The `reason` is part of the contract, not a debug string: a rejection a user
    cannot inspect is indistinguishable from a bug, and the whole value of the
    gate is that its refusals can be audited.
    """

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

    @property
    def attached(self) -> bool:
        return self.decision is AttachmentDecision.ATTACHED

    def as_persisted_dict(self) -> dict[str, object]:
        return asdict(self)
