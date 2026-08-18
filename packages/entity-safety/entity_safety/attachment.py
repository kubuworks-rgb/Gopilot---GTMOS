"""The dual gate: may this passage support a claim about this entity?

The logic here is unchanged from the implementation it was extracted from. It
is covered by an adversarial suite of real near-miss company pairs, and that
suite was confirmed to catch regressions by deliberately reintroducing naive
brand-token matching. Behaviour was deliberately not "improved" during
extraction -- the tests are the asset, and changing behaviour would have
invalidated them.
"""

from __future__ import annotations

import re

from entity_safety.domains import registrable_domain
from entity_safety.model import (
    AttachmentDecision,
    ClaimScope,
    CompanyIdentityRecord,
    EntityRelation,
    EvidenceAttachmentAssessment,
    SOURCE_ROLE_FIRST_PARTY,
)


_DOMAIN_PATTERN = re.compile(
    r"(?<![a-z0-9-])(?:https?://)?(?:www\.)?"
    r"([a-z0-9][a-z0-9-]*(?:\.[a-z0-9][a-z0-9-]*)+)",
    re.IGNORECASE,
)

# Dropped before comparing names, so "Optivian Technologies Inc" and "Optivian"
# compare equal. Note this cuts both ways and is why token overlap alone is not
# safe: it also makes "Optivian" and "Optivian" from two different companies
# compare equal, which is precisely the failure this module exists to stop.
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
    """Lowercase alphanumeric tokens with corporate suffixes removed."""
    tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", value.lower())
        if token not in _CORPORATE_SUFFIXES
    ]
    return " ".join(tokens)


def _mentions_name(text: str, name: str) -> bool:
    """Whole-token match only.

    The length floor and the boundary assertions are load-bearing: a substring
    match would let "Ably" match "Ablyft", which is the single most common way
    brand-token matching contaminates a corpus.
    """
    normalized = normalized_entity_name(name)
    if len(normalized) < 4:
        return False
    haystack = normalized_entity_name(text)
    return (
        re.search(
            rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])",
            haystack,
        )
        is not None
    )


def domains_in_text(text: str) -> set[str]:
    """Every registrable domain mentioned in a passage."""
    domains: set[str] = set()
    for match in _DOMAIN_PATTERN.finditer(text.lower()):
        domain = registrable_domain(match.group(1))
        if domain:
            domains.add(domain)
    return domains


def infer_claim_scope(text: str) -> ClaimScope:
    """Best-effort scope from the wording of a claim.

    Deliberately keyword-driven and conservative. Callers that already know the
    scope should pass it explicitly rather than relying on inference.
    """
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


def claim_scope_is_compatible(relation: EntityRelation, scope: ClaimScope) -> bool:
    """Which relationships may carry which claim scopes.

    Restrictive on purpose. The same entity may carry a company-level claim but
    not a parent-level or subsidiary-level one, because a claim about the parent
    is not a claim about the company even when the source is the company itself.
    A product relationship carries product-level claims and nothing else.
    Everything not named here fails closed.
    """
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
    """Decide whether `passage` may support a claim about `identity`.

    `source_role` is `"FIRST_PARTY"` for a document retrieved from a company's
    own site, anything else for third-party sources. `conflicting_entities` are
    names known to be confusable with the target; naming them turns a silent
    mis-attachment into an explicit rejection.

    Returns a decision with the reason and every input that produced it. Never
    raises on unknown input -- an unresolvable case is a rejection, not an error.
    """
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

    if source_role == SOURCE_ROLE_FIRST_PARTY and source_domain:
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
        external_scope_compatible = claim_scope_is_compatible(external_relation, scope)
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
