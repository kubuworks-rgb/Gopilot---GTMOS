# GoPilot — Product Scenario Blueprint

**Status:** product north star. Section numbers are referenced by the gap analysis,
execution plans and commit messages, so they are stable and must not be renumbered.

---

## 1. What GoPilot is

An evidence-backed GTM intelligence operating system. It answers: *out of all the
companies I could target, which deserve my attention, why, what is happening there
right now, how confident are we, and what should I do next?*

It is **not** a lead scraper, company database, chatbot, email generator, CRM or
search engine.

Core chain — every recommendation inspectable:

```
Company → Verify identity → Research → Evidence → ICP fit → Signals
        → Scores → Recommendation → Opportunity Brief → Human Review → Action
```

## 2. The two workflows

**A. BYOA (Bring Your Own Accounts) — core product.** The user supplies companies
(one, many, domains, pasted lists, CSV, future CRM). GoPilot does not discover them;
it determines whether this is the right company, whether it fits the ICP, what is
known and unknown, what evidence exists, whether something is happening now, and
whether to act, monitor, research further or avoid.

**B. Autonomous discovery — experimental.** May use Exa/Tavily/GDELT. The UI must say
it is experimental. Discovered accounts need extra verification. Never present it as
guaranteed founder-ready account generation.

## 3. Primary persona

Arun, a B2B SaaS founder with a small team, no research department, hundreds of
possible companies and limited bandwidth. His problem: *"I have 200 potential
companies but do not know which 10 deserve attention this week."* He wants "tell me
who matters, why, what changed, and show me the proof" — not 50 dashboards.

## 4. Scenario 1 — first-time user

Must not open onto internal terminology (`ResearchRun`, `SourceDocument`,
`AgentRun`, `GTMFinding`, `ProviderAdapter`, `EvidenceFact`). First screen is simple:
Import Accounts / Discover Accounts (Experimental), plus the four-step value
statement.

## 5. Product / company setup

A Product Profile: company, product, website, what it does, who buys it, market,
regions, preferred size, industries, pains solved, buyer roles, competitors,
exclusions. The user confirms it. **Business-critical ICP assumptions must never be
silently inferred.**

## 6. ICP builder

Convert the profile into an ICP with three tiers: **HARD criteria**, **SOFT
preferences**, **INFORMATIONAL criteria**. Unknown values stay `UNKNOWN` and must
never become `FALSE`. The ICP is editable.

## 7. Scenario 2 — importing 100 accounts

CSV upload, pasted domains, or manual entry. Required: `company_name`, `domain`.
Optional: `industry`, `country`, `employee_band`, `notes`, `crm_id`, `owner`, `tags`.

## 8. Import validation experience

Validate immediately and show a breakdown — rows uploaded, valid, duplicate,
invalid, requires review. The user inspects problems **before research starts**.
Canonicalisation, blocking and review reasons must be shown per row.
**Rows must never be silently dropped.**

## 9. Company identity

Determine exactly which company is meant: canonical name, registrable domain,
official domain, redirects, alternative verified domains, products, parent,
subsidiaries, aliases, acquisitions, rebrands.

Relationships: `SAME_ENTITY`, `PRODUCT_OF`, `SUBSIDIARY_OF`, `PARENT_OF`,
`SISTER_BRAND`, `REBRAND_OF`, `ACQUIRED_BY`, `PARTNER_OF`, `UNRELATED`, `UNKNOWN`.

**Similar names do not imply the same company.** `optivian.ai` must not become
evidence for `optivian.cloud` merely because both contain "Optivian". A relationship
must be proven.

## 10. Research orchestrator

Bounded research jobs with progress per stage (validated / identity / official
sites / ICP analysis / signals / briefs). **No fake completion percentages** — each
stage corresponds to actual persisted progress.

## 11. Research responsibilities

Logical responsibilities, not mandatory separate agents:

1. **Company identity** — who is this, which domains do and do not belong.
2. **Official-site research** — homepage, about, product, pricing, careers,
   newsroom, blog, customers, docs. First-party evidence.
3. **Firmographics** — business model, industry, geography, size, customer type,
   market. Every attribute carries value, state (`VERIFIED`/`ESTIMATED`/`UNKNOWN`),
   confidence and evidence. **Never invent employee counts.**
4. **ICP evaluator** — per criterion: `VERIFIED_MATCH`, `ESTIMATED_MATCH`,
   `UNKNOWN`, `VERIFIED_MISMATCH`.
5. **Signal research** — funding, hiring, launches, expansion, partnership,
   leadership change, customer growth, support expansion. A signal requires correct
   company, correct date, real event, relevant evidence, appropriate source and
   relevance. **Static marketing copy is not an event** — "Trusted by 100+
   companies" on a homepage is not a customer-growth signal without event semantics
   or dated evidence.
