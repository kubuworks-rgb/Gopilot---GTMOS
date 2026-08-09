# GoPilot — Gap Analysis

**Date:** 2026-08-08
**Branch:** `feature/private-alpha-hardening`
**Method:** Read the code, ran the deployed stack, clicked through the live UI, and
queried the real database. Every claim below cites a file:line or an observation
from the running system.

---

## 0. Two referenced artifacts do not exist — read this first

This analysis was requested against a "Product Scenario Blueprint" with numbered
sections (8, 9, 10, 15–17, 19, 31, 36–38, 40) and a competitive research report on
Clay / Common Room / Salesmotion.

**Neither exists in this repository or in this session.** No document under `docs/`
contains those numbered sections (`grep` for "PRODUCT SCENARIO", "Section 31",
"Section 40" returns nothing), and no competitive research was produced here.

What does exist is the **project handover document** supplied at the start of this
session, which uses **lettered** sections A–AP. This analysis uses that as the
requirements source. Where this document says "the handover requires X", that is
verifiable; nothing has been invented to fill in for a blueprint section I cannot
read.

**Consequence:** the requested "classify every scenario in the blueprint" cannot be
done faithfully. Section 2 below classifies against the handover's lettered
requirements instead. If the blueprint exists elsewhere, supply it and this section
can be redone properly.

---

## 1. Module inventory and wiring

| Module | Does | Wired end-to-end? |
|---|---|---|
| `apps/web/components/command-center.tsx` | All 16 UI views in one file | Yes |
| `apps/api/app/api/live_routes.py` | Live API, 22 endpoints | Yes |
| `apps/api/app/api/routes.py` | Fixture API, 17 endpoints | Yes, but duplicate (§4.1) |
| `apps/api/app/services/live_research.py` | Research pipeline, 3,100+ lines | Yes |
| `apps/api/app/services/entity_resolution.py` | Entity + claim-scope gating | Yes |
| `apps/api/app/services/scoring.py` | Deterministic Fit/Intent/Confidence/Priority | Yes |
| `apps/api/app/services/byoa.py` | Import validation, mode availability | Yes |
| `apps/api/app/services/private_alpha.py` | Invite gate, usage limits | Yes |
| `apps/api/app/security/{jwks,tokens}.py` | OIDC verification | Backend yes; **browser sign-in unverified** |
| `services/research_gateway/` | Fetch + URL policy + providers | Yes |
| `services/worker/app/main.py` | Redis consumer, at-least-once | Yes |
| `apps/api/app/workflows/research_graph.py` | LangGraph scaffold | **No production caller** (§4.2) |
| `apps/api/app/agents/prompts.py` | Prompt strings | **No production caller** |
| `JobLeaseRow` / `job_leases` | Lease table | **Modelled, migrated, never read or written** |
| `scripts/` (15 files, ~3,400 lines) | Acceptance harnesses | 12 of 15 are historical |

---

## 2. Requirement classification (against the handover, A–AP)

| Handover requirement | Status | Note |
|---|---|---|
| L — BYOA works with no Exa/Tavily | **COMPLETE** | Verified live: smoke test passes with both keys unset |
| N — entity identity safety | **COMPLETE** | `entity_resolution.py`; brief-level attachment verified clean on real data |
| O — claim-scope safety | **COMPLETE** | Dual gate enforced |
| Q — deterministic scoring | **COMPLETE** | No LLM in scoring path |
| D.2 — unknown is not false | **COMPLETE** (fixed this session) | Was scoring unknown as 0; now `None` + renormalised |
| P — signals need date/event semantics | **COMPLETE** (fixed this session) | Static-page exemption removed |
| U — production authentication | **PARTIAL** | Backend complete and tested; **no verified browser sign-in** |
| V — tenant isolation | **COMPLETE** | Verified live (403 on cross-tenant) |
| T — migration consistency | **COMPLETE** | `alembic check`: "No new upgrade operations detected" |
| AE — CI | **COMPLETE** | 4 jobs green |
| AF — deployment | **COMPLETE** | Full stack deployed and smoke-tested |
| AH — data deletion | **COMPLETE** | Verified: zero orphans, tenant-scoped |
| **AG — observability of failures** | **BROKEN** | See P0-1 |
| R — brief exposes rejected evidence | **PARTIAL** | Count only, no items; and **no slot at all for failed fetches** |
| AA — UI makes BYOA obvious | **PARTIAL** | Import flow good; ICP/Research views are discovery-era |
| AB — safe export | **COMPLETE** | Field set correct, no secrets (asserted in smoke test) |
| AI — do not overengineer | **PARTIAL** | Dead LangGraph scaffold, unused lease table, duplicate routers |

---

