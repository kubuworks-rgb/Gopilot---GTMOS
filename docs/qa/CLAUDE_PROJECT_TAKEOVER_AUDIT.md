# GoPilot — Claude Takeover Audit

**Audit date:** 2026-08-08
**Auditor:** Claude (incoming lead engineer)
**Commit audited:** `ef2467c7ace974f57ffe54fc9d234e17c3f3d67f` (`feature/byoa-core-product`)
**Method:** Read-only inspection of executable code, migrations, tests and Git metadata.
Historical QA reports were treated as claims to be re-verified, not as evidence.

Every status label below is derived from code I read or a command I ran. Where I could
not verify a claim in this environment, it is marked `UNKNOWN` with the reason.

---

## 1. Executive Summary

GoPilot today is a **single-tenant-shaped, demo-authenticated, evidence-backed account
research application** with a genuinely good deterministic intelligence core and no
production authentication.

What actually exists and works:

- A real BYOA (Bring Your Own Accounts) import → validate → research → score → brief →
  review → export pipeline that runs against user-supplied official domains and
  **does not require Exa or Tavily**. I verified this structurally: the BYOA research
  path calls `provider.fetch` (gateway HTTP fetch), never `provider.search`.
- A deterministic, LLM-free scoring module that correctly renormalizes around unknown
  values instead of penalising them.
- A deterministic entity-relation and claim-scope gate that is the strongest piece of
  engineering in the repository, and which does prevent the historical Optivian
  cross-entity defect by construction.
- A hardened research gateway with per-redirect URL revalidation, content-type
  allowlisting, streaming size limits and DNS-resolution-based private-IP blocking.
- A brief UI that genuinely exposes verified facts, ICP mismatches, unknowns,
  NO_SIGNAL, hypotheses and per-component score math, and which hides the outreach
  draft entirely unless the account is evidence-gated `FOUNDER_READY`.

What is not true today:

- **There is no authentication.** Identity is an unverified `X-Demo-User` request
  header. The frontend sends no credential at all. Any caller can assume any user.
- **Intent freshness is fabricated for undated pages.** Signal recency is computed from
  *fetch time*, not event time, and `CUSTOMER_GROWTH_INDICATOR` is explicitly exempted
  from the dated-or-event-page requirement. A static "Trusted by 100+ customers"
  homepage line becomes a maximum-recency current intent signal. This is the exact
  defect class the product principles forbid, and it is still live.
- **There is no CI.** There is no `.github` directory at all, which fully explains
  "Checks: 0" on PR #1.
- **There is no deployment path.** `docker-compose.yml` contains only PostgreSQL and
  Redis — no api, web, worker or gateway service.

The codebase is smaller and better than the handover narrative suggests (152 tracked
files), but it carries ~2,600 lines of historical acceptance-harness archaeology and a
3,042-line research monolith.

**The honest position: the BYOA intelligence core is close to alpha quality. The
product around it — auth, CI, deployment, signal honesty — is not.**

---

## 2. Current Git State

Verified with `git status -sb`, `git branch -vv`, `git remote -v`, `git rev-parse HEAD`.

| Item | Value |
|---|---|
| Current branch | `feature/byoa-core-product` |
| HEAD | `ef2467c7ace974f57ffe54fc9d234e17c3f3d67f` |
| Tracking | `origin/feature/byoa-core-product` (in sync) |
| Worktree | clean |
| Remote | `https://github.com/kubuworks-rgb/Gopilot---GTMOS.git` |
| `develop` | `9c4eaac` (tracked) |
| `main` | `b1b4107` (tracked) |
| Local-only branches | `feature/intelligence-quality-improvement` (`48ce711`), `feature/real-gtm-intelligence` (`a5838a7`) — not pushed |

The commit list in the handover is accurate; I confirmed all named commits exist with
the stated messages. `feature/byoa-core-product` is 17 commits ahead of `develop`.

PR #1 state could not be re-verified from this environment (no authenticated `gh`
session was exercised, per the instruction not to take network actions during audit).
Treated as **UNKNOWN**, but the absence of `.github/workflows` independently confirms
the reported zero CI checks.

**Nothing has been merged, tagged, force-pushed or deployed. No history was rewritten.**

---

## 3. Actual Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│ apps/web  ·  Next.js 15 / React (no auth, no session, no login)      │
│   command-center.tsx — single 205-line file, all views               │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ fetch(), NO Authorization header
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│ apps/api  ·  FastAPI                                                 │
│                                                                      │
│   main.py  ──┬── RESEARCH_MODE=fixture → api/routes.py      (17 ep)  │
│              └── RESEARCH_MODE=live    → api/live_routes.py (22 ep)  │
│                    ▲ import-time branch: two parallel API surfaces   │
│                                                                      │
│   get_live_principal()  ← X-Demo-User header, UNVERIFIED             │
│        └── repository.resolve_membership()  ← membership IS enforced │
│                                                                      │
│   services/  byoa · entity_resolution · scoring · company_identity   │
│              firmographics · intelligence_quality                    │
│              live_research.py ...................... 3,042 lines     │
└───────┬──────────────────────────────────┬───────────────────────────┘
        │ enqueue (Redis LPUSH)            │ SQLAlchemy async
        ▼                                  ▼
┌───────────────────────┐        ┌──────────────────────────────┐
│ services/worker       │        │ PostgreSQL (pgvector:pg17)   │
│  BLPOP loop           │        │  27 tables, 6 migrations     │
│  no ack / no retry    │        │  head = 0006_intelligence_…  │
│  drops workspace_id   │        └──────────────────────────────┘
└───────┬───────────────┘
        │ calls execute_job(kind, target_id)
        ▼
