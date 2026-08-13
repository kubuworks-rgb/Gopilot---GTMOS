# GoPilot — Billing Scope

**Date:** 2026-08-13
**Status:** Scoping only. No billing code exists and none is to be written yet.
**Evidence:** measurements from the live §40 run (see
[LIVE_E2E_FINDINGS.md](../qa/LIVE_E2E_FINDINGS.md)), not estimates.

---

## 1. Where the cost actually sits

Measured on the live run — real Postgres, real worker, real fetches against real
company sites, no paid research provider.

| Per researched account | Measured |
|---|---|
| Outbound HTTP fetches attempted | **8** |
| Pages actually read | 3–5 (404s and refusals are normal) |
| Source documents stored | ~2.8 |
| Source chunks stored | ~13 |
| Evidence facts extracted | ~4.5 |
| Cleaned text retained | ~13 kB |
| Wall-clock | ~15–20 s, dominated by polite fetch pacing |

Whole scenario workspace: 18 accounts imported, 6 researched → 17 documents, 79
chunks, 27 facts, 76 kB text.

**The dominant cost is outbound fetching, not inference.** Scoring is
deterministic and uses no LLM at all, so the marginal cost of an account is
bandwidth, gateway time, rate-limit exposure against third-party sites, and the
storage that retention keeps for 180 days.

This matters commercially: cost scales with **how many companies were researched**
and almost nothing else. Importing 500 accounts and researching none costs
essentially nothing. Researching 50 costs 400 fetches.

---

## 2. The metered unit

**Accounts researched per month.** Confirmed by the measurements above: it is
directly proportional to the dominant cost and it is the unit a founder already
thinks in.

Counting rules, and why each follows from the cost data:

| Action | Counts? | Why |
|---|---|---|
| First research of an account | **Yes** | 8 fetches |
| Re-research of the same account | **Yes** | repeats all 8 fetches |
| `regenerate_brief` | **No** | recomposes stored evidence; zero fetches |
| Reading an account or brief | **No** | zero fetches |
| Exporting | **No** | zero fetches |
| Importing without researching | **No** | validation only |

**Never meter signals, facts, or evidence items.** The measured spread is 0–9
facts per account, driven by what the site happened to say. Charging per fact
would pay the system to inflate its own output — the one incentive an
evidence-backed product must not create. It would also punish a founder for
researching a company with a thin website, which is information, not a failure.

---

## 3. Plan tiers

Positioning assumption from earlier research: undercut Clay's ~$150/mo entry
point. Three tiers, priced on the meter above.

| | **Solo** | **Founder** | **Team** |
|---|---|---|---|
| Price | **$0** | **$79/mo** | **$199/mo** |
| Accounts researched / month | 25 | 300 | 1,000 |
| Seats | 1 | 3 | 10 |
| Workspaces | 1 | 3 | 10 |
| Retention | 30 days | 180 days | 180 days |
| Export | CSV | CSV | CSV + API |

Reasoning:

- **Solo at $0/25 accounts** is the trial. 25 is enough to research a real
  prospect list and judge whether the evidence is worth paying for; the honest
  product only proves itself on real companies.
- **Founder at $79** sits roughly half of Clay's entry point. At 300 accounts
  that is ~2,400 fetches/month — comfortably servable on one host.
- **Team at $199** is still below Clay's entry while adding seats, which is where
  multi-person GTM teams actually feel the constraint.

Seats are a limit, not a per-seat price. Per-seat pricing on a three-person
founding team is a tax on collaboration, and the cost data says seats are nearly
free — a seat that never triggers research costs nothing.

---

## 4. Enforcement call sites

These exist today and already return structured refusals. Billing enforcement
belongs at the same points, not in new middleware.

**The meter increments here — and nowhere else:**

- [`live_routes.py:682`](../../apps/api/app/api/live_routes.py:682)
  `research_account` — the only path that queues per-account fetching.
- [`live_routes.py:275`](../../apps/api/app/api/live_routes.py:275)
  `create_research` — the product/ICP run. Fetches the founder's *own* site, so
  it should be excluded from the customer's meter.

**Explicitly not metered:**

- [`live_routes.py:763`](../../apps/api/app/api/live_routes.py:763) `regenerate_brief`
- [`live_routes.py:897`](../../apps/api/app/api/live_routes.py:897) `export_accounts`
- [`live_routes.py:608`](../../apps/api/app/api/live_routes.py:608) `import_accounts`

**The limit-check pattern to reuse**, in
[`private_alpha.py`](../../apps/api/app/services/private_alpha.py):
`assert_import_size` (109), `assert_workspace_capacity` (123),
`assert_daily_import_quota` (151), `assert_run_concurrency` (180),
`assert_workspace_quota` (208), `assert_export_size` (232).

