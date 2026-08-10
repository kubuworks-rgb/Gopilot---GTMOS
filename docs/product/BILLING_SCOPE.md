# GoPilot — Billing Scope

**Status:** scoping only. **No implementation.** Numbers below are proposals for you
to decide, not commitments.
**Date:** 2026-08-09

New scope — not in the product blueprint. Positioning context comes from
[COMPETITOR_POSITIONING.md](COMPETITOR_POSITIONING.md); enforcement call sites were
read from the codebase, not designed in the abstract.

---

## 1. Where the cost actually sits

Before proposing a meter, where does a workspace cost money?

| Activity | Real cost | Scales with |
|---|---|---|
| **Researching an account** | 1–8 HTTP fetches, parsing, chunking, storage, worker time | **accounts researched** |
| Re-researching | same again | re-research requests |
| Storing evidence | Postgres rows, text | accounts × pages retained |
| Viewing briefs/dashboards | a database read | negligible |
| Seats | nothing marginal | nothing |

**The cost is research operations, not UI usage.** A workspace with 5 users reading
100 researched accounts costs almost exactly what 1 user reading them costs.

That points to **accounts researched per month** as the meter, with **seats as a
packaging lever rather than a cost recovery mechanism**.

One caveat worth pricing around: re-research is a real repeat cost, and today
`/accounts/{id}/research` can be called repeatedly with no per-account throttle. Any
meter counting "accounts researched" must decide whether a re-research counts again.
**Proposal: yes, it counts** — it consumes the same resources, and not counting it
creates an obvious loophole.

## 2. Plan model

Three tiers. The paid entry point deliberately undercuts Clay's ~$149–185/mo, which
the positioning work identified as the reference price.

| | **Solo** (free) | **Founder** | **Team** |
|---|---|---|---|
| Price | $0 | **$79/mo** proposed | **$249/mo** proposed |
| Accounts researched / month | 25 | 300 | 1,500 |
| Accounts stored | 100 | 1,000 | 5,000 |
| Seats | 1 | 3 | 10 |
| Concurrent research runs | 1 | 3 | 5 |
| Imports / day | 3 | 20 | 50 |
| Export | ✓ | ✓ | ✓ |
| Experimental discovery | ✗ | ✗ | opt-in |
| Retention | 30 days | 180 days | 365 days |

**Why free tier exists.** Entity-safety and unknown-aware reasoning are invisible
until you use them on companies you know. 25 accounts is enough for a founder to
check GoPilot against companies whose truth they can verify — which is the actual
sales mechanism for this product.

**Why $79.** Below Clay's entry point, above the "is this serious?" line. The
positioning is not "cheaper Clay" — it's a different tool — but the price has to be
legible against the thing buyers compare it to.

**Why seats are generous.** Seats cost nothing marginal. Charging per seat would
push teams to share logins, which destroys the review-attribution that `review_history`
exists to provide.

**Retention as a tier lever** is deliberate: it maps to a real storage cost and is
already implemented as a configurable window per §33 work.

### Open question for you

Is 300 researched accounts/month right for $79? It implies ~$0.26/account. I have no
usage data — this is a guess anchored to competitor pricing, not to observed
behaviour. **Recommend launching Founder-tier metered but not enforced for the first
cohort**, to gather the distribution before committing to a number.

## 3. Enforcement points — actual call sites

These already exist and follow one pattern: raise `LimitExceeded`, return `429` with
a machine-readable code. Plan limits should extend this, **not introduce a second
mechanism**.

| Where | File:line | Today | Plan-aware change |
|---|---|---|---|
| Import size | `live_routes.py:624` `assert_import_size` | Global cap | Per-plan cap |
| Accounts stored | `live_routes.py:626` `assert_workspace_capacity` | Global cap | Per-plan cap |
| Imports/day | `live_routes.py:625` `assert_daily_import_quota` | Global cap | Per-plan cap |
| Concurrent runs | `live_routes.py:303` `assert_run_concurrency` | Global cap | Per-plan cap |
| Workspaces/user | `live_routes.py:233` `assert_workspace_quota` | Global cap | Per-plan cap |
| Export rows | `live_routes.py:904` `assert_export_size` | Global cap | Per-plan cap |
| **Research quota** | **`live_routes.py:689`** `research_account` | **none** | **New — the meter** |
| **Research quota** | **`live_routes.py:770`** `regenerate_brief` | **none** | Free (no fetch) |
| **Research quota** | **`live_routes.py:339`** run creation | **none** | New |

**The important gap:** every existing limit is a *shape* limit (how many accounts,
how often). None is a *consumption* limit. The meter needs one new check at
`research_account` — the single place a fetch is actually queued.

`regenerate_brief` should **not** consume quota: it recomputes from stored evidence
without fetching. Charging for it would push users away from re-reading their own
data, which is the opposite of the desired behaviour.

### Counting correctly

Count at **enqueue**, not completion — otherwise a user can queue 10,000 jobs before
the first finishes. But a job that dead-letters should refund, since the customer got
nothing. Both hooks exist: `enqueue_job`, and `record_job_failure` for terminal
failures.

