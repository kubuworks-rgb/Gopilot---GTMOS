"""Regressions found by running BYOA against real company websites.

Both defects were invisible to the fixture-based suite and only surfaced when the
deployed stack fetched python.org and sqlalchemy.org for real.

1. The import-time "not yet verified" marker was never cleared once research
   verified the domain, so every imported account was pinned to
   IDENTITY_REVIEW_REQUIRED forever.
2. Identity verification was conflated with evidence extraction. A site whose copy
   carries almost no sentence punctuation yielded no passages, and the account was
   then reported as "the supplied official domain could not be verified" -- untrue,
   because the domain had been fetched and matched.
"""

from __future__ import annotations

from uuid import uuid4

from apps.api.app.db.models import AccountRow
from apps.api.app.services.entity_resolution import (
    IMPORT_PENDING_IDENTITY_WARNING,
    BriefState,
    decide_brief_state,
)
from apps.api.app.services.live_research import (
    _identity_record_for_account,
    _sentences,
)


def _account(
    domain: str, identity: dict[str, object], validation: str = "VALIDATED"
) -> AccountRow:
    return AccountRow(
        id=uuid4(),
        workspace_id=uuid4(),
        icp_id=None,
        icp_profile_id=uuid4(),
        name="Example",
        domain=domain,
        description=None,
        industry=None,
        location=None,
        employee_band=None,
        business_model=None,
        attributes={
            "company_identity": identity,
            "domain_confidence": 0.9,
            "domain_validation": validation,
        },
        evidence_ids=[],
    )


# ------------------------------------------------- pending marker is cleared


def test_verified_domain_clears_the_import_pending_marker() -> None:
    account = _account(
        "python.org",
        {
            "verified_official_domains": ["python.org"],
            "unresolved_identity_warnings": [IMPORT_PENDING_IDENTITY_WARNING],
        },
    )

    record = _identity_record_for_account(account)

    assert record.unresolved_identity_warnings == ()
    assert "python.org" in record.verified_official_domains


def test_an_unverified_domain_keeps_the_marker() -> None:
    account = _account(
        "python.org",
        {
            "verified_official_domains": [],
            "unresolved_identity_warnings": [IMPORT_PENDING_IDENTITY_WARNING],
        },
        validation="UNVERIFIED",
    )

    record = _identity_record_for_account(account)

    assert record.unresolved_identity_warnings == (IMPORT_PENDING_IDENTITY_WARNING,)


def test_a_freshly_imported_account_keeps_the_marker() -> None:
    """Import sets CANONICALIZED_UNVERIFIED; nothing has been fetched yet."""
    account = _account(
        "python.org",
        {
            "verified_official_domains": [],
            "unresolved_identity_warnings": [IMPORT_PENDING_IDENTITY_WARNING],
        },
        validation="CANONICALIZED_UNVERIFIED",
    )

    record = _identity_record_for_account(account)

    assert record.unresolved_identity_warnings == (IMPORT_PENDING_IDENTITY_WARNING,)


def test_genuine_warnings_survive_verification() -> None:
    """Only the pending marker is cleared; a real conflict must still block."""
    conflict = "Two different companies share this brand name."
    account = _account(
        "python.org",
        {
            "verified_official_domains": ["python.org"],
            "unresolved_identity_warnings": [
                IMPORT_PENDING_IDENTITY_WARNING,
                conflict,
            ],
        },
    )

    record = _identity_record_for_account(account)

    assert record.unresolved_identity_warnings == (conflict,)


def test_a_verified_account_is_no_longer_pinned_to_identity_review() -> None:
    """The end-to-end consequence: imported accounts can now reach other states."""
    account = _account(
        "python.org",
        {
            "verified_official_domains": ["python.org"],
            "unresolved_identity_warnings": [IMPORT_PENDING_IDENTITY_WARNING],
        },
    )
    record = _identity_record_for_account(account)

    state = decide_brief_state(
        identity_verified=True,
        unresolved_identity_warnings=record.unresolved_identity_warnings,
        qualification_status="QUALIFIED_WITH_UNCERTAINTY",
        has_supported_icp_fact=True,
        has_actionable_signal=False,
        supported_important_claims=True,
        direct_competitor_conflict=False,
    )

    assert state is BriefState.MONITOR


# ------------------------------------------- terse pages still yield passages


def test_a_page_without_sentence_punctuation_still_yields_a_passage() -> None:
    """sqlalchemy.org's homepage is one long run with almost no full stops."""
    text = "SQLAlchemy The Database Toolkit for Python " * 40

    passages = _sentences(text)

    assert passages, "a long unpunctuated body must not be discarded entirely"
    assert all(len(item) <= 700 for item in passages)


def test_clamping_breaks_on_a_word_boundary() -> None:
    text = "alpha bravo charlie delta echo foxtrot golf hotel india juliet " * 30

    passage = _sentences(text)[0]

    assert len(passage) <= 700
    assert not passage.endswith(" ")
    # Clamped at a space, so the final token is not sliced in half.
    assert passage.split()[-1] in {
        "alpha", "bravo", "charlie", "delta", "echo",
        "foxtrot", "golf", "hotel", "india", "juliet",
    }


def test_short_fragments_are_still_ignored() -> None:
    assert _sentences("Home. About. Contact.") == []


def test_normal_prose_is_unaffected() -> None:
    text = (
        "Acme builds customer support automation for growing teams. "
        "The company serves more than two hundred businesses across India."
    )

    passages = _sentences(text)

    assert len(passages) == 2
    assert passages[0].startswith("Acme builds")