┌──────────────────────────────────────────────────────────────────────┐
│ services/research_gateway  ·  FastAPI, X-Gateway-Token (optional!)   │
│   /fetch   → WebPageAdapter  → httpx, per-hop validate_public_url    │
│   /search  → SearchAdapter   → Exa / Tavily / GDELT   (OPTIONAL)     │
│   /github /rss /youtube                                              │
└──────────────────────────────────────────────────────────────────────┘
```

The critical structural fact: **BYOA uses only the `/fetch` leg.** The `/search` leg —
and therefore Exa and Tavily entirely — is reachable only from autonomous discovery and
from optional BYOA enrichment guarded by `search_provider_configured()`.

---

## 4. Repository Map

152 tracked files. Every major folder:

| Path | Responsibility | Status |
|---|---|---|
| `apps/web/` | Next.js UI, 1 monolithic component file | `IMPLEMENTED_AND_USED` |
| `apps/api/app/domain/models.py` | Pydantic domain contracts (498 ln) | `IMPLEMENTED_AND_USED` |
| `apps/api/app/db/models.py` | SQLAlchemy rows, 27 tables (411 ln) | `IMPLEMENTED_AND_USED` |
| `apps/api/app/api/live_routes.py` | Live API, 22 endpoints (864 ln) | `IMPLEMENTED_AND_USED` |
| `apps/api/app/api/routes.py` | Fixture API, 17 endpoints (459 ln) | `DUPLICATED` |
| `apps/api/app/api/dependencies.py` | Fixture-mode principal | `UNSAFE` |
| `apps/api/app/services/live_research.py` | Research monolith (3,042 ln) | `IMPLEMENTED_BUT_PARTIAL` |
| `apps/api/app/services/entity_resolution.py` | Entity + claim-scope gate | `IMPLEMENTED_AND_USED` |
| `apps/api/app/services/scoring.py` | Deterministic scores (105 ln) | `IMPLEMENTED_AND_USED` |
| `apps/api/app/services/byoa.py` | Import validation, mode availability | `IMPLEMENTED_AND_USED` |
| `apps/api/app/repositories/postgres.py` | Live persistence (1,111 ln) | `IMPLEMENTED_AND_USED` |
| `apps/api/app/repositories/fixture.py` | In-memory demo data | `IMPLEMENTED_AND_USED` (demo only) |
| `apps/api/app/workflows/research_graph.py` | LangGraph scaffold | `DEAD_CODE` in production; test-only (see §22) |
| `apps/api/app/agents/prompts.py` | Prompt strings | `DEAD_CODE` (see §22) |
| `apps/api/alembic/versions/` | 6 migrations, head `0006` | `IMPLEMENTED_BUT_PARTIAL` |
| `services/research_gateway/` | Source retrieval + safety | `IMPLEMENTED_AND_USED` |
| `services/worker/app/main.py` | Redis consumer (49 ln) | `IMPLEMENTED_BUT_PARTIAL` |
| `scripts/` (15 files, 3,375 ln) | Acceptance harnesses | 12 of 15 are `DEAD_CODE` |
| `docs/qa/` | Preserved QA evidence | keep — historical record |
| `.github/` | — | **ABSENT** |

---

## 5. BYOA Core

**Status: `IMPLEMENTED_AND_USED`, provider-independent, with a signal-quality defect.**

Traced end to end:

| Hop | File / symbol | Notes |
|---|---|---|
| UI import | `command-center.tsx:154` `ImportAccountsView` | single / pasted / CSV |
| API | `live_routes.py:529` `import_accounts` | requires a selected ICP first |
| Validation | `byoa.py:275` `validate_account_import` | see below |
| Canonicalisation | `byoa.py:88` `canonicalize_public_company_domain` | strong |
| Persistence | `postgres.py:668` `import_accounts` | writes account + empty score snapshot + placeholder brief + draft |
| Queue | `live_routes.py:594` → `jobs/queue.py:27` | Redis RPUSH |
| Worker | `worker/app/main.py:27` BLPOP | **drops workspace_id** |
| Research | `live_research.py:2926` `research_account` | |
| Official fetch | `live_research.py:1430` `_fetch_supplied_official_sources` | **no search provider** |
| Evidence | `live_research.py:277` `_persist_source` | chunks + facts + provenance |
| Identity gate | `entity_resolution.py:224` `assess_evidence_attachment` | |
| Score + brief | `live_research.py:2399` `_score_and_brief` | |
| Review | `live_routes.py:617` `review_account` | FOUNDER_READY promotion blocked |
| Export | `live_routes.py:796` `export_accounts` | approved-only, formula-neutralised |

### What genuinely works

**Import validation is strong.** `canonicalize_public_company_domain` rejects non-HTTP(S)
schemes, URL credentials, non-standard ports, `localhost` / `.local` / `.internal`,
reserved TLDs, bare IP destinations, non-registrable domains, and directory/social/
job-board hosts. It strips `www.`, lowercases, and reduces to the registrable domain via
the public suffix list. Formula prefixes are rejected on domains and neutralised on all
optional free-text fields. CSV parsing rejects unknown headers, missing required
headers, and malformed input. Duplicates are removed within the import and against
existing workspace accounts.

**Provider independence is real.** `_fetch_supplied_official_sources` walks a fixed
bounded path list (`/`, `about`, `product`, `products`, `customers`, `careers`, `blog`,
`news`) using `provider.fetch`. Every hop asserts the *post-redirect* canonical domain
still equals the account's registrable domain, and rejects with
`CROSS_DOMAIN_REDIRECT_REJECTED` otherwise. Search enrichment happens only inside
`if search_provider_configured():` at `live_research.py:3014`.

**Failure is honest.** If no official source or fact is obtained, the account and its
persisted brief are both moved to `IDENTITY_REVIEW_REQUIRED` with confidence zeroed
(`live_research.py:2950-3010`). No fixture substitution occurs anywhere in the live path.

### What is incomplete

- The signal-freshness defect in §10 undermines the "why now" half of every brief.
- The worker cannot recover a lost job (§17).
- `_fetch_supplied_official_sources` tries 8 fixed paths on every account regardless of
  whether the site's sitemap or nav suggests they exist, producing predictable 404s.

---

## 6. Experimental Discovery

**Status: `EXPERIMENTAL` — correctly gated. Leave it alone.**

`product_mode_availability()` (`byoa.py:69`) returns
`AUTONOMOUS_DISCOVERY_EXPERIMENTAL = CONFIGURATION_REQUIRED` when neither `EXA_API_KEY`
nor `TAVILY_API_KEY` is set, and `BYOA_CORE` is a `Literal["AVAILABLE"]` — it is
structurally incapable of reporting anything else. Three route-level guards return HTTP
409 `CONFIGURATION_REQUIRED` for discovery without a provider
(`live_routes.py:235`, `:456`, `:479`).

The UI places discovery in a separate nav entry rendered with an `EXPERIMENTAL` badge and
an explicit human-review warning (`command-center.tsx:172`).

**Which parts should remain:** the prequalification recall work and the entity gate are
valuable and shared with BYOA. The discovery orchestration itself should stay exactly as
gated as it is. I made no changes here and recommend none before alpha.

---

## 7. Database and Migrations

27 tables, 6 migrations, head `0006_intelligence_quality`. Table parity between
SQLAlchemy metadata and migrations is **exact** — no model-only or migration-only tables.

### Index drift — properly diagnosed

The historically reported "Alembic index metadata drift" is real but has been
mischaracterised. I classified it statically by parsing every migration's `upgrade()`
body (resolving both the `workspace_index(t)` helper and the f-string `for table in (…)`
loops) and diffing against `Base.metadata`:

| Classification | Count |
|---|---|
| `EXPECTED_EXISTING_INDEX` (agree exactly) | 54 |
| `MISSING_IN_MIGRATION` | 22 |
| `MISSING_IN_MODEL_METADATA` | 0 |
| `NAMING_ONLY_DIFFERENCE` | 0 |
| `ACTUAL_SCHEMA_DEFECT` | **0** |

**The drift is purely additive and one-directional:** the models declare 22 indexes that
no migration creates. There is no column-level or uniqueness disagreement anywhere, and
no table mismatch. `alembic check` reports drift because autogenerate wants to *add*
these, not because the deployed schema is wrong.

Of the 22, **21 are pure performance indexes** (foreign keys and status columns). Exactly
one carries a correctness meaning:

- `uq_source_chunk_ordinal` — `UNIQUE (source_document_id, ordinal)` on `source_chunks`.
  Declared on the model, never created. **A uniqueness invariant the database does not
  enforce.**

A methodological note worth recording: my first pass reported `uq_source_run_hash` as an
`ACTUAL_SCHEMA_DEFECT` and `uq_source_workspace_hash` as `MISSING_IN_MODEL_METADATA`.
Both were false positives caused by parsing `downgrade()` bodies alongside `upgrade()`.
Migration `0005` correctly widens `uq_source_run_hash` to the 3-column model form.
**No migration needs to be corrected — only extended.**

The fix is a single additive migration `0007` creating the 22 missing indexes. It is
non-destructive. The one unique index must be created defensively in case pre-existing
rows violate it.

Other schema observations: workspace scoping is consistent (every tenant table carries
`workspace_id` with `ON DELETE CASCADE` to `workspaces`), and
`uq_account_workspace_domain` correctly prevents duplicate logical companies per
workspace.

---

## 8. Research and Evidence

Evidence enters through exactly one path: `_persist_source` (`live_research.py:277`).

1. Content is hashed; an identical `(research_run_id, content_hash, canonical_url)` is
   reused rather than duplicated.
2. The page is classified into a `SourceRole` (`FIRST_PARTY`, `NEWS`, `DIRECTORY`,
   `VENDOR_MARKETING`, …). Marketing paths carrying market-claim language are demoted to
   `VENDOR_MARKETING`, which later disqualifies them from producing signals.
3. Text is split into overlapping `SourceChunk` rows.
4. Passages become `EvidenceFactRow`s with a fixed confidence of `0.82`.
5. `_validate_evidence` asserts the fact's workspace matches the source's workspace and
   raises otherwise — a genuine defence-in-depth check.

**Two weaknesses.** First, evidence confidence is the hardcoded string `"0.82"` for every
fact regardless of source role, recency or directness — the per-fact confidence signal
carries no information. Second, `observed_at = source.published_at or source.retrieved_at`
(line 402) conflates *when the event happened* with *when we downloaded the page*. This
is the root cause of §10.

---

## 9. Identity Safety

**Status: `IMPLEMENTED_AND_USED` — the strongest subsystem in the repository.**

`entity_resolution.py` implements the full relation set (`SAME_ENTITY`, `PRODUCT_OF`,
`SUBSIDIARY_OF`, `PARENT_OF`, `SISTER_BRAND`, `REBRAND_OF`, `ACQUIRED_BY`, `PARTNER_OF`,
`UNRELATED`, `UNKNOWN`) and the full claim-scope set (`COMPANY_LEVEL`, `PRODUCT_LEVEL`,
`PARENT_LEVEL`, `SUBSIDIARY_LEVEL`, `MARKET_LEVEL`, `PARTNER_LEVEL`).

Attachment requires **both** identity compatibility and claim-scope compatibility
(`claim_scope_is_compatible`, line 210). Critically:

- `_relationship_for_domain` returns `SAME_ENTITY` **only** when the source's registrable
  domain is in `verified_official_domains`, or when an explicit relationship record
  exists *with evidence IDs* (`VerifiedEntityRelationship.verified` requires
  `bool(self.evidence_ids)`).
- A different first-party domain with no verified relationship is hard-rejected as
  `UNATTACHED_ENTITY_AMBIGUOUS` (line 286) — **this is precisely the gate that stops the
  Optivian defect.** `optivian.ai` evidence cannot reach `optivian.cloud` because they
  are different registrable domains with no evidence-backed relationship, and brand-token
  similarity is never consulted for first-party sources.
- Third-party sources must *explicitly name* the canonical company or an
  evidence-backed alias, and are rejected if the text mentions a conflicting entity, a
  conflicting domain, or an alias that lacks evidence.

**Can the Optivian error recur?** Not through domain matching, redirects, or fuzzy names.
The one remaining surface is `_mentions_name` on third-party text (line 339): a news
article naming "Optivian" would attach to whichever Optivian account is being researched,
because the name match does not disambiguate between same-named entities on different
domains. This is mitigated — the conflicting-domain check runs first and would catch an
article that also mentions the other domain — but an article naming the brand without any
domain remains ambiguous. **Recorded as P2, not P0**, because the failure requires a
same-brand collision *and* a domainless third-party article.

---

## 10. Signals — **the most product-damaging defect found**

**Status: `UNSAFE`.**

`_signals_from_facts` (`live_research.py:2320`) applies good gates: rejected attachments
are skipped, `MARKET_LEVEL`/`PARTNER_LEVEL` scopes are excluded, `VENDOR_MARKETING`
sources are excluded, and non-first-party sources must pass
`_news_result_matches_company`.

Then it fails, in two compounding ways.

**(a) The dated-or-event-page requirement has an explicit exemption.**

```python
# live_research.py:2376
if source is not None and signal_type != "CUSTOMER_GROWTH_INDICATOR":
    dated_or_event_page = source.published_at is not None or any(
        marker in source.url.lower()
        for marker in ("/careers", "/jobs", "/news", "/blog", "/press", "/announcements")
    )
    if not dated_or_event_page:
        continue
