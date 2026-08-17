"""Entity-safety demonstration: evidence must not leak between confusable companies.

Blueprint section 9. This is the differentiator suite -- a single place to point at
when asked "prove evidence from one company cannot silently attach to a similarly
named one". Every row is a near-miss pair that a naive brand-token matcher would
merge.

Run just this file to see the guarantee:

    python -m pytest apps/api/tests/test_confusable_pairs.py -v

The headline invariant is `test_no_confusable_pair_contaminates_the_account`: across
the whole matrix, not one unproven relationship produces an ATTACHED decision.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from apps.api.app.services.entity_resolution import (
    AttachmentDecision,
    ClaimScope,
    CompanyIdentityRecord,
    EntityRelation,
    VerifiedAlias,
    VerifiedEntityRelationship,
    assess_evidence_attachment,
)


ACCOUNT_DOMAIN = "acme.com"
ACCOUNT_NAME = "Acme"


def _identity(
    *,
    official_domains: tuple[str, ...] = (ACCOUNT_DOMAIN,),
    relationships: tuple[VerifiedEntityRelationship, ...] = (),
    aliases: tuple[VerifiedAlias, ...] = (),
) -> CompanyIdentityRecord:
    return CompanyIdentityRecord(
        canonical_company_name=ACCOUNT_NAME,
        canonical_registrable_domain=ACCOUNT_DOMAIN,
        verified_official_domains=official_domains,
        known_aliases=aliases,
        relationships=relationships,
        identity_confidence=0.99,
    )


def _proven(
    subject: str, relation: EntityRelation
) -> VerifiedEntityRelationship:
    """A relationship backed by evidence. Without evidence_ids it is not verified."""
    return VerifiedEntityRelationship(
        subject_domain=subject,
        object_domain=ACCOUNT_DOMAIN,
        relation=relation,
        evidence_ids=("evidence-1",),
    )


def _unproven(subject: str, relation: EntityRelation) -> VerifiedEntityRelationship:
    return VerifiedEntityRelationship(
        subject_domain=subject,
        object_domain=ACCOUNT_DOMAIN,
        relation=relation,
        evidence_ids=(),
    )


@dataclass(frozen=True)
class ConfusablePair:
    label: str
    source_url: str
    expected: AttachmentDecision
    why: str
    identity: CompanyIdentityRecord
    scope: ClaimScope = ClaimScope.COMPANY_LEVEL


# --------------------------------------------------------------------------------
# Pairs a naive matcher would merge. Everything here shares a brand token with the
# account, which is exactly why brand tokens must never drive attachment.
# --------------------------------------------------------------------------------
UNPROVEN_PAIRS: list[ConfusablePair] = [
    ConfusablePair(
        label="same name, different TLD (the historical Optivian defect)",
        source_url="https://acme.ai/about",
        expected=AttachmentDecision.UNATTACHED_ENTITY_AMBIGUOUS,
        why="different registrable domain, no proven relationship",
        identity=_identity(),
    ),
    ConfusablePair(
        label="same name, .io",
        source_url="https://acme.io/company",
        expected=AttachmentDecision.UNATTACHED_ENTITY_AMBIGUOUS,
        why="different registrable domain",
        identity=_identity(),
    ),
    ConfusablePair(
        label="same name, country TLD",
        source_url="https://acme.co.uk/about",
        expected=AttachmentDecision.UNATTACHED_ENTITY_AMBIGUOUS,
        why="a national namesake is a different company until proven otherwise",
        identity=_identity(),
    ),
    ConfusablePair(
        label="hyphenated lookalike",
        source_url="https://acme-inc.com/about",
        expected=AttachmentDecision.UNATTACHED_ENTITY_AMBIGUOUS,
        why="legal-suffix variants are not automatically the same entity",
        identity=_identity(),
    ),
    ConfusablePair(
        label="typosquat",
        source_url="https://acmme.com/about",
        expected=AttachmentDecision.UNATTACHED_ENTITY_AMBIGUOUS,
        why="near-miss spelling must never resolve to the account",
        identity=_identity(),
    ),
    ConfusablePair(
        label="brand-prefixed unrelated company",
        source_url="https://acmehealth.com/about",
        expected=AttachmentDecision.UNATTACHED_ENTITY_AMBIGUOUS,
        why="shared prefix is not a relationship",
        identity=_identity(),
    ),
    ConfusablePair(
        label="claimed subsidiary with no evidence",
        source_url="https://acme-labs.com/about",
        expected=AttachmentDecision.UNATTACHED_ENTITY_AMBIGUOUS,
        why="an unproven relationship carries no weight",
        identity=_identity(
            relationships=(_unproven("acme-labs.com", EntityRelation.SUBSIDIARY_OF),)
        ),
    ),
    ConfusablePair(
        label="claimed product domain with no evidence",
        source_url="https://acmecloud.com/product",
        expected=AttachmentDecision.UNATTACHED_ENTITY_AMBIGUOUS,
        why="an unproven PRODUCT_OF must not attach even at product scope",
        identity=_identity(
            relationships=(_unproven("acmecloud.com", EntityRelation.PRODUCT_OF),)
        ),
        scope=ClaimScope.PRODUCT_LEVEL,
    ),
]

# --------------------------------------------------------------------------------
# Proven relationships. These are real, but a relationship is not a licence to treat
# another company's facts as the account's facts -- scope still decides.
# --------------------------------------------------------------------------------
PROVEN_PAIRS: list[ConfusablePair] = [
    ConfusablePair(
        label="verified second official domain",
        source_url="https://acme.net/about",
        expected=AttachmentDecision.ATTACHED,
        why="listed as an official domain of the same entity",
        identity=_identity(official_domains=(ACCOUNT_DOMAIN, "acme.net")),
    ),
    ConfusablePair(
        label="proven rebrand, company-level claim",
        source_url="https://oldacme.com/news",
        expected=AttachmentDecision.ATTACHED,
        why="a rebrand is the same company under a former name",
        identity=_identity(
            relationships=(_proven("oldacme.com", EntityRelation.REBRAND_OF),)
        ),
    ),
    ConfusablePair(
        label="proven product domain, product-level claim",
        source_url="https://acmecloud.com/product",
        expected=AttachmentDecision.ATTACHED,
        why="product-scope claims may attach through a proven PRODUCT_OF",
        identity=_identity(
            relationships=(_proven("acmecloud.com", EntityRelation.PRODUCT_OF),)
        ),
        scope=ClaimScope.PRODUCT_LEVEL,
    ),
    ConfusablePair(
        label="proven product domain, company-level claim",
        source_url="https://acmecloud.com/about",
        expected=AttachmentDecision.RELATED_ENTITY_ONLY,
        why="a product's page cannot establish a fact about the whole company",
        identity=_identity(
            relationships=(_proven("acmecloud.com", EntityRelation.PRODUCT_OF),)
        ),
    ),
    ConfusablePair(
        label="proven parent, company-level claim",
        source_url="https://acmegroup.com/about",
        expected=AttachmentDecision.RELATED_ENTITY_ONLY,
        why="the parent's facts are not the subsidiary's facts",
        identity=_identity(
            relationships=(_proven("acmegroup.com", EntityRelation.PARENT_OF),)
        ),
    ),
    ConfusablePair(
        label="proven subsidiary, company-level claim",
        source_url="https://acmesub.com/about",
        expected=AttachmentDecision.RELATED_ENTITY_ONLY,
        why="a subsidiary's facts are not the parent's facts",
        identity=_identity(
            relationships=(_proven("acmesub.com", EntityRelation.SUBSIDIARY_OF),)
        ),
    ),
    ConfusablePair(
        label="proven sister brand",
        source_url="https://siblingbrand.com/news",
        expected=AttachmentDecision.RELATED_ENTITY_ONLY,
        why="shared ownership is not shared identity",
        identity=_identity(
            relationships=(_proven("siblingbrand.com", EntityRelation.SISTER_BRAND),)
        ),
    ),
    ConfusablePair(
        label="proven partner",
        source_url="https://partnerco.com/press",
        expected=AttachmentDecision.RELATED_ENTITY_ONLY,
        why="a partner's activity is not the account's buying intent",
        identity=_identity(
            relationships=(_proven("partnerco.com", EntityRelation.PARTNER_OF),)
        ),
    ),
    ConfusablePair(
        label="proven acquirer",
        source_url="https://acquirer.com/press",
        expected=AttachmentDecision.RELATED_ENTITY_ONLY,
        why="the acquirer is a separate legal entity",
        identity=_identity(
            relationships=(_proven("acquirer.com", EntityRelation.ACQUIRED_BY),)
        ),
    ),
]

ALL_PAIRS = UNPROVEN_PAIRS + PROVEN_PAIRS


def _assess(pair: ConfusablePair):
    return assess_evidence_attachment(
        pair.identity,
        source_url=pair.source_url,
        source_role="FIRST_PARTY",
        source_title=f"{ACCOUNT_NAME} — company information",
        passage=f"{ACCOUNT_NAME} announced a significant company update today.",
        claim_scope=pair.scope,
    )


@pytest.mark.parametrize("pair", ALL_PAIRS, ids=[item.label for item in ALL_PAIRS])
def test_confusable_pair_resolves_as_specified(pair: ConfusablePair) -> None:
    assessment = _assess(pair)

    assert assessment.decision is pair.expected, (
        f"{pair.label}: expected {pair.expected.value}, "
        f"got {assessment.decision.value} — {pair.why}"
    )


def test_no_confusable_pair_contaminates_the_account() -> None:
    """The headline guarantee: no unproven relationship ever attaches.

    This is the invariant the Optivian defect violated. Note that the passage
    explicitly names the account and the source title carries the brand, so every
    lexical cue points the wrong way -- and attachment still requires a proven
    relationship.
    """
    contaminated = [
        pair.label
        for pair in UNPROVEN_PAIRS
        if _assess(pair).decision is AttachmentDecision.ATTACHED
    ]

    assert contaminated == [], (
        "evidence leaked onto the account from unrelated domains: "
        + ", ".join(contaminated)
    )


def test_unproven_pairs_never_claim_identity_compatibility() -> None:
    for pair in UNPROVEN_PAIRS:
        assessment = _assess(pair)
        assert not assessment.identity_compatible, pair.label
        assert assessment.entity_match_confidence == 0.0, pair.label


def test_related_entities_are_recognised_but_still_withheld() -> None:
    """A proven relationship is not a licence to borrow facts.

    Distinguishing RELATED_ENTITY_ONLY from UNATTACHED matters: the first says "we
    know who this is and it is not you", which is a materially different answer for
    the founder reading the rejected-evidence panel.
    """
    related = [
        pair
        for pair in PROVEN_PAIRS
        if pair.expected is AttachmentDecision.RELATED_ENTITY_ONLY
    ]
    assert related, "the matrix must exercise related-but-withheld cases"

    for pair in related:
        assessment = _assess(pair)
        assert assessment.identity_compatible, pair.label
        assert not assessment.claim_scope_compatible, pair.label
        assert assessment.relation is not EntityRelation.UNKNOWN, pair.label


def test_the_optivian_defect_specifically() -> None:
    """The original production bug, kept as its own named case.

    optivian.ai evidence attached to optivian.cloud because brand-token matching
    treated them as one company.
    """
    optivian_cloud = CompanyIdentityRecord(
        canonical_company_name="Optivian",
        canonical_registrable_domain="optivian.cloud",
        verified_official_domains=("optivian.cloud",),
        identity_confidence=0.99,
    )

    assessment = assess_evidence_attachment(
        optivian_cloud,
        source_url="https://optivian.ai/blog/series-a",
        source_role="FIRST_PARTY",
        source_title="Optivian raises Series A",
        passage="Optivian announced a Series A funding round this week.",
    )

    assert assessment.decision is AttachmentDecision.UNATTACHED_ENTITY_AMBIGUOUS
    assert not assessment.identity_compatible


def test_the_matrix_covers_every_relation_the_model_defines() -> None:
    """Guards against a relation being added without a confusable-pair case."""
    exercised = {
        relationship.relation
        for pair in ALL_PAIRS
        for relationship in pair.identity.relationships
    }
    unexercised = (
        set(EntityRelation)
        - exercised
        - {EntityRelation.SAME_ENTITY, EntityRelation.UNRELATED, EntityRelation.UNKNOWN}
    )

    assert unexercised == set(), (
        "relations with no confusable-pair coverage: "
        + ", ".join(sorted(item.value for item in unexercised))
    )
