# GoPilot — Complete Product Design

**Date:** 2026-08-09
**Blueprint:** §39 (section headers below are exactly those it lists)
**Sources:** the codebase as it stands at `47ad2d6`,
[GAP_ANALYSIS.md](GAP_ANALYSIS.md), [COMPETITOR_POSITIONING.md](COMPETITOR_POSITIONING.md),
and [PRODUCT_SCENARIO_BLUEPRINT.md](PRODUCT_SCENARIO_BLUEPRINT.md).

This is a synthesis of what exists, not a plan. **Anything not built says so.**

---

## Product Promise

> Turn a messy list of companies into a prioritised set of evidence-backed
> decisions — and never assert anything the product cannot prove.

Concretely: a tool that will not tell you something it cannot show you the source
for, will not confuse one company for another, and needs no paid data provider to
research the accounts you already have.

## Target User

A B2B SaaS founder with a small team, no research function, hundreds of possible
companies and limited bandwidth. The problem is not finding companies — it is
deciding which ten deserve attention this week, and being able to justify that.

## Problems Solved

1. **Which of these companies matter?** Deterministic Fit / Intent / Confidence /
   Priority with a visible per-factor breakdown.
2. **Why does this one matter?** Every material claim traces to a passage, a source
   URL and a retrieval date.
3. **What don't we know?** Unknowns are named, not filled in or silently zeroed.
4. **Is this even the right company?** Identity is verified before anything attaches.
5. **Is anything happening now?** Signals require a real dated event; "no" is a valid
   answer.

## Main User Journey

```
Product profile → Import accounts → Validate (per-row verdicts)
  → Research official sources → Extract evidence → Verify identity
  → Evaluate ICP → Detect signals → Score → Compose brief
  → Human review → Export
```

Implemented end to end and verified live against real company websites.

## BYOA Workflow — the core product

**Status: COMPLETE.**

Single account, pasted list, or CSV. Validation returns a verdict for every row
(valid / duplicate / invalid / needs review) with summary counts, the canonical
domain each resolved to, and a reason — shown *before* anything is written. Research
fetches a bounded set of official paths through the gateway using direct HTTP only.

**No search provider is required.** Verified: the smoke test passes with
`EXA_API_KEY` and `TAVILY_API_KEY` unset, and CI pins both empty.

## Experimental Discovery Workflow

**Status: EXPERIMENTAL, off by default.**

Requires a configured provider *and* `ALLOW_EXPERIMENTAL_DISCOVERY=true`; during
private alpha it is disabled regardless. Three route-level guards return HTTP 409.
Its quality never met the historical acceptance thresholds and it is not presented
as production-ready.

## Product Profile

**Status: PARTIAL.** Company, website, product and target market are captured and
stored as user-confirmed claims. Blueprint §5 additionally asks for buyer roles,
preferred size, industries, competitors and explicit exclusions as first-class
fields — **these are not separately modelled**; they are inferred from the free-text
target market.

## ICP Builder

**Status: PARTIAL.** BYOA creates one user-confirmed ICP from the product profile
and evaluates criteria with `VERIFIED_MATCH` / `UNKNOWN` / mismatch semantics.

**Not built:** the three-tier HARD / SOFT / INFORMATIONAL structure of §6, and
user editing of the ICP. The UI now states plainly that the profile is
user-confirmed rather than evidence-derived, instead of the previous false claim
that it traced to research evidence.

## Account Import

**Status: COMPLETE.** Canonicalisation (www, scheme, port, case, tracking),
rejection of private/local/IP/reserved destinations and directory/social hosts,
formula-injection neutralisation, in-import and cross-workspace duplicate detection,
and a conservative needs-review flag when the supplied name and domain share no
meaningful token.

## Research Architecture

```
API ──enqueue(id)──► Redis ──BLMOVE──► Worker ──► Research Gateway ──► public web
 │                                        │
 └──────────── PostgreSQL ◄───────────────┘
```

Only typed IDs cross the queue — no code or command. Delivery is at-least-once: a
job is claimed into a per-worker in-flight list and released only when it settles,
so a crash mid-job is reclaimed on restart, retried, then dead-lettered with the
failure recorded on the row.

## Logical Research Agents

Blueprint §11 describes nine responsibilities. **All nine are deterministic
services, not LLM agents** — §38 explicitly warns against creating an agent per
function.

| §11 responsibility | Implementation |
|---|---|
| 1 Company identity | `company_identity.py`, `entity_resolution.py` |
| 2 Official-site research | `live_research.py` bounded path fetch |
| 3 Firmographics | `firmographics.py` |
| 4 ICP evaluator | `_qualify_account` |
| 5 Signal research | `_signals_from_facts` |
| 6 Evidence auditor | `assess_evidence_attachment` |
| 7 Scoring | `scoring.py` — no LLM |
| 8 Brief composer | `compose_executive_summary` — deterministic |
| 9 QA guardrail | `decide_brief_state` |

**No LLM is called anywhere in the product today.** The blueprint permits one for
summarisation and brief composition; the executive summary is instead assembled from
counted, verified inputs, so it cannot introduce a claim the brief does not support.

## Identity Model