6. **Evidence auditor** — source exists, passage exists, identity compatible, claim
   scope compatible, source appropriate, not contradicted. Outcomes: `ATTACHED`,
   `UNATTACHED_ENTITY_AMBIGUOUS`, `RELATED_ENTITY_ONLY`, `REJECTED_SOURCE`, `STALE`,
   `UNKNOWN`.
7. **Scoring engine** — deterministic. Fit, Intent, Confidence, Priority. An LLM must
   not emit a score without deterministic inputs. Every score explainable by factor.
8. **Brief composer** — human-readable, introduces **no new unsupported claims**.
9. **Final QA guardrail** — before `FOUNDER_READY`, check identity, evidence, claim
   support, signal correctness, competitor status, confidence. Any critical issue
   downgrades the state.

## 12. Evidence chain

```
Source URL → SourceDocument → Passage/SourceChunk → EvidenceFact → GTMFinding
           → Account Fact → Signal → Score Factor → Recommendation → Brief
```

Important claims must be traceable backwards to their source.

## 13. Account states

- **`FOUNDER_READY`** — strong identity, ICP evidence, claims, confidence, actionable reason.
- **`RESEARCH_CANDIDATE`** — promising, important evidence unknown, worth more research.
- **`MONITOR`** — good fit, no compelling reason to act now.
- **`IDENTITY_REVIEW_REQUIRED`** — domain ambiguity, related brand, parent/subsidiary
  confusion, unresolved identity. No unsupported outreach.
- **`DO_NOT_TARGET`** — verified mismatch, direct competitor, wrong market or type.

## 14. Account priority dashboard

Counts per state, then a table: company, state, Fit, Intent, Confidence, Priority,
why now, evidence, last researched, action. Sortable and filterable by priority,
fit, intent, confidence, state, country, industry, owner, tag, signal, unknowns.

## 15. Account detail screen

Should feel like an analyst researched the company. Sections: status and scores,
**why this account matters**, **why now**, **ICP fit** (per criterion with verified/
unknown/mismatch), **current signals**, **unknown information**, **rejected or
ambiguous evidence** (shown deliberately — this creates trust), **recommended
action** with reason, **next research step**, **evidence** links.

## 16. Opportunity Brief

**Not one giant AI paragraph.** Structured sections:

1. Executive summary (2–3 sentences)
2. Why it fits (✓ / ? per criterion)
3. Why now — verified current events only; if none, **"NO CURRENT HIGH-CONFIDENCE
   SIGNAL"**, which is acceptable
4. Verified facts — fact, evidence, confidence
5. Unknowns — never hidden
6. Signals — event, date, confidence, relevance, evidence
7. Scores — Fit, Intent, Confidence, Priority with factor drill-down
8. Risks
9. Recommendation — target / research / monitor / identity review / do not target
10. Next best action — one clear step
11. Sources — clickable

## 17. Human review

The user can: agree, change status, add notes, mark evidence incorrect, mark company
irrelevant, flag wrong identity, mark signal irrelevant, request re-research.
**Feedback is stored.** Do not silently retrain or alter deterministic logic from one
person's feedback.

## 18. Campaign / outreach draft

Only `FOUNDER_READY` accounts expose a draft by default. **No automatic sending.**
Explicit review and approval required. Weak accounts must not get confident drafts.

## 19. Safe export

Fields: `company_name`, `domain`, `state`, `fit_score`, `intent_score`,
`confidence_score`, `priority_score`, `recommended_action`, `primary_evidence_url`,
`unknowns`, `owner`, `review_status`. Spreadsheet-safe. No secrets, no raw provider
messages, no internal system data.

## 20. Scenario 3 — no current signal

Strong fit, no reliable recent signal. Do **not** invent one. Fit high, Intent low,
state `MONITOR`, with an explanation and what to watch for. This is a good result.

## 21. Scenario 4 — not enough information

Relevant but unprovable size / model / geography → `RESEARCH_CANDIDATE`, **not**
`DO_NOT_TARGET`. Show unknown count, confidence and next step.

## 22. Scenario 5 — wrong company

Domain points at a different organisation → `IDENTITY_REVIEW_REQUIRED`. Stop
account-level recommendation until resolved.

## 23. Scenario 6 — direct competitor

Same target customer, product, problem, commercial substitution → `DO_NOT_TARGET`.
No outreach.

## 24. Scenario 7 — experimental discovery

Explicit experimental warning. Funnel is visible. Discovered companies display
"Discovered automatically", never "Imported by user".

## 25. Research providers

Replaceable infrastructure: Exa/Tavily/future for discovery, GDELT for events,
direct safe fetching for official evidence, GitHub, RSS, public media metadata.
**Exa is not a product feature.** Users should not need to understand MCP or provider
architecture.

## 26. Competitor differentiation

