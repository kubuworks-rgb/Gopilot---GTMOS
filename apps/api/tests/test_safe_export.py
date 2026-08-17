"""Export must carry product facts and nothing else (blueprint section 19).

The export leaves GoPilot and lands in a spreadsheet someone forwards. Two things
must hold: it contains the fields the blueprint promises, and it can never carry an
internal identifier, a provider payload or a credential.
"""

from __future__ import annotations

import csv
import io

import pytest

from apps.api.app.services.exports import EXPORT_COLUMNS, csv_safe as _csv_safe


BLUEPRINT_FIELDS = {
    "company_name",
    "domain",
    "state",
    "fit_score",
    "intent_score",
    "confidence_score",
    "priority_score",
    "recommended_action",
    "primary_evidence_url",
    "unknowns",
    "owner",
    "review_status",
}

# Anything resembling an internal handle, a provider payload or a secret. Matched
# as substrings against every column name.
FORBIDDEN_FRAGMENTS = (
    "_id",
    "uuid",
    "token",
    "key",
    "secret",
    "password",
    "credential",
    "authorization",
    "bearer",
    "provider",
    "payload",
    "raw_",
    "internal",
    "workspace",
    "trace",
    "cookie",
    "session",
    "prompt",
    "embedding",
    "chunk",
    "storage",
)


def test_every_blueprint_field_is_exported() -> None:
    missing = BLUEPRINT_FIELDS - set(EXPORT_COLUMNS)

    assert missing == set(), f"blueprint fields absent from the export: {missing}"


def test_owner_is_exported() -> None:
    """Called out separately: it was missing entirely until this was written."""
    assert "owner" in EXPORT_COLUMNS


@pytest.mark.parametrize("column", EXPORT_COLUMNS)
def test_no_column_looks_like_an_internal_field(column: str) -> None:
    offending = [
        fragment for fragment in FORBIDDEN_FRAGMENTS if fragment in column.lower()
    ]

    assert offending == [], (
        f"export column {column!r} resembles internal data ({offending}). "
        "Exports are forwarded outside the product."
    )


def test_columns_are_unique_and_stable() -> None:
    assert len(EXPORT_COLUMNS) == len(set(EXPORT_COLUMNS))
    assert EXPORT_COLUMNS[0] == "company_name", "the first column identifies the row"


# ------------------------------------------------------------- spreadsheet safety


@pytest.mark.parametrize(
    "payload",
    [
        "=HYPERLINK(\"http://evil.example\",\"click\")",
        "+1+1",
        "-1+1",
        "@SUM(A1:A9)",
        "\tinjected",
        "\rinjected",
    ],
)
def test_formula_payloads_are_neutralised(payload: str) -> None:
    safe = _csv_safe(payload)

    assert safe.startswith("'"), f"{payload!r} would execute in a spreadsheet"
    assert payload in safe, "the original text must still be readable"


def test_ordinary_values_are_untouched() -> None:
    assert _csv_safe("Acme Software") == "Acme Software"
    assert _csv_safe("acme.com") == "acme.com"
    assert _csv_safe(None) == ""
    assert _csv_safe(42) == "42"


def test_a_neutralised_row_round_trips_through_csv() -> None:
    """Neutralisation must not corrupt the file for a legitimate reader."""
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(EXPORT_COLUMNS)
    writer.writerow(
        [_csv_safe("=cmd|'/c calc'!A1")] + [""] * (len(EXPORT_COLUMNS) - 1)
    )

    rows = list(csv.reader(io.StringIO(output.getvalue())))

    assert rows[0] == EXPORT_COLUMNS
    assert rows[1][0].startswith("'")
    assert len(rows[1]) == len(EXPORT_COLUMNS)
