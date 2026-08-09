"""Per-fact confidence must be computed, not asserted.

Every evidence fact used to be written with a hardcoded 0.82 and rendered as
"82% confidence" on every passage in every brief, implying a per-fact judgement
that did not exist. Shipping a fabricated number as if it were computed is exactly
the kind of false precision the product's evidence-first promise rules out.
"""

from __future__ import annotations

import pytest

from apps.api.app.services.intelligence_quality import SourceRole, source_quality_score
from apps.api.app.services.live_research import evidence_confidence


def test_confidence_varies_with_source_quality() -> None:
    """The defect: a directory listing scored identically to an official page."""
    first_party = source_quality_score(
        role=SourceRole.FIRST_PARTY, directness=0.95, recency=0.85, entity_match=0.95
    )
    directory = source_quality_score(
        role=SourceRole.DIRECTORY, directness=0.70, recency=0.55, entity_match=0.70
    )

    assert evidence_confidence(
        source_trust=first_party, context_matched=True
    ) > evidence_confidence(source_trust=directory, context_matched=True)


def test_a_fallback_passage_is_weaker_than_a_matched_one() -> None:
    """Same source, but nothing matched the research question."""
    trust = 0.9

    assert evidence_confidence(
        source_trust=trust, context_matched=False
    ) < evidence_confidence(source_trust=trust, context_matched=True)


def test_no_fact_ever_claims_certainty() -> None:
    assert evidence_confidence(source_trust=1.0, context_matched=True) <= 0.99


def test_confidence_stays_within_the_model_bounds() -> None:
    """EvidenceFact validates 0..1, so the function must never leave that range."""
    for trust in (0.0, 0.01, 0.35, 0.5, 0.88, 1.0):
        for matched in (True, False):
            value = evidence_confidence(source_trust=trust, context_matched=matched)
            assert 0.0 <= value <= 1.0


def test_a_worthless_source_still_produces_a_usable_number() -> None:
    assert evidence_confidence(source_trust=0.0, context_matched=False) >= 0.05


def test_it_is_deterministic() -> None:
    assert evidence_confidence(source_trust=0.7, context_matched=True) == (
        evidence_confidence(source_trust=0.7, context_matched=True)
    )


@pytest.mark.parametrize(
    "role",
    [
        SourceRole.FIRST_PARTY,
        SourceRole.NEWS,
        SourceRole.DIRECTORY,
        SourceRole.COMMUNITY,
        SourceRole.VENDOR_MARKETING,
    ],
)
def test_every_source_role_yields_a_distinct_grounded_value(role: SourceRole) -> None:
    trust = source_quality_score(
        role=role, directness=0.8, recency=0.7, entity_match=0.8
    )
    value = evidence_confidence(source_trust=trust, context_matched=True)

    assert 0.0 < value <= 0.99
    # The old constant must not reappear for every role by coincidence.
    assert value == round(min(0.99, trust), 2)


def test_the_old_constant_is_no_longer_universal() -> None:
    """Guards the actual regression: one number for every fact regardless of source."""
    values = {
        evidence_confidence(
            source_trust=source_quality_score(
                role=role, directness=0.9, recency=0.8, entity_match=0.9
            ),
            context_matched=matched,
        )
        for role in (SourceRole.FIRST_PARTY, SourceRole.NEWS, SourceRole.DIRECTORY)
        for matched in (True, False)
    }

    assert len(values) > 1, "confidence collapsed back to a single constant"