Research actual competitors (Apollo, Clay, 6sense, Common Room, ZoomInfo, Ocean.io,
Unify, Persana, Amplemarket, AI SDR platforms) before claiming superiority, and
produce `docs/product/COMPETITOR_POSITIONING.md`.

Candidate differentiators, to be **validated against the market, not assumed**:
evidence-first recommendations; unknown-aware reasoning; entity-safe research;
explainable deterministic scoring; honest no-signal outcome; opportunity brief
instead of raw lead data; human-in-the-loop; provider-independent BYOA.

## 27. UX principle

Hide internal complexity. Internally there may be workers, Redis, evidence facts,
source chunks, providers, claim compatibility, agent runs. The founder sees accounts,
evidence, signals, scores, recommendations, briefs, actions. **Do not make the
founder operate the research engine.**

## 28. Navigation

Home, Accounts, Import, Research, Experimental Discovery, Briefs, Review Queue,
Exports, Settings. Admin/diagnostics must not dominate normal navigation.

## 29. Home dashboard

Decision information: accounts researched, ready for review, research candidates,
monitoring, identity issues, excluded. Plus weekly deltas — new high-confidence
signals, accounts that increased priority, accounts that lost evidence freshness.

## 30. Research transparency

A secondary "Research Details" view for technical users: sources, evidence, rejected
evidence, provider, retrieval date, reasoning, score factors. Secondary, not primary.

## 31. Failure states

Distinct, visible states for: website unavailable, robots restriction, 403, 429,
timeout, DNS failure, invalid domain, identity unresolved, insufficient evidence,
provider unavailable, partial research. **No failure silently becomes success.** Live
failures are never replaced with demo fixtures.

## 32. Performance / cost control

Bounded research: cheap validation → cheap identity → basic research → determine
research-worthiness → deeper research only when valuable. Search count, page count,
runtime and document count bounded and configurable.

## 33. Private alpha scope

Invite-only, BYOA, limited accounts/imports, evidence-backed briefs, manual review,
export. Autonomous discovery disabled by default or clearly experimental. No public
signup, no autonomous outreach.

## 34. Success metrics

Identity correctness 100%; cross-company evidence attachment 0%; supported important
claims ≥95%; unsupported <5%; false signal attachment 0%; mean brief usefulness
≥2/3; founder-useful ≥80%. Plus research completion, time saved, user corrections.

## 35. The ultimate experience

> "I uploaded 100 companies this morning. GoPilot researched them while I worked. Now
> I have 12 to look at, 28 needing research, 41 worth monitoring, and 19 I can ignore.
> For every recommendation I can see exactly why. I did not spend two days manually
> opening 100 websites."

## 36–38. Working principles

Classify every feature as COMPLETE / PARTIAL / MISSING / EXPERIMENTAL / BROKEN /
OVERENGINEERED / UNNECESSARY. Do not rebuild everything at once.

**Do not build what already exists. Do not rewrite stable systems without reason. Do
not create a separate agent per function merely because this document says "agent".**
Prefer simple modules, clear interfaces, deterministic rules, good tests, strong
provenance, clean UX.

Use an LLM only for summarisation, research synthesis, claim interpretation and brief
composition. Keep deterministic: identity constraints, security, qualification rules,
score calculation, evidence gating, permissions.

**Prioritisation.** P0: wrong company, wrong evidence, security, data leaks, false
founder-ready recommendations. P1: private alpha, BYOA end-to-end, login, research
reliability, brief usefulness, CI/deployment. P2: UX, review workflows, exports,
observability, feedback. P3: autonomous discovery, extra providers, CRM, analytics,
campaigns.

## 39. Required design document

`GoPilot — Complete Product Design`, covering promise, persona, problems, journey,
both workflows, product profile, ICP builder, import, research architecture, logical
agents, identity/evidence/signal models, scoring, brief, states, dashboard, detail
UX, review, export, approval, error states, providers, security, cost controls,
competitor comparison, differentiation, current implementation, missing features,
features to simplify, private alpha scope, roadmap, acceptance scenario.

## 40. End-to-end acceptance scenario

A founder logs in, creates a workspace, defines their product and ICP, uploads 20
companies. All accounts validated; duplicates detected; unsafe domains rejected;
identity verified; research runs; official sources fetched; evidence extracted;
cross-company evidence rejected; ICP evaluated; unknowns remain unknown; signals
require real events; scores deterministic; briefs generated. Weak accounts are not
founder-ready. No-signal accounts become Monitor. Competitors become Do Not Target.
Ambiguous identities become Identity Review Required. The founder sees prioritised
results, opens an account, understands why it fits, why now, what is unknown, what
evidence supports it and what GoPilot recommends, changes status, and exports the
reviewed list.

**No autonomous message is sent. No Exa/Tavily key was required for the
supplied-account workflow.**
