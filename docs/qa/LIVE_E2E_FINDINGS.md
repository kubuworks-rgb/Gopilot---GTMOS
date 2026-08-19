# GoPilot — Live End-to-End Findings (Blueprint §40)

**Date:** 2026-08-13
**Branch:** `feature/private-alpha-hardening`
**Stack:** real Postgres (pgvector pg17), real Redis, real worker consuming the
queue, research gateway making real HTTP requests to real company websites.
`EXA_API_KEY` and `TAVILY_API_KEY` deliberately empty.
**Driver:** `scripts/verify_e2e_scenario.py`

The scenario was walked with 20 real companies (Zerodha, Freshworks, Postman,
Razorpay, Chargebee, BrowserStack, Hasura, Zoho, Atlassian, Basecamp, Linear,
Vercel, Supabase, PlanetScale, Render, Fly.io, Neon, Clerk), one deliberate
duplicate, and one private-network address.

---

## 1. The headline: BYOA works without a paid research provider

This was the specific claim under test, and it holds. With no search provider
configured, the supplied-account workflow completed end to end: 18 accounts
imported, 6 researched against their real websites, evidence extracted and
attributed, scores computed, briefs generated, statuses changed, list exported.

`/product-modes` reports `search_provider_configured: false` throughout.

---

## 2. P0 — Unknown fit was scored as zero, and it changed the ranking (FIXED)

**Status: fixed.** This was the one finding that blocked a claim of "ready". It
was not a crash and no test caught it; the system produced a confident, wrong
number. It is now pinned by a regression test built from this exact case.

### What was happening

