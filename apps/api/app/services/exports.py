"""Safe CSV export (blueprint section 19).

One definition shared by both routers. They previously kept separate copies of the
column list and row construction, and had already drifted apart.

An export leaves the product and lands in a spreadsheet someone forwards, so every
column here is a product-level fact: no internal identifiers, no provider payloads,
no credentials. `test_safe_export.py` asserts that against the column names.
"""

from __future__ import annotations

from apps.api.app.domain.models import Account, AccountOpportunityBrief, ScoreBreakdown
from apps.api.app.services.byoa import neutralize_formula


# `state` and `domain` use the blueprint's founder-facing names rather than the
# internal `brief_state` / `canonical_domain`.
EXPORT_COLUMNS: list[str] = [
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
    "identity_status",
    "qualification_status",
    "import_source",
]


def csv_safe(value: object) -> str:
    """Neutralise spreadsheet formula prefixes without altering readable text."""
    return neutralize_formula(value)


def export_row(
    account: Account, brief: AccountOpportunityBrief | None
) -> list[object]:
    """Build one export row. Order must match EXPORT_COLUMNS."""

    primary_evidence_url = (
        str(brief.sources[0].canonical_url)
        if brief is not None and brief.sources
        else ""
    )
    def score_or_not_determined(breakdown: ScoreBreakdown) -> object:
        return breakdown.score if breakdown.determined else "Not determined"

    return [
        csv_safe(account.name),
        csv_safe(account.domain),
        csv_safe(account.brief_state),
        score_or_not_determined(account.scores.fit),
        score_or_not_determined(account.scores.intent),
        score_or_not_determined(account.scores.confidence),
        account.scores.priority,
        csv_safe(account.recommended_action),
        csv_safe(primary_evidence_url),
        csv_safe(" | ".join(brief.unknowns) if brief is not None else ""),
        csv_safe(account.owner or ""),
        csv_safe(account.review_status.value),
        csv_safe(account.domain_validation),
        csv_safe(account.qualification_status.value),
        csv_safe(account.import_source.value if account.import_source else ""),
    ]
