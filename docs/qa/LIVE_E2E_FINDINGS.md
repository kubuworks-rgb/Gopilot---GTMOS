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

## 2. P0 — Unknown fit is scored as zero, and it changes the ranking

**This is the one finding that should block a claim of "ready".** It is not a
crash and no test catches it; the system produces a confident, wrong number.

### What happens

`_breakdown_missing_aware` ([scoring.py:25](../../apps/api/app/services/scoring.py:25))
exists precisely so that an unknown criterion is never treated as a negative one.
It drops unknown components and renormalises the remaining weights. But when
*every* component of a dimension is unknown, it falls through to:

```python
if known_weight <= 0:
    return ScoreBreakdown(score=0, components=[])
```

A score of **0 with an empty component list**. That is the same defect the
function was written to prevent, one level up: unknown has become zero for the
whole dimension.

### Observed on the live run

| Account | Fit | Components | What 0 actually means |
|---|---|---|---|
| `supabase.com` | 50 | `Industry match 50` | evaluated |
| `neon.tech` | 0 | `Industry match 0`, `Geography match 0` | **evaluated, genuinely 0** |
| `fly.io` | 0 | *(none)* | **not determined** |
| `render.com` | 0 | *(none)* | **not determined** |

`neon.tech` and `fly.io` both render as "Fit 0". One is a verdict; the other is
an absence of a verdict. Nothing in the API response or the UI distinguishes
them.

### Why it matters beyond display

Priority is computed from the zero:

```python
priority = round((fit.score * 0.55 + intent.score * 0.45) * confidence.score / 100)
```

For `fly.io` — intent 70, confidence 91, fit *unknown*:

- As shipped: `(0×0.55 + 70×0.45) × 0.91` = **29**
- Renormalised as the design intends (intent carries the full weight when fit is
  unknown): `70 × 0.91` = **64**

The account is ranked **less than half as urgent as its own evidence supports**,
and 29 vs 64 is the difference between "below the fold" and "top of the list".
The founder never learns that fit was never determined; they see a low number and
move on.

This also silently interacts with the new §14 score filters: a "Fit 60+" filter
hides every account whose fit could not be determined, presenting them as
positively poor-fit.

### Why this is reported rather than patched

Fixing it properly means a dimension score has to be able to say "not
determined", which is a `float | None` through the domain model, the API schema,
the web types, the accounts table, sorting, the new filters, and the CSV export —
plus a product decision on what priority should even mean when a dimension is
missing (renormalise onto the remaining dimensions, or refuse to rank at all).
That is a design change, not a repair, so it is on the table rather than in the
code.

**Recommendation:** renormalise priority across known dimensions the same way
components are renormalised within one, and render an undetermined dimension as
"Not determined" rather than 0.

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

The P0 in §2 reproduced identically across both runs: `fly.io` and `render.com`
returned fit 0 with an empty component list each time.