## 4. Over-limit and lapsed-subscription behaviour

**Proposal: read-only, never destructive.**

| State | Behaviour |
|---|---|
| Within limits | Normal |
| Quota exhausted | Research blocked (`429`, plan code). Everything else works. |
| Payment failed | 14-day grace, full function, escalating banner |
| Grace expired | **Read-only**: view, review, export. No new research or imports. |
| Cancelled | Read-only for the retention window, then eligible for deletion |

**Why read-only rather than a hard block.** The product's asset is the founder's
accumulated evidence and review decisions. Locking them out of data they already paid
to produce is the behaviour that generates chargebacks and bad-faith reviews. **Export
must keep working in every non-fraud state** — a customer who cannot get their data
out will say so publicly, and for a product selling trustworthiness that is a
disproportionate cost.

**Tradeoffs, stated plainly:**

- Read-only is *weaker* commercial pressure than a hard block. Some will sit in
  read-only indefinitely. Acceptable: they cost nothing (no research = no fetches).
- A 14-day grace means up to two weeks of unpaid research at full rate. Bounded by
  the plan's own quota, so the exposure is capped and small.
- Quota-exhausted-but-paid is the one hard block, and it should upsell rather than
  merely refuse.

## 5. Integration

**Stripe.** Nothing in this stack argues otherwise: Checkout removes card handling
entirely (this codebase must never touch card data), webhooks fit the existing
worker/queue shape, and the Customer Portal removes the need to build plan-change and
payment-method UI at all.

### Minimal integration

**Storage — workspace-level, not user-level.** Limits are already enforced per
workspace (`assert_workspace_capacity`, `assert_daily_import_quota`), and a user can
belong to several. Billing must line up with the thing being limited.

```
workspace_subscriptions
  workspace_id        FK, unique
  stripe_customer_id
  stripe_subscription_id
  plan                solo | founder | team
  status              active | past_due | canceled | incomplete
  current_period_end
  grace_until         nullable
  accounts_researched_this_period   int
  period_started_at
```

A new table rather than columns on `workspaces`: billing state changes on a different
cadence than workspace identity, and keeping it separate means a billing outage
cannot corrupt tenancy.

**Three flows only:**

1. **Checkout** — `POST /billing/checkout` → Stripe Checkout session → redirect.
2. **Webhook** — `POST /billing/webhook`, signature-verified, handling
   `checkout.session.completed`, `customer.subscription.updated`,
   `customer.subscription.deleted`, `invoice.payment_failed`. Idempotent by event ID;
   Stripe retries.
3. **Portal** — `POST /billing/portal` → Stripe Customer Portal. Plan changes,
   payment methods and cancellation are Stripe's UI, not ours.

**Webhook is the only source of truth for subscription state.** Never infer
entitlement from a checkout redirect — the user can navigate away, and the redirect
is not authenticated as a payment.

### Security notes

- Webhook signature verification is mandatory; an unverified endpoint is a free
  subscription for anyone who reads the docs.
- `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` are secrets: the CI scanner already
  matches `SECRET_KEY` and would catch a committed one.
- The webhook must be reachable publicly while `api` stays internal — the Caddy
  config needs one explicit path exception, and that is the **only** route that should
  be exposed without authentication.

## 6. Deliberately out of scope

For a first paid tier — flagged as skipped, not forgotten:

| Not building | Why |
|---|---|
| Usage-based billing beyond a cap | Metered billing needs usage-reporting reconciliation and a dispute story. A cap is legible and one integer. |
| Invoicing / purchase orders | Enterprise procurement. No enterprise customers. |
| Proration | Stripe handles it on plan change; do not reimplement. |
| Multi-currency | USD only until there is demand with a location attached. |
| Annual contracts | Needs a renewal and dunning story that does not exist. |
| Per-seat pricing | Seats cost nothing marginal; charging pushes teams to share logins and destroys review attribution. |
| Credit rollover | Every rollover scheme creates end-of-period gaming. |
| Free-trial-of-paid | The free tier *is* the trial, with no card and no expiry cliff. |

## 7. Sequence, once you have decided

1. Confirm tiers, prices and the research quota.
2. Migration for `workspace_subscriptions`.
3. `plan_limits.py` beside `private_alpha.py`, same `LimitExceeded` pattern.
4. Research quota check at `research_account` and run creation.
5. Stripe Checkout, webhook, portal.
6. Read-only mode.
7. Billing section on Settings, next to the retention statement.

**Blocked first:** none of this matters until OIDC sign-in works, because billing
attaches to an authenticated identity. Sign-in is the prerequisite.

## 8. One risk worth naming

Billing pushes toward *more* research — it is the meter. The product's argument is
that **not** researching, and saying "unknown" or "no signal", is often the right
answer. If quota pressure ever nudges the product toward researching more accounts
more shallowly, the meter has damaged the thing being sold.

**Mitigation:** meter accounts researched, never facts produced or signals found.
Nothing in the plan model should reward finding *more*, only researching *more
companies*.
