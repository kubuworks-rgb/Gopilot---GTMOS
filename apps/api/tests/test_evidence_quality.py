"""Evidence must read as claims, and unknown must not be scored as a mismatch.

Both defects were found by clicking through the deployed product in a browser and
reading the brief it actually rendered for a real company:

1. Navigation and footer blobs were shown under "VERIFIED PUBLIC EVIDENCE" as
   SUPPORTED facts at 82% confidence -- the product's promise exactly inverted.
2. Fit was 0 for a correctly verified company, because absent industry and
   geography evidence was scored as a hard 0 rather than left unknown.
"""

from __future__ import annotations

import pytest

from apps.api.app.services.live_research import (
    _is_boilerplate_passage,
    _target_geography_terms,
    _usable_passages,
)
from apps.api.app.services.scoring import score_account


# Verbatim from the brief the deployed app rendered for djangoproject.com.
DJANGO_FOOTER = (
    "The Django Software Foundation About the Foundation Our non-profit supports "
    "the project Support Django Your contribution makes Django stronger Contact "
    "the Django Software Foundation More about the DSF Django Links Learn More "
    "About Django Getting Started with Django Team Organization Django Software "
    "Foundation Code of Conduct Diversity Statement Get Involved Join a Group "
    "Contribute to Django Submit a Bug Report a Security Issue Individual "
    "membership Get Help Getting Help FAQ Django Discord Official Django Forum "
    "Follow Us GitHub X Fediverse Bluesky LinkedIn News RSS Support Us"
)
DJANGO_NAV = (
    "Menu Main navigation Overview Download Documentation News Code Issues "
    "Community Foundation Donate Search Submit Toggle theme (current theme: auto)"
)
DJANGO_SKIP_LINK = (
    "Django Software Foundation | Django Skip to main content Django The web "
    "framework for perfectionists with deadlines."
)

# Also verbatim from that brief -- this one is a genuine, useful fact.
REAL_FACT = (
    "TicketCamp donated to the Django Software Foundation to support Django "
    "development."
)


@pytest.mark.parametrize(
    "label,text",
    [
        ("footer link run", DJANGO_FOOTER),
        ("navigation menu", DJANGO_NAV),
        ("skip link and title", DJANGO_SKIP_LINK),
        ("cookie notice", "We use cookies. Read our cookie policy for details here."),
        ("too short to be a claim", "Download Documentation News"),
        ("sign-in chrome", "Sign in to your account to continue to the dashboard."),
    ],
)
def test_site_chrome_is_never_offered_as_evidence(label: str, text: str) -> None:
    assert _is_boilerplate_passage(text), f"{label} reached the brief as a fact"


@pytest.mark.parametrize(
    "label,text",
    [
        ("donation fact", REAL_FACT),
        (
            "support prose",
            "Acme builds customer support automation for growing teams in India.",
        ),
        (
            "hiring fact",
            "We are hiring customer success managers to support our growing "
            "enterprise customer base this quarter.",
        ),
        (
            "funding fact",
            "The company raised a Series B funding round led by Accel to expand "
            "its go-to-market team.",
        ),
        (
            "mission statement",
            "Our non-profit foundation supports long-term development of the "
            "framework and its worldwide community of contributors.",
        ),
    ],
)
def test_real_claims_survive_the_gate(label: str, text: str) -> None:
    assert not _is_boilerplate_passage(text), f"{label} was wrongly discarded"


def test_usable_passages_filters_a_mixed_page() -> None:
    page = f"{DJANGO_NAV} {REAL_FACT} {DJANGO_FOOTER}"

    passages = _usable_passages(page)

    assert all(not _is_boilerplate_passage(item) for item in passages)
    assert not any("Main navigation" in item for item in passages)


# --------------------------------------------------------------- unknown vs zero


def test_absent_evidence_does_not_behave_like_a_mismatch() -> None:
    """The defect: a verified company scored Fit 0 for saying nothing about itself."""

    def fit(industry: float | None, geography: float | None) -> int:
        return score_account(
            industry_match=industry,
            size_match=None,
            geography_match=geography,
            signal_strength=0,
            signal_recency=None,
            evidence_coverage=80,
            source_quality=80,
            fit_evidence=["e"],
            signal_evidence=[],
        ).fit.score

    unknown_everything = fit(None, None)
    known_industry_only = fit(100.0, None)
    verified_mismatch = fit(0.0, 0.0)

    # Nothing known: no fit claim can be made either way.
    assert unknown_everything == 0
    # One known positive should not be diluted by two unknowns.
    assert known_industry_only == 100
    # A verified mismatch is still a real zero.
    assert verified_mismatch == 0


def test_a_single_known_positive_renormalises_across_unknowns() -> None:
    scores = score_account(
        industry_match=None,
        size_match=None,
        geography_match=80.0,
        signal_strength=0,
        signal_recency=None,
        evidence_coverage=50,
        source_quality=50,
        fit_evidence=["e"],
        signal_evidence=[],
    )

    assert scores.fit.score == 80
    assert [component.label for component in scores.fit.components] == [
        "Geography match"
    ]


# ------------------------------------------------------------ geography vocabulary


@pytest.mark.parametrize(
    "target_market,expected",
    [
        ("B2B SaaS companies in India", "bengaluru"),
        ("Mid-market teams across the United States", "san francisco"),
        ("European scale-ups", "berlin"),
        ("APAC enterprises", "singapore"),
        ("Companies in London and Manchester", "london"),
    ],
)
def test_geography_follows_the_founders_target_market(
    target_market: str, expected: str
) -> None:
    """Previously hardcoded to Indian cities, so every other market scored zero."""
    assert expected in _target_geography_terms(target_market)


def test_a_market_naming_no_geography_yields_no_terms() -> None:
    assert _target_geography_terms("Developer tooling companies") == ()
