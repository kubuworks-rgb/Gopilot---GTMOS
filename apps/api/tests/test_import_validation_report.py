"""Import validation must account for every submitted row (blueprint section 8).

The founder inspects duplicates, invalid domains and identity doubts *before*
research starts, so no row may be silently dropped between upload and research.
"""

from __future__ import annotations

import pytest

from apps.api.app.domain.models import (
    AccountImportPayload,
    AccountImportSource,
    ImportRowVerdict,
)
from apps.api.app.services.byoa import validate_account_import


def _csv(text: str):
    return validate_account_import(
        AccountImportPayload(csv_text=text, import_source=AccountImportSource.CSV_UPLOAD)
    )


def test_every_submitted_row_appears_in_the_report() -> None:
    """The core guarantee: rows in equals rows accounted for."""
    validation = _csv(
        "company_name,domain\n"
        "Acme,acme.com\n"
        "Acme Again,www.acme.com\n"
        "Broken,company.local\n"
        "Globex,globex.com\n"
    )

    assert validation.summary.total == 4
    assert [item.row for item in validation.rows] == [2, 3, 4, 5]
    assert (
        validation.summary.valid
        + validation.summary.duplicate
        + validation.summary.invalid
        + validation.summary.needs_review
        == validation.summary.total
    )


def test_the_blueprint_example_breakdown() -> None:
    """Section 8: valid / duplicate / invalid / requires review, each distinct."""
    validation = _csv(
        "company_name,domain\n"
        "Freshworks,freshworks.com\n"
        "Freshworks,https://www.freshworks.com/\n"
        "Local Thing,company.local\n"
        "Acme AI,example-company.ai\n"
    )

    assert validation.summary.valid == 1
    assert validation.summary.duplicate == 1
    assert validation.summary.invalid == 1
    assert validation.summary.needs_review == 1


def test_a_duplicate_reports_the_canonical_domain_that_collided() -> None:
    validation = _csv(
        "company_name,domain\nFreshworks,freshworks.com\nFresh,www.freshworks.com\n"
    )

    duplicate = next(
        item for item in validation.rows if item.verdict is ImportRowVerdict.DUPLICATE
    )
    assert duplicate.canonical_domain == "freshworks.com"
    assert "already appears" in (duplicate.reason or "")


def test_canonicalisation_is_visible_to_the_user() -> None:
    validation = _csv("company_name,domain\nFreshworks,https://www.freshworks.com/\n")

    row = validation.rows[0]
    assert row.submitted_domain == "https://www.freshworks.com/"
    assert row.canonical_domain == "freshworks.com"
    assert row.canonicalised is True


def test_an_invalid_row_carries_the_reason_not_just_a_code() -> None:
    validation = _csv("company_name,domain\nLocal Thing,company.local\n")

    row = validation.rows[0]
    assert row.verdict is ImportRowVerdict.INVALID
    assert row.code == "PRIVATE_DESTINATION"
    assert row.reason


# ------------------------------------------------------------- needs-review rule


@pytest.mark.parametrize(
    "name,domain",
    [
        ("Acme AI", "example-company.ai"),
        ("Globex Corporation", "initech.com"),
    ],
)
def test_name_and_domain_with_nothing_in_common_are_flagged(
    name: str, domain: str
) -> None:
    validation = _csv(f"company_name,domain\n{name},{domain}\n")

    row = validation.rows[0]
    assert row.verdict is ImportRowVerdict.NEEDS_REVIEW
    assert row.code == "POSSIBLE_IDENTITY_MISMATCH"


@pytest.mark.parametrize(
    "name,domain",
    [
        ("Freshworks", "freshworks.com"),
        ("Freshworks Inc", "freshworks.com"),
        ("BrowserStack", "browserstack.com"),
        ("Zoho Corporation", "zoho.com"),
        # Legal and descriptive noise must not trigger a false flag.
        ("Acme Technologies Private Limited", "acme.com"),
    ],
)
def test_a_matching_name_and_domain_are_not_flagged(name: str, domain: str) -> None:
    validation = _csv(f"company_name,domain\n{name},{domain}\n")

    assert validation.rows[0].verdict is ImportRowVerdict.VALID


def test_a_flagged_row_is_still_importable() -> None:
    """Review is a caution, not a rejection -- the user decides."""
    validation = _csv("company_name,domain\nAcme AI,example-company.ai\n")

    assert validation.summary.needs_review == 1
    assert [item.domain for item in validation.accepted] == ["example-company.ai"]


def test_pasted_domains_without_names_are_not_flagged_for_review() -> None:
    """A pasted bare domain has no name to contradict, so there is nothing to doubt."""
    validation = validate_account_import(
        AccountImportPayload(
            pasted_domains="acme.com\nglobex.com",
            import_source=AccountImportSource.PASTED_DOMAINS,
        )
    )

    assert validation.summary.needs_review == 0
    assert validation.summary.valid == 2