## 3. Confusing-things audit (the part you asked for specifically)

### 3.1 A 87.5%-failed research run is displayed as clean success — **P0**

Importing `apache.org` and clicking "Research account" attempts 8 pages. Observed in
the live database just now:

```
https://apache.org/          completed
https://apache.org/about     failed   SOURCE_UNAVAILABLE
https://apache.org/product   failed   SOURCE_UNAVAILABLE
https://apache.org/products  failed   SOURCE_UNAVAILABLE
https://apache.org/customers failed   SOURCE_UNAVAILABLE
https://apache.org/careers   failed   SOURCE_UNAVAILABLE
https://apache.org/blog      failed   SOURCE_UNAVAILABLE
https://apache.org/news      failed   SOURCE_UNAVAILABLE
```

The UI showed: `VALIDATED DOMAIN · 99%`, one fact, and
**"0 evidence items rejected or held for review."**

The failures are persisted correctly (`live_research.py:1499-1501` writes
`task.status = "failed"` and `task.error`), but **nothing reads them back out**.
`ResearchRun` (`domain/models.py:143`) carries only `searches_used`,
`documents_used`, `findings` and a single run-level `error` — there is no per-task
failure surface, so the API cannot expose it and the UI cannot show it.

The brief has a slot for *"evidence we rejected"* but **no slot for *"pages we could
not fetch"***. Those are different things, and only one has a home.

This is the exact "failure silently swallowed and shown as success" case. It also
directly undermines the Confidence score: 55/100 looks like a considered judgement,
not "we only managed to read one page."

The gateway distinguishes **14 error codes** (`SOURCE_UNAVAILABLE`, `FETCH_TIMEOUT`,
`RATE_LIMITED`, `UNSUPPORTED_CONTENT_TYPE`, `URL_POLICY_BLOCKED`, …). Every one of
them collapses into the same invisible nothing.

### 3.2 "EXACTLY THREE CANDIDATES" above exactly one candidate — **P1**

`command-center.tsx:248`. Live screenshot of `/icps` in BYOA mode:

- Header: **"EXACTLY THREE CANDIDATES"** — one ICP is displayed
- Subtitle: *"Each candidate traces its rationale to research evidence"* — the card
  reads **"0 evidence record"**
- Heading: "Choose the market worth learning from" — BYOA does not choose a market;
  the user supplied the accounts

BYOA creates exactly one ICP (`postgres.py:387`, name `"Imported account target"`).
Three statements on one screen, all false in the default product mode.

### 3.3 Research view speaks autonomous-discovery language — **P1**

`command-center.tsx:246`:

- Title **"Market and ICP discovery"** for a run that did neither
- `run.findings` is always empty in BYOA → an unexplained blank region, no empty state
- Budget denominators **hardcoded** `/60` and `/100` with `max="60"`/`max="100"`,
  not read from the run's actual budgets
- Copy: *"Optional source failure returns partial results; it cannot crash the full
  workflow"* — true, but this is the one screen where those failures could be shown
  and it shows none (§3.1)

### 3.4 Status pill colour derives from a different field than its label — **P1**

`command-center.tsx:251` and `:265`:

```
className={`qualification-pill ${account.qualification_status.toLowerCase()}`}
>{account.brief_state.replaceAll("_", " ")}
```

The CSS class comes from `qualification_status`; the visible text comes from
`brief_state`. These are different enumerations, so the colour can contradict the
word. Observed live: text `MONITOR` styled by `insufficient_evidence`.

### 3.5 Two concepts stacked under one column header — **P2**

The accounts table header says **STATUS**, and the cell renders `brief_state` above
`review_status` (`command-center.tsx:251`). One header, two independent state
machines. A founder cannot tell which one "PENDING" belongs to.

### 3.6 Account states are bare labels in the table — **P2**

The accounts table shows `MONITOR` / `RESEARCH CANDIDATE` with no reason. The reason
*does* exist on the detail page ("Reason not to target: …", evidence gaps), so this
is a surfacing gap rather than a missing capability.

### 3.7 Undiscoverable or dead-end UI — **P2**

- **Campaigns** nav lists every account as a "draft" (`command-center.tsx:268`)
  regardless of whether a draft exists or the account is `FOUNDER_READY`; clicking
  through reaches an account whose page says *"No outreach draft generated"*.
- **Approvals** shows `approval_count` drafts but lists every account.
- **Experimental discovery** is correctly gated, but the button is disabled with no
  explanation of what the user would gain by configuring a provider.

### 3.8 Terminology drift, UI vs code — **P2**