Ten relations (`SAME_ENTITY`, `PRODUCT_OF`, `SUBSIDIARY_OF`, `PARENT_OF`,
`SISTER_BRAND`, `REBRAND_OF`, `ACQUIRED_BY`, `PARTNER_OF`, `UNRELATED`, `UNKNOWN`)
and six claim scopes. Attachment requires **both** identity compatibility and
claim-scope compatibility.

A relationship counts only when backed by evidence IDs. A different registrable
domain is hard-rejected without one — brand-token similarity is never consulted for
first-party sources.

**Verified:** `packages/entity-safety/tests/test_confusable_pairs.py` — seventeen
near-miss pairs, covered by 22 tests. Removing the different-domain rejection turns
11 red, including the named Optivian case.

## Evidence Model

```
Source URL → SourceDocument → SourceChunk → EvidenceFact
  → attachment decision → Account fact → Signal → Score factor → Brief
```

Per-fact confidence derives from the source's computed trust score and whether the
passage matched the research question. Site chrome — navigation runs, footers, skip
links — is rejected by a quality gate before it can be presented as a fact.

Excluded evidence is shown with its passage and the reason, not merely counted.

## Signal Model

A signal requires a real event: correct entity, compatible claim scope, an
event-semantics page or a published date, and freshness. **Recency comes from the
event date, never from fetch time** — the fix that stopped a static "Trusted by 100+
customers" line scoring as maximum-freshness intent. Absent a date, a signal
contributes no recency rather than borrowing the moment we happened to fetch.

## Scoring

Deterministic and LLM-free.

- **Fit** — industry 0.45 / size 0.35 / geography 0.20, renormalised over known
  factors. Unknown is never a mismatch.
- **Intent** — strength 0.60 / recency 0.40, same treatment.
- **Confidence** — evidence coverage 0.40 / source quality 0.35 / retrieval coverage
  0.25.
- **Priority** — `(Fit·0.55 + Intent·0.45) × Confidence / 100`.

Every component carries its evidence IDs and renders in the brief.

## Opportunity Brief

**Status: COMPLETE.** All 11 sections of §16 render live: executive summary, why it
fits, why now, verified facts, unknowns, signals, scores, risks, recommendation,
next best action, sources. Plus official-pages-read and rejected-evidence panels.

"Why now" reads **NO CURRENT HIGH-CONFIDENCE SIGNAL** when true, framed as an honest
result rather than a gap.

## Account States

`FOUNDER_READY`, `RESEARCH_CANDIDATE`, `MONITOR`, `IDENTITY_REVIEW_REQUIRED`,
`DO_NOT_TARGET`, decided deterministically in that precedence.

`FOUNDER_READY` requires five conditions and **cannot be set by hand** — the API
returns 409, and the UI omits it from the state selector.

## Dashboard

**Status: PARTIAL.** Reports real run state, account counts, average priority and
approval count, with workflow steps ticked only when actually done. Previously it
asserted completion regardless of state; that is fixed.

**Not built:** §29's weekly deltas — new high-confidence signals, accounts that
gained priority, accounts that lost evidence freshness. No historical comparison
exists yet.

## Account Detail UX

**Status: COMPLETE.** Identity and verified domains, per-criterion ICP fit, signals
with dates, unknowns, rejected evidence with reasons, retrieval coverage, per-factor
score breakdown, recommendation, next step, sources, and the review panel.

## Review Workflow

**Status: COMPLETE.** Agree/approve, request changes, change state, add a note, flag
wrong identity, mark irrelevant, request re-research. Decisions append to an ordered
`review_history` with actor, state and timestamp. Verified persisted in PostgreSQL.

## Export

**Status: COMPLETE.** Fifteen columns including the §19 field set. Approved accounts
only, formula-neutralised, defined once and shared by both routers. An automated
test asserts no column name resembles an internal identifier, provider payload or
credential.

## Human Approval

**Status: COMPLETE.** No send path exists anywhere. Drafts are exposed only for
`FOUNDER_READY` accounts; edit and approve return 409 otherwise. The approvals queue
counts only actionable drafts.

## Error States

**Status: PARTIAL.** Retrieval outcomes are distinct and visible: retrieved,
truncated, not-found, forbidden, unavailable, timed-out, rate-limited,
blocked-by-policy, unsupported-content, cross-domain-redirect. Absent pages are
excluded from coverage rather than counted as failures.

**Not distinctly surfaced:** robots restriction and DNS failure, which currently
collapse into the generic unavailable state. Queue and provider unavailability are
recorded on the run but not richly rendered.

## Provider Architecture

`GeneralSearchProvider` abstracts Exa (primary) and Tavily (fallback); GDELT serves
news; direct fetch serves official evidence. Availability is computed from
environment presence, needing no network call.

**BYOA touches only the fetch leg.** Search is reachable only from discovery and
from optional enrichment behind `search_provider_configured()`.

## Security

- OIDC/JWKS verification, fail-closed; algorithm pinned from an allowlist and never
  read from the token, so `alg: none` and HMAC confusion are refused before any
  signature check. Symmetric algorithms are rejected by configuration validation.