```

`CUSTOMER_GROWTH_INDICATOR` matches `("customers"|"users"|"businesses")` **and**
`("grew"|"growth"|"serves"|"trusted by"|"crossed")` — so the literal string
**"Trusted by 100+ customers"** on a static homepage matches, and is waved past the
event-semantics requirement.

**(b) Recency is measured from fetch time, not event time.**

An undated page has `published_at = None`, so `observed_at` falls back to `retrieved_at`
(`live_research.py:402`) — i.e. *now*. Then:

- the 730-day staleness check (line 2390) trivially passes;
- `signal_decay(observed_at)` returns `1.0`;
- `signal_recency = 100` (line 2488) — the **maximum possible** recency score.

**Combined failure:** a static marketing boast with no date and no event becomes a
maximum-recency current intent signal. Because `decide_brief_state` requires
`has_actionable_signal` for `FOUNDER_READY`, this can promote an account to
`FOUNDER_READY` — and therefore unlock its outreach draft — on the strength of a
homepage line.

This is the exact failure mode the product principles forbid ("No fabricated intent",
"Search snippets are not final company facts", "static pages are not current events").
It survived Phase 6 because the entity gate and the signal-freshness gate are independent
concerns, and Phase 6 only fixed the former.

Note that (b) affects *every* signal type, not just the exempted one: a `/blog` or
`/careers` page with no `published_at` still yields recency `1.0`.

---

## 11. Scoring

**Status: `IMPLEMENTED_AND_USED` — deterministic and correct.**

`scoring.py` is 105 lines, pure, and contains no LLM call. No LLM supplies any numeric
score anywhere in the codebase.

- **Fit** uses `_breakdown_missing_aware`, which renormalises weights across only the
  known factors. Unknown is genuinely not treated as a mismatch — the documented
  principle is correctly implemented. Industry 0.45 / size 0.35 / geography 0.20.
- **Intent** = signal strength 0.60 + signal recency 0.40. Zero signal → zero intent,
  which is the correct treatment of `NO_SIGNAL`.
- **Confidence** = evidence coverage 0.55 + source quality 0.45.
- **Priority** = `(fit·0.55 + intent·0.45) · confidence / 100` — confidence correctly
  *gates* priority multiplicatively rather than being averaged in.
- Every component carries its `evidence_ids`, so the UI can and does explain the math.

The only weakness is inherited, not intrinsic: `signal_recency` is fed a fabricated
`observed_at` (§10), so intent and therefore priority are inflated for undated sources.
Fix §10 and scoring is sound.

---

## 12. Opportunity Briefs

**Status: `IMPLEMENTED_AND_USED`.**

`decide_brief_state` (`entity_resolution.py:372`) is deterministic and correctly ordered:

1. any unresolved identity warning → `IDENTITY_REVIEW_REQUIRED`
2. disqualified or direct-competitor conflict → `DO_NOT_TARGET`
3. verified identity **and** `QUALIFIED` **and** supported ICP fact **and** actionable
   signal **and** supported important claims → `FOUNDER_READY`
4. supported ICP fact but no actionable signal → `MONITOR`
5. otherwise → `RESEARCH_CANDIDATE`

`FOUNDER_READY` requires all five conditions — it cannot be reached by a weak account,
and `review_account` returns HTTP 409 on any manual promotion attempt
(`live_routes.py:632`). `update_campaign` returns 409 for `edit`/`approve` unless the
account is already `FOUNDER_READY` (`live_routes.py:741`). The gate is real and enforced
on both the state and the campaign.

One ordering question worth flagging: an account that is both disqualified *and* has an
identity warning surfaces as `IDENTITY_REVIEW_REQUIRED` rather than `DO_NOT_TARGET`.
Defensible (you cannot judge what you cannot identify) but worth an explicit decision.

The brief model exposes everything §R asks for. The only gap: the UI renders
`rejected_or_ambiguous_evidence` as a **count only**, not the items.

---

## 13. Frontend

**Status: `IMPLEMENTED_AND_USED` with misleading content and severe density.**

Verified green: `eslint` clean, `tsc --noEmit` clean, 4/4 web contract tests pass.

**The brief page is genuinely good.** `BriefView` shows verified identity and official
domains, verified facts with click-through evidence, ICP mismatches, unknown criteria,
reason-not-to-target, "why now" with an explicit `NO_SIGNAL — no verified current event.
Monitor remains valid.` fallback, hypotheses labelled *not verified facts*, per-component
score breakdowns, and — when not `FOUNDER_READY` — a clear **"No outreach draft
generated"** panel instead of the campaign editor. This is the product working as
designed and must be preserved.

**The dashboard is not honest.** `Dashboard` (`command-center.tsx:150`) renders:

- `<strong>1</strong>` hardcoded as "Active research";
- "All above confidence threshold" as a fixed caption under the account count;
- "Research is complete and N account opportunities are ready for review" regardless of
  run state;
- a hardcoded five-step workflow list — *"Product profile confirmed / Market evidence
  collected / 3 ICP candidates generated / ICP selected / Accounts scored and ranked"* —
  each rendered with a ✓ and the caption "Validated", **irrespective of what actually
  happened**.

For a product whose entire thesis is "every claim is inspectable", a dashboard that
asserts unearned completion is a direct contradiction of the value proposition.
`ResearchView` similarly hardcodes `/60` and `/100` budget denominators instead of
reading the run's actual budgets.

**Structure.** `command-center.tsx` is 205 lines containing 16 components, most written
as a single enormous line each (line 198 alone is the entire brief view). It passes lint
because no rule caps line length. This is the least maintainable file in the repository.

**Navigation.** Ten top-level entries. "ICP studio", "Research", and "Campaigns" are
autonomous-discovery-era concepts that carry little meaning in a BYOA-first product and
push the founder toward an internal-engineering-dashboard experience.

---

## 14. Authentication — **P0**

**Status: `UNSAFE` / effectively `STUB`.**

```python
# apps/api/app/api/live_routes.py:82
async def get_live_principal(session, x_demo_user=None, x_workspace_id=None):
    if not settings.demo_auth_enabled:
        raise HTTPException(401, "Verified authentication is required …")
    user_id = x_demo_user or "demo-user"
    membership = await repository.resolve_membership(session, user_id, x_workspace_id)
