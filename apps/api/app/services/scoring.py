from __future__ import annotations

from datetime import UTC, datetime

from apps.api.app.domain.models import AccountScores, ScoreBreakdown, ScoreComponent


def _breakdown(items: list[tuple[str, float, float, list[str]]]) -> ScoreBreakdown:
    components = [
        ScoreComponent(
            label=label,
            value=value,
            weight=weight,
            contribution=round(value * weight, 2),
            evidence_ids=evidence_ids,
        )
        for label, value, weight, evidence_ids in items
    ]
    return ScoreBreakdown(
        score=round(sum(component.contribution for component in components)),
        components=components,
    )


def _breakdown_missing_aware(
    items: list[tuple[str, float | None, float, list[str]]],
) -> ScoreBreakdown:
    """Renormalize known factors; unknown is never treated as a negative."""

    known_weight = sum(weight for _, value, weight, _ in items if value is not None)
    if known_weight <= 0:
        return ScoreBreakdown(score=0, components=[])
    normalized = [
        (label, value, weight / known_weight, evidence_ids)
        for label, value, weight, evidence_ids in items
        if value is not None
    ]
    return _breakdown(normalized)  # type: ignore[arg-type]


def signal_decay(observed_at: datetime, half_life_days: int = 45) -> float:
    now = datetime.now(UTC)
    observed = observed_at if observed_at.tzinfo else observed_at.replace(tzinfo=UTC)
    age_days = max(0.0, (now - observed).total_seconds() / 86400)
    return round(0.5 ** (age_days / half_life_days), 4)


def score_account(
    *,
    industry_match: float | None,
    size_match: float | None,
    geography_match: float | None,
    signal_strength: float,
    signal_recency: float | None,
    evidence_coverage: float,
    source_quality: float,
    fit_evidence: list[str],
    signal_evidence: list[str],
    retrieval_coverage: float | None = None,
) -> AccountScores:
    fit = _breakdown_missing_aware(
        [
            ("Industry match", industry_match, 0.45, fit_evidence),
            ("Company size match", size_match, 0.35, fit_evidence),
            ("Geography match", geography_match, 0.20, fit_evidence),
        ]
    )
    # Recency is None when the supporting source carries no event date. Renormalizing
    # onto signal strength keeps unknown recency from being scored as either a fresh
    # event or a stale one; only a real event date can earn a recency contribution.
    intent = _breakdown_missing_aware(
        [
            ("Signal strength", signal_strength, 0.60, signal_evidence),
            ("Signal recency", signal_recency, 0.40, signal_evidence),
        ]
    )
    # Retrieval coverage is how much of what we tried to read we actually read. A
    # brief built from one page out of eight must not carry the same confidence as
    # one built from eight, and the founder must be able to see why in the
    # component breakdown. None means the run predates outcome tracking, in which
    # case the other two components renormalize rather than being penalised.
    confidence = _breakdown_missing_aware(
        [
            (
                "Evidence coverage",
                evidence_coverage,
                0.40,
                fit_evidence + signal_evidence,
            ),
            ("Source quality", source_quality, 0.35, fit_evidence + signal_evidence),
            ("Retrieval coverage", retrieval_coverage, 0.25, []),
        ]
    )
    priority = round((fit.score * 0.55 + intent.score * 0.45) * confidence.score / 100)
    return AccountScores(fit=fit, intent=intent, confidence=confidence, priority=priority)


def priority_band(
    scores: AccountScores,
    *,
    qualification_status: str,
    has_verified_signal: bool,
) -> tuple[str, str]:
    if qualification_status == "DISQUALIFIED":
        return "LOW", "Do not target; retain only for QA and feedback."
    if (
        scores.priority >= 70
        and has_verified_signal
        and qualification_status == "QUALIFIED"
    ):
        return "HIGH", "Human review for timely, evidence-led outreach."
    if scores.priority >= 45 and qualification_status in {
        "QUALIFIED",
        "QUALIFIED_WITH_UNCERTAINTY",
    }:
        return "MEDIUM", "Resolve named evidence gaps before outreach."
    if qualification_status == "QUALIFIED_WITH_UNCERTAINTY":
        return "MONITOR", "Research candidate; verify unknown hard criteria."
    return "MONITOR", "Monitor or nurture; no verified current trigger."
