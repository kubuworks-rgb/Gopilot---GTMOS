"""The executive summary may only restate what the brief already proves.

Blueprint section 16.1 asks for two or three sentences. Composing them
deterministically from counted, verified inputs means the summary cannot introduce
a claim the rest of the document does not support -- which section 11.8 requires of
the brief composer regardless of how it is implemented.
"""

from __future__ import annotations

import pytest

from apps.api.app.services.live_research import compose_executive_summary


def _summary(**overrides: object) -> str:
    base: dict[str, object] = {
        "company_name": "Acme",
        "brief_state": "RESEARCH_CANDIDATE",
        "verified_fact_count": 3,
        "unknown_count": 2,
        "has_signal": False,
        "priority": 41,
    }
    base.update(overrides)
    return compose_executive_summary(**base)  # type: ignore[arg-type]


def test_it_names_the_company_and_its_state() -> None:
    assert _summary().startswith("Acme is a research candidate.")


@pytest.mark.parametrize(
    "state,fragment",
    [
        ("FOUNDER_READY", "ready for founder review"),
        ("RESEARCH_CANDIDATE", "research candidate"),
        ("MONITOR", "monitoring rather than approaching now"),
        ("IDENTITY_REVIEW_REQUIRED", "needs identity review"),
        ("DO_NOT_TARGET", "should not be targeted"),
    ],
)
def test_every_account_state_reads_as_a_recommendation(
    state: str, fragment: str
) -> None:
    assert fragment in _summary(brief_state=state)


def test_an_unrecognised_state_still_produces_a_sentence() -> None:
    assert "Acme has been researched." in _summary(brief_state="SOMETHING_NEW")


def test_it_reports_both_what_is_known_and_what_is_not() -> None:
    summary = _summary(verified_fact_count=3, unknown_count=2)

    assert "verified 3 facts" in summary
    assert "left 2 criteria unresolved" in summary


def test_singulars_read_correctly() -> None:
    summary = _summary(verified_fact_count=1, unknown_count=1)

    assert "verified 1 fact " in summary
    assert "1 criterion unresolved" in summary


def test_no_unknowns_is_stated_positively() -> None:
    assert "no unresolved criteria" in _summary(unknown_count=0)


def test_no_evidence_is_admitted_rather_than_glossed() -> None:
    summary = _summary(verified_fact_count=0, unknown_count=0)

    assert "No official evidence has been collected yet." in summary


def test_no_facts_but_open_questions_is_stated_honestly() -> None:
    assert "No fact could be verified yet" in _summary(
        verified_fact_count=0, unknown_count=4
    )


def test_absence_of_a_signal_is_stated_not_hidden() -> None:
    """Blueprint section 20: no-signal is a good result, not something to obscure."""
    summary = _summary(has_signal=False, priority=24)

    assert "No current supported signal was found" in summary
    assert "priority stands at 24" in summary


def test_a_signal_is_reported_as_a_reason_to_act() -> None:
    summary = _summary(has_signal=True, priority=82)

    assert "reason to act now" in summary
    assert "priority is 82" in summary


def test_it_stays_to_three_sentences() -> None:
    """Section 16.1 asks for two or three, not an essay."""
    for state in ("FOUNDER_READY", "MONITOR", "DO_NOT_TARGET"):
        for signal in (True, False):
            summary = _summary(brief_state=state, has_signal=signal)
            assert summary.count(". ") + summary.count(".") - summary.count(". ") <= 3
            assert len([part for part in summary.split(". ") if part]) <= 3


def test_it_is_deterministic() -> None:
    assert _summary() == _summary()
