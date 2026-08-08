# Prequalification Recall Baseline

Status: immutable development baseline

Source run: `37355f0a-d439-4c38-ae8d-837c25dd8974`

Evidence status: verified from the preserved `research_candidates` rows and the
independent first-30 review completed on 2026-07-25.

This document preserves the failed SupportPilot V2 holdout. It is a calibration
baseline, not a fresh holdout, and must not be reinterpreted as post-change
evidence.

## Funnel

| Stage | Count |
|---|---:|
| Raw candidates | 60 |
| Prequalified | 1 |
| Deep researched | 1 |
| Qualified | 0 |
| Founder-usable | 0 |

The only prequalified candidate was BizBMS. Account-level research subsequently
disqualified it, leaving no founder-usable account.

## First-30 manual QA

| Finding | Count |
|---|---:|
| Confirmed real company/product sites | 27 |
| Uncertain | 3 |
| Potentially useful raw candidates | approximately 25 |
| Apparently correct canonical domains | 30 |
| Duplicate domains | 0 |
| Proven fake entities | 0 |

`USEFUL_RAW_CANDIDATE` means worth a bounded official-site research budget. It
does not mean that final ICP qualification, intent, employee size, or buyer value
has already been proven.

## Preserved score distribution

| Old score | Count | Old outcome |
|---:|---:|---|
| 46 | 1 | Accepted |
| 36 | 4 | Rejected at prequalification |
| 33 | 11 | Rejected at prequalification |
| 31 | 19 | Rejected at prequalification |
| 28 | 19 | Rejected at prequalification |
| 25 | 6 | Rejected at prequalification |

All 60 rows had an official-root or official-subdomain page role, identity
confidence of at least `0.80`, one authenticated Exa provider, and no persisted
provider relevance score. Fifty-nine candidates were rejected by the single
45-point threshold before official-site research.

## Baseline conclusion

The baseline failure is excessive false negatives in prequalification. It is not
evidence that final qualification should be weakened. Final ICP, evidence,
signal, deterministic scoring, and Opportunity Brief standards remain unchanged.