`_breakdown_missing_aware` ([scoring.py:25](../../apps/api/app/services/scoring.py#L25))
exists precisely so that an unknown criterion is never treated as a negative one.
It drops unknown components and renormalises the remaining weights. But when
*every* component of a dimension was unknown, it fell through to:

```python
if known_weight <= 0:
    return ScoreBreakdown(score=0, components=[])
```

A score of **0 with an empty component list**. That was the same defect the
function was written to prevent, one level up: unknown had become zero for the
whole dimension.

### Observed on the live run

| Account | Fit | Components | What 0 actually meant |
|---|---|---|---|
| `supabase.com` | 50 | `Industry match 50` | evaluated |
| `neon.tech` | 0 | `Industry match 0`, `Geography match 0` | **evaluated, genuinely 0** |
| `fly.io` | 0 | *(none)* | **not determined** |
| `render.com` | 0 | *(none)* | **not determined** |

`neon.tech` and `fly.io` both rendered as "Fit 0". One was a verdict; the other
was an absence of a verdict. Nothing in the API response or the UI distinguished
them.

### Why it mattered beyond display

Priority was computed from the zero:

```python
priority = round((fit.score * 0.55 + intent.score * 0.45) * confidence.score / 100)
```

For `fly.io` — intent 70, confidence 91, fit *unknown*:

- As shipped: `(0×0.55 + 70×0.45) × 0.91` = **29**
- Renormalised as the design intends (intent carries the full weight when fit is
  unknown): `70 × 0.91` = **64**

The account was ranked **less than half as urgent as its own evidence
supported**, and 29 vs 64 is the difference between "below the fold" and "top of
the list". The founder never learned that fit was never determined; they saw a
low number and moved on.

### The fix

`ScoreBreakdown` gained a `determined: bool` field
([models.py:244](../../apps/api/app/domain/models.py#L244)), `False` only when
every factor in a dimension was unknown. `_breakdown_missing_aware` sets it
rather than silently returning a confident 0
([scoring.py:25](../../apps/api/app/services/scoring.py#L25)), and a new
`_priority_from` composes priority the same missing-aware way its own
components are composed: an undetermined dimension is excluded from the
weighted sum and the other's weight is renormalised to compensate, instead of
multiplying by a phantom 0
([scoring.py:49](../../apps/api/app/services/scoring.py#L49)). The UI, account
table, and CSV export now render "Not determined" instead of a bare `0` for an
undetermined dimension ([score.tsx](../../apps/web/components/score.tsx),
[exports.py](../../apps/api/app/services/exports.py)) — this was never about
hiding that it's missing, only about not letting the absence act as a negative
signal in the math.

`apps/api/tests/test_security_and_scoring.py` pins this with a fixture built
from the exact fly.io numbers above (`test_a_fully_unknown_fit_is_excluded_rather_than_scored_zero`,
expects priority 64, not 29) plus a unit-level check on `_priority_from` in
isolation. Both were confirmed to fail against the reverted code before the fix
was restored.

**Live re-verification (re-running `scripts/verify_e2e_scenario.py` against the
same real stack, same fly.io account): see the "Live scoring-fix re-verification"
addendum below.**

This also affected the §14 score filters: a "Fit 60+" filter hid every account
whose fit could not be determined, presenting them as positively poor-fit rather
than as unevaluated. That specific interaction is not yet addressed — a filter
floor still excludes an undetermined account rather than treating it as its own
category — and is a smaller residual worth a follow-up, not a re-opening of this
P0.

---

## 3. Founder-experience flags (§35)

These pass technically. They would still confuse the person using the product.

### 3.1 "Intent 70, Fit 0" is not explained

`fly.io` shows strong intent against zero fit. Even once §2 is fixed, the honest
reading — *"something is happening here, but we could not establish whether they
are your kind of company"* — is never said. The founder is left to reconcile two
numbers that appear to contradict each other.

### 3.2 95% confidence on an empty verdict

`render.com`: fit 0, intent 0, **confidence 95**. Confidence measures evidence
coverage, source quality and retrieval coverage — how well the site was read, not
how strong the opportunity is. So 95% is technically "we read this site
thoroughly". It reads as "we are 95% sure about this account".

The executive summary partly rescues it — *"No current supported signal was
found, so priority stands at 0"* — but the number next to it still says 95.

**Recommendation:** label it "Evidence confidence" wherever it appears next to
fit and intent, or state the sentence the number actually supports.

### 3.3 One ICP, generically named

The BYOA run proposed exactly one ICP, named *"Imported account target"*, and it
carries no `qualification_logic`. It works, but a founder who was promised an ICP
they can inspect and argue with gets a label.

---

## 4. What is genuinely good

Worth recording, because it was verified rather than assumed.

- **Import validation is strict and specific.** `192.168.1.10` → `IP_DESTINATION`;
  `localhost` → `PRIVATE_DESTINATION`; `169.254.169.254` (cloud metadata) →
  `IP_DESTINATION`; malformed input → `NON_PUBLIC_DOMAIN`; the duplicate was
  caught before any write. 18 of 20 accepted, and each rejection names its reason.
- **Identity checking works on real names.** `"Good Co"` submitted against
  `supabase.com` returned `POSSIBLE_IDENTITY_MISMATCH` — *"shares no name token
  with supabase.com"*.
- **Retrieval is honest.** `supabase.com` reports 4 of 8 pages read, with
  `/about` marked `NOT_FOUND (HTTP 404)` and excluded from the coverage
  denominator rather than counted as failure.
- **Unknowns are listed, not hidden.** Five for `supabase.com`, including
  *"Employee count remains unknown; it is not treated as false."*
- **FOUNDER_READY cannot be granted by hand** — a direct PATCH returns 409.
- **No autonomous outreach.** 32 audit events, no send.
- **Export is safe.** No cell begins `=`, `+`, `-` or `@`.
- **Confidence varies with evidence** (0, 91, 95 across six accounts) rather than
  being the constant it once was.

---

## 5. Scenario result

```
PASS 31   FAIL 0   FLAGS 2
```

Three FAILs appeared across earlier runs. **All three were defects in the driver,
not the product**, and are recorded here so the corrections are not mistaken for
the product having changed:

1. Asserted `source_url` on `EvidenceFact`, which carries `source_id` and resolves
   through the brief's `sources` list. Replaced with a check that the join
   resolves, which is the stronger assertion.
2. Read `/accounts/{id}`, which does not exist. The brief is at
   `/accounts/{id}/opportunity-brief`.
3. Searched issue text for `"192.168"` / `"PRIVATE"` when the code returned was
   `IP_DESTINATION`.

### Run-to-run variance is real, and correct

Between two runs of the same six accounts, confidence moved: `fly.io` 91 → 83,
`render.com` 95 → 83, `planetscale.com` 95 → 85. Fit, intent and state did not
move.

That is the right behaviour. Confidence is driven by retrieval coverage, and the
open web genuinely served a different number of pages on the second pass. A
confidence score that did *not* move under those conditions would be the
suspicious one.

The P0 in §2 (now fixed) reproduced identically across both runs: `fly.io` and
`render.com` returned fit 0 with an empty component list each time.

---

## 6. Live scoring-fix re-verification

**Date:** 2026-08-15. Same driver, same standard, fresh real stack: Postgres and
Redis brought up from `deploy/docker-compose.dev-infra.yml`, migrations applied
from empty, gateway/API/worker/OIDC issuer running live, no `EXA_API_KEY` or
`TAVILY_API_KEY`. `scripts/verify_e2e_scenario.py` walked the full scenario
again end to end: **PASS 31, FAIL 0** (identical to the original run).

`fly.io` reproduced the fully-unknown-fit case again on this run —
`F 0 I 70 C 95`, an empty fit component list — and the fix held:

- **Priority as shown: 66.** `round(70 × 0.95) = 66` — intent carries the full
  weight because fit is excluded and renormalized, not multiplied by 0.
- **What the old formula would have produced on this same run:**
  `round((0×0.55 + 70×0.45) × 0.95) = round(29.925) = 30`.

This run's confidence (95) differs from the original run's (91) — retrieval
coverage varies run to run against the live web, which is expected and already
documented in §5 — so the absolute before/after numbers differ from the
originally reported 29 → 64. The mechanism is the same and the direction and
magnitude of the correction are consistent: fit being undetermined no longer
costs the account more than half its priority.

`render.com` also reproduced its fully-unknown case (`F 0 I 0 C 95`, both
weighted dimensions undetermined) and correctly scored **priority 0** — there is
nothing to renormalize onto when both fit and intent are undetermined, which is
the documented fallback in `_priority_from`, not a bug.

The two founder-experience flags from §3 (fit/intent contradiction not
explained; confidence read as a verdict) are unchanged by this fix and remain
open — they are about explanation, not about the math being wrong.
