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
    """Renormalize known factors; unknown is never treated as a negative.

    When every factor is unknown there is nothing left to renormalize onto, so
    the dimension itself is undetermined rather than a confident zero -- the
    same principle this function already applies to a single missing factor,
    one level up. A live run against 20 real companies found exactly this case
    (fly.io, render.com) silently ranking below accounts with genuinely poor
    fit; see docs/qa/LIVE_E2E_FINDINGS.md.
    """

    known_weight = sum(weight for _, value, weight, _ in items if value is not None)
    if known_weight <= 0:
        return ScoreBreakdown(score=0, components=[], determined=False)
    normalized = [
        (label, value, weight / known_weight, evidence_ids)
        for label, value, weight, evidence_ids in items
        if value is not None
    ]
    return _breakdown(normalized)  # type: ignore[arg-type]


def _priority_from(
    fit: ScoreBreakdown, intent: ScoreBreakdown, confidence: ScoreBreakdown
) -> int:
    """Compose priority the same missing-aware way its inputs are composed.

    fit and intent are weighted terms exactly like the factors inside one
    breakdown, so an undetermined one is excluded and the other's weight is
    renormalized to compensate -- not multiplied by a phantom 0. confidence is
    a damping multiplier rather than a weighted term; if it were ever
    undetermined too, treating it as "no penalty" (1.0) keeps an absence of
    evidence from acting as the strongest possible negative signal, consistent
    with why the weighted terms are renormalized instead of zeroed.
    """

    weighted = [(fit.score, 0.55, fit.determined), (intent.score, 0.45, intent.determined)]
    known_weight = sum(weight for _, weight, determined in weighted if determined)
    if known_weight <= 0:
        return 0  # both dimensions undetermined: nothing to rank on
    composite = sum(
        score * (weight / known_weight)
        for score, weight, determined in weighted
        if determined
    )
    confidence_factor = confidence.score / 100 if confidence.determined else 1.0
    return round(composite * confidence_factor)


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
    priority = _priority_from(fit, intent, confidence)
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
