"""entity-safety: stop evidence attaching to the wrong company.

In any retrieval or agent pipeline that gathers facts about a named entity,
some of what comes back is about a *different* entity with a similar name, or
about a related-but-distinct one -- a parent, a subsidiary, a product, a
company that merely shares a brand token. Similarity scoring cannot tell those
apart, because they are genuinely similar; that is the whole problem.

This library answers one question with an auditable reason:

    may this passage support a claim about this entity?

    >>> from entity_safety import CompanyIdentityRecord, assess_evidence_attachment
    >>> identity = CompanyIdentityRecord(
    ...     canonical_company_name="Optivian",
    ...     canonical_registrable_domain="optivian.ai",
    ...     verified_official_domains=("optivian.ai",),
    ... )
    >>> result = assess_evidence_attachment(
    ...     identity,
    ...     source_url="https://optivian.cloud/press/series-b",
    ...     source_role="FIRST_PARTY",
    ...     source_title="Optivian raises Series B",
    ...     passage="Optivian today announced a $40M Series B.",
    ... )
    >>> result.decision
    <AttachmentDecision.UNATTACHED_ENTITY_AMBIGUOUS: 'UNATTACHED_ENTITY_AMBIGUOUS'>
    >>> result.reason
    'Different first-party domain has no verified account relationship.'

Same brand token, same industry, plausible headline, wrong company. A naive
matcher attaches it and reports a funding round that never happened.
"""

from entity_safety.attachment import (
    assess_evidence_attachment,
    claim_scope_is_compatible,
    domains_in_text,
    infer_claim_scope,
    normalized_entity_name,
)
from entity_safety.domains import registrable_domain
from entity_safety.model import (
    SOURCE_ROLE_FIRST_PARTY,
    AttachmentDecision,
    ClaimScope,
    CompanyIdentityRecord,
    EntityRelation,
    EvidenceAttachmentAssessment,
    VerifiedAlias,
    VerifiedEntityRelationship,
)

__version__ = "0.1.0"

__all__ = [
    "SOURCE_ROLE_FIRST_PARTY",
    "AttachmentDecision",
    "ClaimScope",
    "CompanyIdentityRecord",
    "EntityRelation",
    "EvidenceAttachmentAssessment",
    "VerifiedAlias",
    "VerifiedEntityRelationship",
    "assess_evidence_attachment",
    "claim_scope_is_compatible",
    "domains_in_text",
    "infer_claim_scope",
    "normalized_entity_name",
    "registrable_domain",
    "__version__",
]