| UI says | Code/API calls it |
|---|---|
| "Status" (table header) | `brief_state` **and** `review_status` |
| "Priority" column shows `MONITOR · 4` | `priority_band` + `scores.priority` merged |
| "Sources" (research view) | `documents_used` |
| "ICP studio / candidates" | one `ICPProfileRow` |
| "Score" (badge component) | `fit` / `intent` / `confidence` / `priority` |

---

## 4. Code-level problems

### 4.1 Duplicate API surface — **P2**
`routes.py` (17 endpoints) and `live_routes.py` (22) implement the same product
against different repositories, selected by an import-time branch in `main.py:10`.
The fixture surface is **missing 4 endpoints** that exist in live:
`/accounts/refresh`, `/accounts/{id}/research`, `/accounts/{id}/regenerate-brief`,
`/qa-evaluations`. Every contract change must be made twice, and already has drifted.

### 4.2 Dead code — **P2**
- `workflows/research_graph.py` — no production import; only
  `test_security_and_scoring.py:87` exercises it. `langgraph==1.2.9` is a production
  dependency solely for this.
- `agents/prompts.py` — no production caller.
- `JobLeaseRow` / `job_leases` — modelled and migrated, never read or written. The
  worker's reliability is implemented with Redis lists instead.
- `scripts/`: 12 of 15 files are phase-specific archaeology (~2,600 lines).

### 4.3 Evidence confidence is a constant — **P2**
`live_research.py` writes `confidence="0.82"` for every fact. The UI renders it as
**"82% confidence"** on every single passage, implying a per-fact judgement that does
not exist.

### 4.4 Not a bug (checked, ruling it out)
`evidence_facts` rows are scoped to workspace + source, not to accounts, so a raw
`JOIN` on `workspace_id` appears to show one company's text under another's name.
**Brief-level attachment was verified clean on live data**: Python Software
Foundation cites only `python.org`; SQLAlchemy cites only `sqlalchemy.org`. The
entity gate is doing its job.

---

## 5. Prioritised fix list

### P0 — silent failure presented as success
1. **Failed page fetches are invisible.** §3.1. Surface per-task retrieval outcomes
   through the API and into the brief and research views, as distinct states
   (unavailable / timeout / rate-limited / policy-blocked / unsupported type).
   Confidence must reflect retrieval coverage, not just what was parsed.

### P1 — the UI states things that are not true
2. ICP view: "exactly three candidates" / "traces rationale to evidence" (§3.2)
3. Research view: "Market and ICP discovery", hardcoded budgets, blank findings (§3.3)
4. Status pill colour derived from a different field than its text (§3.4)

### P2 — clarity, duplication, dead weight
5. One header covering two state machines (§3.5)
6. Bare state labels in the table (§3.6)
7. Campaigns / Approvals list accounts that have nothing to act on (§3.7)
8. Terminology drift (§3.8)
9. Duplicate router surfaces, already drifted (§4.1)
10. Dead LangGraph scaffold, `job_leases`, script archaeology (§4.2)
11. Constant 0.82 confidence presented as a per-fact number (§4.3)

### P3 — later
12. `live_research.py` at 3,100+ lines
13. `command-center.tsx` one-line components

---

## 6. On the three "defensible differentiators"

Assessed against the code, not aspiration:

**A. Entity-safety — already real.** `entity_resolution.py` requires identity
compatibility *and* claim-scope compatibility, treats a different registrable domain
as hard-rejected without evidence-backed relationship, and never uses brand-token
similarity for first-party sources. Verified on live data. Gap: the confusable-pair
test suite you asked for does not exist as a named, runnable artifact
(`test_entity_resolution.py` covers pieces).

**B. Unknown-aware reasoning — real as of this session.** Was genuinely broken:
absent industry/geography scored as hard `0`. Fixed to `None` + renormalisation.
Gap: unknowns are visible on the Account Detail brief but **not** in the accounts
table, and the "82% confidence" constant undercuts the claim.

**C. Provider-independent BYOA — already real and verified.** Smoke test passes end
to end with `EXA_API_KEY` and `TAVILY_API_KEY` unset; CI pins them empty at workflow
level. `/search` is reachable only from discovery paths.

So of the three, **one needed fixing (B, done), one needs a demonstrable test suite
(A), and one is already proven (C)**. The honest framing is that these are mostly
existing strengths needing better proof, not features to build.

I have not done the requested competitive research on Clay/Common Room/Salesmotion
in this phase — Phase 1 was specified as read-only repository analysis, and I would
rather not mix unverified external claims into a gap analysis of your code.

---

## 7. Recommended sequence

P0-1 first, alone — it is the only item that makes the product actively misleading.
Then P1 3.2/3.3/3.4, which are small copy and binding fixes with high honesty value.
Then the entity-safety demonstration suite (differentiator A), since it is proof
rather than new behaviour.