- Invite-only access; limits return explicit `429`s and never silently truncate.
- Gateway refuses to start in production without a token; validated addresses are
  pinned for the connection, closing the DNS-rebinding window.
- Per-hop URL revalidation, content-type allowlist, streaming size caps.
- Tenant isolation enforced on every resource route.
- Secret scanner in CI reports file and line, never the matched value.

**Gap: the browser sign-in flow has never completed against a real issuer.**

## Cost Controls

Bounded searches, documents, pages per account, elapsed time, accounts per import,
accounts per workspace, imports per day, concurrent runs, workspaces per user and
export rows — all configurable, all validated positive at startup.

## Competitor Comparison

See [COMPETITOR_POSITIONING.md](COMPETITOR_POSITIONING.md). Summary: the
account-research layer consolidated through five acquisitions in seven months;
Salesmotion is the closest conceptual competitor and Clay the closest capability
benchmark; the market is currently punishing autonomous-sender positioning.

## GoPilot Differentiation

Three verified, four partial, one commoditised — rated in the positioning doc, not
asserted equally:

- **Defensible:** provider-independent BYOA, entity-safe research, unknown-aware
  reasoning.
- **Partial:** evidence-first (Salesmotion and Clay now claim similar),
  deterministic scoring (defensible on determinism, not explainability), honest
  no-signal, human-in-the-loop (positioning, not a moat).
- **Commoditised:** briefs over raw lead data.

## Current Implementation

528 tests passing, 9 skipped. CI green across backend, frontend, database and
security. Deployed stack of seven services verified end to end against real company
websites. Schema at migration `0008`; `alembic check` reports no drift.

## Missing Features

| Missing | Blueprint | Impact |
|---|---|---|
| Browser sign-in against a real issuer | §33 | **Blocks private alpha** |
| ICP three-tier structure and editing | §6 | Medium |
| Product profile structured fields | §5 | Medium |
| Weekly deltas on the dashboard | §29 | Medium |
| Robots and DNS failure as distinct states | §31 | Low |
| Accounts table sort/filter | §14 | Low |
| Research Details view | §30 | Low |

## Features To Remove/Simplify

**Already removed:** LangGraph scaffold, `agents/prompts.py`, the `langgraph`
dependency, and the never-used `job_leases` table (migration `0008`).

**Still outstanding:**

- **Duplicate routers.** Fixture and live implement 15 shared paths. Not merged: the
  fixture repository is synchronous and session-less while Postgres is async with
  session injection, so merging means rewriting all fifteen. A contract-parity guard
  now prevents silent drift.
- **`live_research.py` at ~3,200 lines.** Splits along existing seams.
- **`command-center.tsx`** one-line components.
- **~2,600 lines of historical acceptance scripts** in `scripts/`.
- **Nav still shows ten items** including ICP studio and Research, which carry little
  meaning in a BYOA-first product (§28 says nav should reflect what is real).

## Production Deployment Scope

BYOA only, bounded usage, human-reviewed output, safe export, autonomous discovery
disabled by default. Optional invite-gating for anyone who wants to run a closed
deployment rather than an open one. Deployable via
`deploy/docker-compose.production.yml` with a runbook and a smoke test.

Browser sign-in (Authorization Code with PKCE against any standard OIDC issuer,
including logout, refresh, and tenant isolation) is implemented and verified live —
see `scripts/verify_oidc_flow.py`.

## Later Roadmap

**None of this is built.** Listed as direction only:

1. ICP editing and the three-tier structure.
2. Dashboard deltas, which need historical snapshots.
3. Router consolidation behind a repository protocol.
4. Splitting the research monolith.
5. Automatic deletion once past the retention window — currently preview-only via
   `scripts/apply_retention.py`, by design, until an operator confirms each run.
6. Re-evaluating autonomous discovery quality.
7. CRM import, explicitly out of scope for alpha.

Explicitly **not** planned: outbound sending, autonomous outreach — §18 and the
competitive evidence in §3.1 of the positioning doc both argue against it.

## End-to-End Acceptance Scenario

§40's scenario, as verified live:

| Step | Verified |
|---|---|
| Workspace, product, ICP | ✓ |
| Import 2+ companies | ✓ real domains |
| Duplicates detected | ✓ reported, not merged |
| Unsafe domains rejected | ✓ localhost, metadata IP, directories |
| Identity verified | ✓ `VALIDATED DOMAIN · 99%` |
| Official sources fetched | ✓ real HTTP through the gateway |
| Evidence extracted | ✓ with passage and source |
| Cross-company evidence rejected | ✓ each account cites only its own domain |
| Unknowns remain unknown | ✓ six named, none defaulted |
| Signals require real events | ✓ NO_SIGNAL returned honestly |
| Scores deterministic | ✓ per-factor breakdown |
| Weak accounts not founder-ready | ✓ 409 on manual promotion |
| No-signal becomes Monitor | ✓ |
| Founder reviews and exports | ✓ note persisted; export approved-only |
| No message sent | ✓ no send path exists |
| No provider key required | ✓ both unset throughout |

**Not verified:** "a new founder logs in" — the first step of §40. Everything after
it works; the front door does not yet.