```

There is **no token, no signature, no verification of any kind**. `X-Demo-User` is
accepted as identity. `DEMO_AUTH_ENABLED` defaults to `true` (`config.py:15`). The
frontend (`lib/api.ts:5`) sends no `Authorization` header at all — there is no login
screen and no session anywhere in the product.

The one genuine protection: `config.validate()` refuses to start when
`APP_ENV=production` and demo auth is enabled (`config.py:58`). So GoPilot cannot boot
into production *with* demo auth — but it also cannot boot into production *at all*,
because no alternative authentication exists. That is a hard alpha blocker, and the
README (line 248) states it honestly.

`.env.example` declares `SUPABASE_URL`, `SUPABASE_JWKS_URL`, `SUPABASE_JWT_ISSUER`,
`SUPABASE_JWT_AUDIENCE` — **none of which any code reads**. An identity vendor appears to
have been chosen but never wired.

Nothing required by §U exists: no JWKS retrieval or cache, no issuer/audience validation,
no algorithm allowlist, no `exp`/`nbf` handling, no `kid` rotation.

---

## 15. Tenant Isolation

**Status: `IMPLEMENTED_AND_USED` — the logic is sound; the identity feeding it is not.**

This is better than expected and worth stating precisely, because it changes the shape of
the fix. `resolve_membership` (`postgres.py:237`) filters on `MembershipRow.user_id` and,
when a workspace is supplied, **also** on `MembershipRow.workspace_id`. A caller naming a
workspace they do not belong to gets no row → HTTP 403/404. Guessing a workspace ID does
not grant access.

I checked every live route that takes a resource ID:

| Route | Scoping | Verdict |
|---|---|---|
| `get_research` / evidence | `run_row(..., workspace_id)` + explicit `workspace_id ==` filters | ✓ |
| `list_accounts` / `brief` | workspace-filtered; `brief` re-checks `account_row.workspace_id` | ✓ |
| `review_account` | `str(row.workspace_id) != principal.workspace_id` → 404 | ✓ |
| `update_campaign` | `repository.campaign(..., workspace_id)` checks row workspace | ✓ |
| `create_feedback` | target row workspace compared | ✓ |
| `create_qa_evaluation` | both account **and** run workspace compared | ✓ |
| `select_icp` / `import_accounts` | `icp_row(..., workspace_id)` | ✓ |
| `export_accounts` / `audit` | workspace-filtered queries | ✓ |

**I found no ID-guessing hole.** The gap is entirely upstream: because `user_id` is
attacker-controlled, an attacker simply claims to *be* a member. Isolation is correctly
implemented around an identity that is worthless.

**Consequence for the repair plan: fixing authentication fixes tenant isolation.** No
per-route rework is required.

---

## 16. Security

**Good, and worth protecting:**

- `validate_public_url` (`url_policy.py:40`) rejects non-HTTP(S) schemes and URL
  credentials, blocks `localhost`/`*.localhost`/metadata hostnames, resolves DNS and
  rejects **any** resolved private / loopback / link-local / multicast / reserved /
  unspecified address, explicitly blocks `169.254.169.254`, and correctly unwraps
  NAT64 `64:ff9b::/96` addresses to check the embedded IPv4.
- `WebPageAdapter.fetch` disables httpx redirect following and **revalidates the URL
  policy on every hop** — the correct design.
- Content-type allowlist; size enforced *during* streaming, not after; explicit timeouts.
- Retrieved content is tagged `{"untrusted": True, …}` and never granted tool authority.
- CSV formula neutralisation on both import and export.
- Gateway token comparison uses `hmac.compare_digest`.
- Redis job payloads are typed IDs only — `decode_job` validates against a Pydantic model
  with a `Literal` job-kind union. No code or command can arrive via the queue.

**Findings:**

| # | Finding | Severity |
|---|---|---|
| S1 | Unverified `X-Demo-User` identity (§14) | **P0** |
| S2 | `require_internal_token` is a **no-op when `RESEARCH_GATEWAY_TOKEN` is unset** (`main.py:47` — `if expected and …`). Default `.env.example` ships it empty, so the gateway's `/fetch` is an unauthenticated fetch service on the network. | **P1** |
| S3 | DNS-rebinding TOCTOU: `validate_public_url` resolves, then httpx re-resolves at connect. With user-supplied BYOA domains this is a reachable SSRF vector. | **P1** |
| S4 | CORS `allow_headers` includes `X-Demo-User` / `X-Workspace-Id`, advertising the spoofable auth surface to browsers. | P2 |
| S5 | No rate limiting or per-workspace resource caps on any endpoint. | P2 |
| S6 | `httpx` response attributes (`encoding`, `status_code`) are read after the `async with` stream block closes — works today, fragile. | P3 |

I found **no** credential logging, no secrets in tracked files, no `shell=True`, and no
subprocess invocation in product code.

---

## 17. Worker / Queue

**Status: `IMPLEMENTED_BUT_PARTIAL`.**

`services/worker/app/main.py` is 49 lines: `BLPOP` → `decode_job` → `execute_job`.

| Issue | Impact |
|---|---|
| `BLPOP` removes the job before execution; a crash mid-job loses it permanently. No ack, no retry, no dead-letter. | Silent data loss — an account stays in `RESEARCH_CANDIDATE` forever with no error surfaced. |
| `except Exception: logger.exception(…)` swallows every failure; the account's row is never marked failed. | The UI cannot distinguish "still running" from "failed". |
| `execute_job(job.kind, job.target_id)` **drops `workspace_id` and `actor_id`** (`live_research.py:2913`). | Audit events attribute work to `"system"`; no defence-in-depth workspace re-check in the worker. |
| Single sequential consumer, no concurrency, no visibility. | A 20-account import serialises behind 8 HTTP fetches each. |
| A `job_leases` table exists in the schema and is **completely unused**. | The lease-based design was modelled and never implemented. |

Note the queue *is* safe by design — only typed IDs cross it. The problem is reliability,
not security.

---

## 18. Provider Architecture

**Status: correct. Exa is properly a replaceable detail.**

`GeneralSearchProvider` (`providers/general_search.py`) abstracts Exa (primary) and
Tavily (fallback); GDELT serves news/events; the webpage adapter serves direct fetch.
Availability is computed from environment presence only — no network call is needed to
determine mode availability, which is why the BYOA-without-Exa property is testable
offline.

The layering is right: BYOA depends on `/fetch`; discovery depends on `/search`; nothing
in the domain layer imports a provider by name. I recommend no changes here.

---

## 19. Testing

Measured, not reported: **172 passed, 3 skipped, 2 errors** in 7.18s.

The 2 errors are environmental — `PermissionError: [WinError 5]` creating
`C:\Users\LENOVO\AppData\Local\Temp\pytest-of-LENOVO` for the `tmp_path` fixture in
`test_acceptance_orchestration.py`. Not code defects. This exactly accounts for the
historical "174 passed" claim (172 + the 2 that cannot run here).

| Category | Reality |
|---|---|
| `UNIT` | Genuine. Entity resolution (297 ln), scoring, import validation, brief states. Strong. |
| `SECURITY` | Genuine. Gateway URL policy, SSRF, redirect, content-type. |
| `DATABASE` | **Gated off.** `test_live_database_integration.py` requires `RUN_LIVE_DB_TESTS=1` + live PostgreSQL. Not exercised here (Docker not running). |
| `CONTROLLED_TRANSPORT` | Genuine — asserts search is *never called* on the BYOA path. |
| `LIVE_OPT_IN` | Skipped by default (3 skips). |
| `END_TO_END` | Only via the DB-gated test. |
| `UI` | 4 contract tests — type-shape assertions only. No rendering, interaction, or state tests. |
| `QA_REPLAY` | `scripts/byoa_acceptance.py` — offline replay over a fixture CSV. |

**What is claimed beyond what is proven.** The "BYOA CORE QUALITY PASS" 20-account
evaluation is an **offline evaluation over `byoa_20_account_evaluation.csv` using
production validators and gates** — it exercises identity, claim-scope, scoring and
brief-state logic against curated fixtures. It is *not* evidence that 20 live websites
were fetched and correctly interpreted. The metrics (100% identity correctness, 0%
cross-company attachment) are true statements about the deterministic logic and should
be described that way. Notably, the evaluation cannot detect the §10 signal defect,
because the fixture passages are not real undated homepages.

Gaps: no auth tests (nothing to test), no tenant-isolation tests, no worker failure/
recovery tests, no migration tests, no frontend behaviour tests.

---

## 20. CI

**Status: `ABSENT`.**

There is no `.github` directory. No workflows, no actions, no secret scanning, no
required checks. This fully and independently explains "Checks: 0" on PR #1 — there is
nothing configured to run.

Everything needed for CI already works locally without any provider credential:
`ruff` ✓, `mypy` (52 files) ✓, `pytest` ✓, `eslint` ✓, `tsc` ✓, `npm test` ✓.
CI is a matter of writing the workflow, not of making the project testable.

---

## 21. Deployment

**Status: `IMPLEMENTED_BUT_PARTIAL` — local development only.**

`docker-compose.yml` defines **only** `postgres` (pgvector/pgvector:pg17) and `redis`.
There is no Dockerfile anywhere in the repository, and no compose service for the API,
web, worker or gateway. Postgres credentials are the literal `gtm:gtm`.

Nothing here is deployable. There is no healthcheck wiring for application services, no
startup ordering, no migration step, no reverse proxy, and no runbook.

---

## 22. Code Quality

**Dead code:**

- `apps/api/app/workflows/research_graph.py` and `apps/api/app/agents/prompts.py` — the
  LangGraph scaffold. `langgraph==1.2.9` is a declared production dependency; **no
  production code path imports it**. It is not entirely untouched: `test_security_and_
  scoring.py:87` exercises the graph, so it is a tested module with no production
  caller — the test proves the scaffold works, not that the product uses it. Removing
  both the module and its test lets the dependency go too.
- 12 of 15 files in `scripts/` (~2,600 lines) are phase-specific archaeology:
  `phase5_*`, `phase6_*`, `supportpilot_*`, `evaluate_supportpilot_v2`,
  `persist_supportpilot_qa`, `export_supportpilot_acceptance`, `inspect_supportpilot`,
  `prequalification_recall_replay`, `provider_discovery_probe`. Only
  `byoa_acceptance.py`, `live_smoke.ps1` and `gdelt_control_smoke.py` remain current.
- `job_leases` table — modelled, migrated, never read or written.

**Duplication:**

- `routes.py` (17 endpoints) and `live_routes.py` (22 endpoints) are parallel
  implementations of the same API, selected by an import-time branch in `main.py`. Every
  contract change must be made twice, and the fixture surface silently lacks 5 endpoints.
- `dependencies.py::get_principal` and `live_routes.py::get_live_principal` are two
  independent auth implementations. The former imports the **fixture** repository
  unconditionally.

**Complexity:**

- `live_research.py` — 3,042 lines, 31 module-level functions, spanning research
  planning, discovery, prequalification, firmographics, competitor assessment, identity,
  signals, scoring and brief generation. This is the single hardest file to change safely.
- `command-center.tsx` — 16 components, most one line each.

**Poor abstractions:**

- Account state is stored in an untyped `attributes` JSON blob and re-parsed with
  ~25 `str(row.attributes.get(...) or default)` calls in `account_domain`
  (`postgres.py:576`). Every field is stringly-typed with silent defaults; a typo yields
  a default rather than an error. This is why BYOA needed no migration — and also why
  schema drift here is invisible.

---

## 23. Documentation Accuracy

Better than expected. The README is notably honest — line 248 explicitly states
"Production JWT/JWKS authentication is not implemented".

| Doc claim | Reality | Verdict |
|---|---|---|
| BYOA works without Exa/Tavily | Structurally true | ✓ Accurate |
| No fixture fallback in live mode | True | ✓ Accurate |
| Deterministic scores, no LLM numerics | True | ✓ Accurate |
| Production JWT not implemented | True | ✓ Accurate |
| Autonomous discovery is experimental | True and enforced | ✓ Accurate |
| `.env.example` `SUPABASE_*` keys | **No code reads them** | ✗ Misleading |
| Handover: "174 passed" | 172 + 2 environmental errors | ~ Consistent |
| Handover: "BYOA CORE QUALITY PASS" | True of the *offline* evaluation; reads as a live-site claim | ~ Needs framing |
| Handover: "Alembic index metadata drift" | Real, but additive-only with 0 schema defects | ~ Under-diagnosed |
| README/docs on signals as dated events | Contradicted by the `CUSTOMER_GROWTH_INDICATOR` exemption | ✗ **Inaccurate** |

---

## 24. P0 Problems

| ID | Problem | Evidence | Impact | Root cause | Fix |
|---|---|---|---|---|---|
| **P0-1** | No authentication; `X-Demo-User` header is identity | `live_routes.py:82`, `dependencies.py:19`, `lib/api.ts:5` | Any caller is any user in any workspace they name. Tenant isolation is nullified. | Demo scaffold never replaced | Provider-neutral JWT/JWKS verification; fail closed; frontend sends bearer token |
| **P0-2** | Fabricated intent freshness | `live_research.py:2376` exemption + `:402` `observed_at` fallback | Static "Trusted by 100+ customers" ⇒ recency 100 ⇒ can reach `FOUNDER_READY` and unlock an outreach draft | Signal freshness derived from fetch time; one signal type exempted from event semantics | Remove the exemption; separate `event_date` from `retrieved_at`; no event date ⇒ no intent contribution |

---

## 25. P1 Problems

| ID | Problem | Evidence | Fix |
|---|---|---|---|
| P1-1 | No CI whatsoever | no `.github/` | Add credential-free workflow (all checks already pass locally) |
| P1-2 | Gateway auth is a no-op when token unset | `research_gateway/app/main.py:47` | Require the token outside explicit local dev; fail closed |
| P1-3 | Worker loses jobs on crash; failures invisible | `worker/app/main.py:27,41` | Reliable claim + failure recorded on the run/account row |
| P1-4 | 22 model-declared indexes absent from the DB, incl. the unique `uq_source_chunk_ordinal` | §7 | Single additive migration `0007` |
| P1-5 | No deployable artifact | `docker-compose.yml` | Dockerfiles + full compose + runbook |
| P1-6 | DNS-rebinding TOCTOU on user-supplied domains | `url_policy.py:40` | Pin the validated IP for the connection |
| P1-7 | Dashboard asserts unearned completion | `command-center.tsx:150` | Render real run state |
| P1-8 | No resource limits (accounts/import, concurrent runs, pages/account) | `config.py` | Configurable, explicit-error caps |

---

## 26. P2 Problems

- P2-1 Two parallel API implementations (`routes.py` / `live_routes.py`).
- P2-2 `live_research.py` at 3,042 lines.
- P2-3 `command-center.tsx` one-line components.
- P2-4 ~2,600 lines of historical acceptance scripts in the active tree.
- P2-5 Dead LangGraph scaffold + unused `langgraph` dependency.
- P2-6 Untyped `attributes` JSON blob as the account state store.
- P2-7 Same-brand third-party attribution ambiguity (§9).
- P2-8 Evidence confidence hardcoded to `0.82`.
- P2-9 Brief shows only a *count* of rejected evidence.
- P2-10 Ten-item nav dilutes the BYOA-first story.
- P2-11 No data-retention or deletion path.
- P2-12 Unused `job_leases` table.

---

## 27. Things That Should NOT Be Changed

Protect these. They are the verified core of the product.

1. **`entity_resolution.py` in its entirety.** The relation model, the dual identity +
   claim-scope requirement, the evidence-ID requirement on relationships, and the
   first-party-domain hard rejection. This is what makes GoPilot defensible.
2. **`scoring.py`.** Deterministic, LLM-free, and `_breakdown_missing_aware` is exactly
   the right treatment of unknowns.
3. **`decide_brief_state` ordering and the five-condition `FOUNDER_READY` gate**,
   including the 409s on manual promotion and on campaign edit/approve.
4. **`url_policy.py` + `WebPageAdapter`'s per-hop revalidation.** Do not relax any of it
   to make a test pass.
5. **`product_mode_availability`'s `Literal["AVAILABLE"]` typing of BYOA** — it makes the
   core-workflow guarantee unfalsifiable by construction.
6. **The no-fixture-fallback rule** in the live path.
7. **The typed Redis job contract** (IDs only).
8. **`BriefView`'s evidence-first layout** and the "No outreach draft generated" panel.
9. **All preserved QA evidence in `docs/qa/`.**

---

## 28. Recommended Simplifications

1. Collapse fixture and live routes into one router with a repository interface, or drop
   fixture mode from the product and keep it only as a test fixture.
2. Split `live_research.py` along existing seams: `research/official_sources.py`,
   `research/signals.py`, `research/qualification.py`, `research/briefs.py`,
   `research/discovery.py`.
3. Move `scripts/phase*`, `scripts/supportpilot*` and the other historical harnesses to
   `scripts/archive/` — preserve the evidence, stop maintaining the code.
4. Delete the LangGraph scaffold and drop `langgraph` from requirements.
5. Replace the stringly-typed `attributes` reads with one typed adapter.
6. Reduce the nav to the actual BYOA journey: **Import · Accounts · Approvals ·
   Settings**, with Discovery kept separate and badged.
7. Break `command-center.tsx` into per-view files.

---

## 29. Private Alpha Plan

Dependency-ordered. Each stage is independently verifiable.

**Stage 0 — Baseline (done during this audit)**
Test/lint/type baseline captured; index drift classified; no code changed.

**Stage 1 — P0-2 Signal honesty**
Separate `event_date` from `retrieved_at`. Remove the `CUSTOMER_GROWTH_INDICATOR`
exemption. A signal with no derivable event date contributes no intent. Add regression
tests: static homepage ⇒ `NO_SIGNAL`; dated press release ⇒ signal with real decay.
*Chosen first: it is pure domain logic, needs no infrastructure, and every later
quality measurement is invalid until it is fixed.*

**Stage 2 — P0-1 Authentication**
Provider-neutral JWKS verification module (issuer, audience, algorithm allowlist,
`exp`/`nbf`, `kid` rotation, cached JWKS, fail-closed). Single principal resolver shared
by both routers. `DEMO_AUTH_ENABLED` permitted only outside production. Frontend sends a
bearer token. Full §U test matrix plus explicit cross-workspace-denial tests.

**Stage 3 — P1-4 Migration `0007`** — additive indexes; defensive unique creation.

**Stage 4 — P1-1 CI** — backend (pytest/ruff/mypy), frontend (eslint/tsc/build/test),
security (gateway tests, secret scan, `git diff --check`), database (Postgres + Redis +
`alembic upgrade head` + integration). No provider credentials.

**Stage 5 — P1-2, P1-6 Gateway hardening** — token required outside local dev; pin the
validated IP for the connection.

**Stage 6 — P1-3 Worker reliability** — reliable claim, failure recorded on the row,
`workspace_id` and `actor_id` threaded through `execute_job`.

**Stage 7 — P1-8 Alpha limits + observability** — configurable caps with explicit
errors; safe operational events only (never tokens, CSV contents, notes or page bodies).

**Stage 8 — P1-5 Deployment** — Dockerfiles, full compose, `.env.private-alpha.example`,
runbook, smoke test.

**Stage 9 — P1-7 UX honesty** — real run state on the dashboard; simplified nav; render
rejected evidence items.

**Stage 10 — P2 cleanup** — archive scripts, delete dead code, split the monolith.

Stages 1–2 are the true alpha blockers. Stages 3–8 are the deployability blockers.

---

## 30. Estimated Current Readiness

| Dimension | Score | Reasoning |
|---|---:|---|
| **BYOA product quality** | **68** | Import, identity, scoring, brief states and gating are genuinely good and provider-independent. Held down by fabricated intent freshness (§10), which corrupts the "why now" half of every brief, and by a dashboard that asserts unearned completion. |
| **Engineering quality** | **62** | Clean lint/type/test baseline, honest docs, sound domain modelling. Offset by a 3,042-line monolith, duplicated API surfaces, ~2,600 lines of dead harness code, and stringly-typed state. |
| **Security** | **55** | Excellent SSRF/redirect/content policy and a safe queue contract. Reduced by the unauthenticated gateway default, DNS-rebinding TOCTOU, and the absence of any rate limiting. Not lower, because the isolation *logic* is correct. |
| **Authentication** | **8** | Nothing exists. The only credit is that production startup refuses to run with demo auth. |
| **Deployment** | **15** | Two infrastructure containers, no application images, no runbook, no environment template. |
| **Autonomous discovery** | **35** | Correctly gated and honestly labelled; quality never met its thresholds. The right call was made — keep it experimental. |
| **Overall private-alpha readiness** | **38** | Two P0s, no CI, and no deployable artifact. The distance is real but bounded: the hard part (defensible evidence logic) is built; what remains is mostly conventional platform work. |

**Classification: B — FUNCTIONAL BUT BLOCKED.**

The BYOA intelligence core is close to alpha quality. The platform around it is not.
No merge, tag or deployment should proceed until P0-1 and P0-2 are closed and CI is green.