Each raises `LimitExceeded`, which carries `code`, `message`, `limit` and
`attempted`, and surfaces as **429** with a machine-readable body. A billing limit
should raise the same shape with `code: "PLAN_LIMIT_REACHED"` rather than
inventing a second refusal vocabulary.

Note the ordering already established at
[`live_routes.py:620`](../../apps/api/app/api/live_routes.py:620): limits are
checked *before* anything is written, so a refused request leaves no partial
state. A metered check must keep that property — increment only after the job is
successfully queued, or a failed enqueue bills for work never done.

### Where subscription state lives

Workspace-level, not user-level: the workspace already owns accounts, membership
and audit, and a founder with three workspaces should not be billed three times
by accident. A new `workspace_billing` row keyed by `workspace_id`, holding plan,
Stripe customer and subscription ids, current period bounds, and status.

Usage is *derived, not stored as a counter*: count `account_research_requested`
audit events in the current period. The audit table is already the source of
truth, and a derived count cannot drift from reality the way a hand-maintained
counter does.

---

## 5. Over-limit and lapsed subscription

**Proposal: soft cap with a hard stop on new research only.**

Over the monthly limit:

- New research is refused with 429 `PLAN_LIMIT_REACHED`, naming the limit, the
  count, and the reset date.
- **Everything already researched stays fully readable, reviewable and
  exportable.**

Lapsed subscription (payment failed, 14-day grace):

- During grace: full function, persistent banner.
- After grace: workspace becomes read-only. Research refused; reading, review and
  **export stay available**.

Tradeoffs, stated plainly:

- *Against:* read-only workspaces cost us storage indefinitely for £0. Retention
  bounds it at 180 days, but it is a real cost.
- *For:* the alternative — withholding evidence a founder already paid to gather —
  makes the product hostile at exactly the moment they are deciding whether to
  come back. It also risks looking like ransom over their own data.
- *Rejected:* deleting data on lapse. Retention is a published promise
  (`retention_policy`, served on the Settings screen); overriding it for
  non-payment would make that promise conditional and untrustworthy.

**Export must never be gated.** A founder who cannot get their data out will not
trust the product with it in the first place.

---

## 6. Stripe integration outline

Design only.

**Checkout.** Stripe Checkout in subscription mode, not a custom card form — no
card data should reach GoPilot at any point. `client_reference_id` carries the
workspace id so the webhook can bind the subscription without trusting the
browser.

**Webhooks.** A single endpoint, signature-verified with the webhook secret
(never the API key), that is the *only* writer of subscription state — the
browser's return from Checkout is a UI hint and must never grant entitlement.

| Event | Effect |
|---|---|
| `checkout.session.completed` | bind customer + subscription to workspace |
| `customer.subscription.updated` | plan or period change |
| `customer.subscription.deleted` | start grace, then read-only |
| `invoice.payment_failed` | start grace, flag the workspace |
| `invoice.payment_succeeded` | clear grace |

Handlers must be idempotent on Stripe's event id — webhooks are delivered at least
once, and a replayed `subscription.deleted` must not re-lock a recovered account.

**Portal.** Stripe Customer Portal for plan changes, payment method and invoices.
Building those screens is weeks of work Stripe already did.

**Secrets.** Stripe keys follow the existing rule: environment only, never in
`.env.example`, never in Git, never logged. `RESEARCH_GATEWAY_TOKEN` already sets
the precedent, including the 32-character minimum enforced at startup.

---

## 7. Deliberately not yet

- Usage-based/metered billing to Stripe (report usage; charge a flat tier)
- Invoicing, POs, procurement, tax handling beyond Stripe Tax defaults
- Proration on mid-cycle plan changes
- Enterprise contracts, custom terms, SSO-gated plans
- Annual pricing and discounts
- Dunning sequences beyond the single grace window
- Per-seat pricing
- Free-trial credit-card capture
- Any refund automation

---

## 8. Sequence, when it is time

1. Usage metering with **enforcement disabled** — count and display only. Confirms
   the meter matches reality before anyone is blocked by it.
2. Read the numbers from real alpha usage. The tier boundaries above are informed
   by cost, not by demand; only usage tells you whether 300 is generous or mean.
3. Plan records and the Settings surface showing usage against limit.
4. Stripe Checkout + webhooks, still without enforcement.
5. Turn enforcement on, soft cap first.

---

## 9. One risk worth naming

The meter is honest but it is not free of incentive. Charging per account
researched rewards *volume of research*, and the product's actual value is
**deciding which companies not to bother with**. A founder who imports 300
accounts, sees that 280 are poor fits, and contacts 20 has received enormous value
and generated a large bill; one who researches 30 well-chosen companies pays
little.

Metering fetches is the closest proxy to cost, so it stays. But the pricing page
should not encourage researching more — and the product should keep making it
easy to *not* research an account, which is what the import validation and
identity gates already do before a single fetch is spent.
