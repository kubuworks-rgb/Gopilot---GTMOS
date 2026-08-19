# GoPilot — Private Alpha Execution Plan

**Owner:** Claude (lead engineer)
**Opened:** 2026-08-08
**Baseline commit:** `ef2467c` (`feature/byoa-core-product`)
**This branch:** `feature/private-alpha-hardening`

## Branch split

Work is separated by scope so PR #1 stays focused on the verified BYOA core.

| Branch | Contains | State |
|---|---|---|
| `feature/byoa-core-product` (PR #1, draft) | Signal-honesty fix, takeover audit, credential-free CI | pushed — **CI green, all 4 jobs** |
| `feature/private-alpha-hardening` | OIDC authentication, migration `0007`, migration-parity tests, CI's `alembic check` and auth steps, and all later hardening | branched from PR #1 |
| `backup/takeover-20260808` + tag `takeover-checkpoint-20260808` | The unsplit original three commits | retained; nothing lost |

Two CI steps are deliberately absent from PR #1 because they depend on work that is
not part of the BYOA core, and would fail there for reasons that PR does not
introduce: `alembic check` (needs `0007`) and the authentication tests.

### First CI run found a real problem

Three tests in `test_acceptance_orchestration.py` shell out to `powershell.exe` to
exercise the historical Phase 5 acceptance scripts. They test the QA harness, not
the product, and cannot run on Linux. They are now skipped where that interpreter is
absent — deleting them would discard preserved QA evidence.

The first fix was wrong and CI caught it: it accepted `pwsh` as sufficient, but
GitHub's Ubuntu runners ship PowerShell Core, so the guard passed and the tests still
invoked a `powershell.exe` that did not exist. The gate is now on the interpreter
these tests actually call.

This is a live symptom of the acceptance-harness coupling in audit §Y/§22 — QA
scripts entangled with the product suite. Archiving them stays P2.

**Sequencing:** hold PR #1 open and draft until it is reviewed. After it merges into
`develop`, rebase this branch onto the updated `develop` and continue. Nothing merges
automatically.

**Source audit:** [CLAUDE_PROJECT_TAKEOVER_AUDIT.md](../../qa/CLAUDE_PROJECT_TAKEOVER_AUDIT.md)
**Target:** Limited private alpha of `BYOA_CORE`. Not a public launch. Not an
autonomous-discovery release.

**Current classification: B — FUNCTIONAL BUT BLOCKED.**

---

## Baseline measured at takeover (not reported — run)

| Check | Result |
|---|---|
| `pytest apps/api/tests services/research_gateway/tests` | 172 passed, 3 skipped, 2 errors¹ |
| `ruff check` | pass |
| `mypy` (52 source files) | pass |
| `eslint` | pass |
| `tsc --noEmit` | pass |
| `npm test --workspace apps/web` | 4/4 pass |
| Alembic index drift | 22 missing-in-migration, **0 schema defects** |
| CI | **absent** — no `.github/` |
| Deployable artifact | **absent** — compose has infra only |

¹ **Now resolved.** The cause was a corrupted `C:\Users\LENOVO\AppData\Local\Temp\
pytest-of-LENOVO` directory whose ACL could not even be read, left behind by an
earlier run. It cannot be deleted without elevation, but pointing pytest elsewhere
clears it:

```powershell
$env:PYTEST_DEBUG_TEMPROOT="<any writable directory>"
```

With that set the suite reports **0 errors**. This also explains the historical
"174 passed" figure — it was 172 plus these two. CI on Linux is unaffected.

---

## Stage status

| Stage | Work | Blocker class | Status |
|---|---|---|---|
| 0 | Forensic audit + baseline | — | **DONE** |
| 1 | P0-2 signal honesty | alpha | **DONE** |
| 2 | P0-1 authentication | alpha | **DONE** (backend); login UI outstanding |
| 3 | P1-4 migration `0007` | deployability | **DONE** |
| 4 | P1-1 CI | deployability | **DONE** |
| 5 | P1-2 / P1-6 gateway hardening | deployability | **DONE** |
| 6 | P1-3 worker reliability | deployability | **DONE** |
| 7 | P1-8 alpha limits + invite-only | deployability | **DONE** |
| 8 | P1-5 deployment path | deployability | **DONE** (re-verify blocked) |
| 9 | Frontend OIDC sign-in | alpha | **DONE** |
| 10 | P1-7 UX honesty | quality | TODO |
| 11 | P2 cleanup / simplification | maintainability | TODO |

## What the first real deployment proved — and broke

The whole stack was built and run for real (postgres, redis, migrate, gateway, api,
worker, web — all healthy, migrations applied before any service took traffic), and
the smoke test drove it through the web proxy against **real company websites**.

It passed the invite gate, workspace, product, BYOA run, unsafe-domain rejection,
import, duplicate detection, worker research, and evidence-backed briefs with no
cross-company contamination.

Then it found two defects the entire fixture suite had missed:

1. **No imported account could ever leave `IDENTITY_REVIEW_REQUIRED`.** Import
   writes a "not yet verified" marker and nothing cleared it once research
   verified the domain. `decide_brief_state` returns `IDENTITY_REVIEW_REQUIRED`
   whenever any warning is present, so the core BYOA workflow could not reach
   `MONITOR`, `RESEARCH_CANDIDATE` or `FOUNDER_READY` **at all**.
2. **A real company was reported as unverifiable.** `_sentences` discarded any
   segment over 700 characters, so `sqlalchemy.org` — whose homepage is one long
   run with almost no full stops — yielded zero passages, and the account was
   labelled "the supplied official domain could not be verified". Untrue: the
   domain had been fetched and matched. Identity verification was conflated with
   evidence extraction.

Both are fixed with regression tests
(`apps/api/tests/test_byoa_identity_verification.py`). This is the clearest
argument in the whole takeover for running the real thing: an offline evaluation
over curated fixtures reported "BYOA CORE QUALITY PASS" while the deployed product
could not move an account out of identity review.

### Re-verified after the fixes

Docker Desktop's engine died mid-run; `wsl --shutdown` and a relaunch recovered it
without needing elevation. The stack was rebuilt from scratch on a clean volume and
the smoke test re-run end to end:

```
[8]  sqlalchemy.org  state=RESEARCH_CANDIDATE  fit=0 intent=70 conf=94
     python.org      state=RESEARCH_CANDIDATE  fit=0 intent=70 conf=94
...
SMOKE TEST PASSED
```

Both accounts now leave identity review, and `sqlalchemy.org` verifies with 2 real
source documents instead of being called unverifiable.

One assertion in the smoke test was wrong, not the product: it demanded an empty
campaign subject for non-`FOUNDER_READY` accounts. A draft row does exist as a
"Research checkpoint", but it is never approved, the API refuses to edit or approve
it (409, step 10), and the UI shows "No outreach draft generated". The assertion now
tests that gate rather than the subject string.

Also verified against the running stack:

- `scripts/delete_workspace_data.py` — dry run, cross-tenant refusal, then a real
  delete leaving **zero orphans** across accounts, sources, evidence, briefs, audit
  and memberships, while a second workspace's data was untouched.
- The exact command in the runbook, run inside the `api` container.

---

## Stage 1 — Signal honesty (P0-2)

**Defect.** `live_research.py:2376` exempts `CUSTOMER_GROWTH_INDICATOR` from the
dated-or-event-page requirement, and `:402` falls `observed_at` back to `retrieved_at`.
A static "Trusted by 100+ customers" homepage line therefore becomes a
maximum-recency (`signal_decay = 1.0`, `signal_recency = 100`) current intent signal,
and can carry an account to `FOUNDER_READY` — unlocking its outreach draft.

**Why first.** Pure domain logic; no infrastructure dependency. Every later quality
measurement is invalid while intent freshness is fabricated.

**Approach.**
1. Distinguish *event date* from *retrieval date*. Only a genuine published/event date
   may drive recency.
2. Remove the `CUSTOMER_GROWTH_INDICATOR` exemption — no signal type is exempt from
   event semantics.
3. A signal with no derivable event date contributes **no** intent. `NO_SIGNAL` stays a
   valid, correct outcome.
4. Regression tests: static homepage ⇒ no signal; dated press release ⇒ signal with
   real decay; undated `/blog` ⇒ no fabricated freshness.

**Invariants preserved:** unknown ≠ false; no account is forced into `FOUNDER_READY`;
deterministic scoring; no LLM numerics.

### Outcome (2026-08-08)

Implemented:
- `signal_event_date(source)` returns `published_at` or `None` — never retrieval time.
- The `CUSTOMER_GROWTH_INDICATOR` exemption is removed; **no signal type is exempt**
  from event semantics. A source with neither a published date nor an event-semantics
  URL produces no signal.
- `_signals_from_facts` returns `(signal_type, fact, event_date | None)`.
- `score_account(signal_recency: float | None)`; intent now uses
  `_breakdown_missing_aware`, so unknown recency renormalizes onto signal strength
  instead of being scored as either a fresh event or a penalty — the same treatment
  fit already gave unknown company size.
- Staleness is measured against the real event date; undated signals keep base
  strength rather than borrowing fetch-time freshness.

Proven, not assumed — the same input through both code paths:

| | pre-fix | post-fix |
|---|---|---|
| `"Trusted by 100+ customers"` on a static homepage | `CUSTOMER_GROWTH_INDICATOR`, recency **100/100** | **no signal** |

Verification: `179 passed, 3 skipped, 2 errors` (same 2 environmental `tmp_path`
errors as baseline; +7 new tests in `apps/api/tests/test_signal_event_semantics.py`).
`ruff` clean, `mypy` clean across 52 files.

Note: the pre-existing suite passed unchanged against the fix, which confirms it never
covered this defect.

---

## Stage 2 — Authentication (P0-1)

Provider-neutral JWT/JWKS verification: issuer, audience, algorithm allowlist,
`exp`/`nbf`, unknown-`kid` rejection, cached JWKS with rotation, fail-closed.
`DEMO_AUTH_ENABLED` permitted only outside production. One principal resolver shared by
both routers. Frontend sends a bearer token.

`.env.example` already declares `SUPABASE_*` JWKS variables that **no code reads** —
the vendor appears chosen but unwired. Core domain logic stays vendor-neutral; vendor
specifics live in configuration only.

Tests: valid / expired / wrong issuer / wrong audience / unknown kid / bad signature /
unsigned / forbidden algorithm / missing / malformed / JWKS unavailable / JWKS cached /
JWKS rotated / no membership / **cross-workspace access denied** / demo auth rejected in
production. Test keys only.

**Note from the audit:** tenant-isolation *logic* is already correct — `resolve_membership`
enforces membership and every resource route re-checks `workspace_id`. Fixing
authentication fixes tenant isolation. No per-route rework is required.

### Outcome (2026-08-08) — decision: provider-neutral OIDC/JWKS

Chosen because it is free (works with any issuer's free tier, including the Supabase
project the `.env` template already anticipated), reliable (a standard every IdP
implements), and secure without the team owning password, session and recovery
handling. Vendor choice stays in configuration; no vendor name appears in domain logic.

Implemented:
- `apps/api/app/security/jwks.py` — TTL-cached JWKS with single-refresh rotation
  handling, rate-limited so unknown key IDs cannot amplify requests at the issuer.
- `apps/api/app/security/tokens.py` — fail-closed verification. The algorithm is
  pinned from the configured allowlist and **never read from the token**, so
  `alg: none` and HMAC-confusion tokens are rejected before any signature check.
  Requires `exp`, `iss`, `aud`, `sub`; verifies `nbf` and `iat`.
- `config.py` — `AUTH_MODE`, `JWT_ISSUER`, `JWT_AUDIENCE`, `JWKS_URL`,
  `JWKS_CACHE_TTL_SECONDS`, `JWT_ALGORITHMS`. Production requires `oidc`;
  configuration rejects symmetric algorithms outright.
- One shared `authenticated_user_id` resolver for both routers. **Under `oidc` the
  `X-Demo-User` header is ignored entirely** — it cannot impersonate anyone.
- `apps/web/lib/api.ts` attaches `Authorization: Bearer …` when a token is present.

Verification: **210 passed**, 3 skipped, same 2 environmental errors. 31 new auth
tests covering the full §U matrix, including a **hand-forged** HMAC algorithm-confusion
token (PyJWT refuses to construct one, so the attack was built by hand to prove our
verifier rejects it rather than that a library declined to create it).

**Outstanding before alpha:** the web app has no login screen. The API verifies
tokens correctly, but the browser has no way to obtain one. Tracked in Stage 9.

---

## Stage 3 — Migration `0007` (P1-4) — DONE

Additive only: 21 model-declared performance indexes, `if_not_exists=True`, no rows
touched.

**Diagnosis corrected twice during this work, both times because the verification
method was too weak:**

1. Parsing `downgrade()` alongside `upgrade()` invented two schema defects. Neither
   was real; `0005` already widens `uq_source_run_hash` correctly.
2. Source pattern-matching cannot see constraints declared inline in `create_table`,
   so `uq_source_chunk_ordinal` looked like an unenforced uniqueness invariant. It is
   not — migration `0002` creates it as a `UniqueConstraint`, which PostgreSQL backs
   with a unique index of the same name. The models declare it as a unique `Index`;
   the two differ in kind, not in effect. `0007` deliberately leaves it alone, and the
   row-deduplication statement drafted on the false premise was removed.

Replaced the throwaway parser with `apps/api/tests/test_migration_index_parity.py`,
which **executes** every `upgrade()` against a recording stub of `alembic.op`. That
captures every call style — literal, helper, loop, inline constraint — and needs no
database. Nine tests now assert index, column, and table parity plus a linear
revision chain. Verified to fail without `0007` and pass with it.

Column and table parity are clean, which is what gives confidence that CI's
`alembic check` step (which needs a live database) will pass on first run.

## Stage 4 — CI (P1-1) — DONE

`.github/workflows/ci.yml`, four jobs, no provider credentials anywhere
(`EXA_API_KEY` and `TAVILY_API_KEY` are pinned empty at workflow level):

- **backend** — ruff, mypy, pytest
- **frontend** — eslint, tsc, tests, Next.js build
- **database** — Postgres 17 + Redis, `alembic upgrade head`, `current`, offline SQL,
  a downgrade/upgrade round trip, `alembic check`, and the live DB integration tests
- **security** — gateway security tests, authentication tests, whitespace, secret scan

Added `scripts/secret_scan.py`: reports only file and line, **never the matched
value**, so a leak is not compounded into CI logs. It is itself tested
(`test_secret_scan.py`) against planted synthetic credentials — a scanner that never
fires is worse than none, because it looks like coverage. Those tests caught a
malformed AWS key in my own fixture.

## Stages 5–10

See audit §29. Summary of intent:

- **5** Gateway token required outside local dev (currently a no-op when unset); pin the
  validated IP to close the DNS-rebinding TOCTOU.
- **6** Worker: reliable claim, failure recorded on the row, `workspace_id` / `actor_id`
  threaded through `execute_job`.
- **7** Configurable caps with explicit errors — never silent truncation. Safe
  operational events only.
- **8** Dockerfiles, full compose, `.env.private-alpha.example`, runbook, smoke test.
- **9** Real run state on the dashboard (currently hardcoded ✓ steps); simplified nav;
  render rejected-evidence items.
- **10** Archive historical harnesses, delete the LangGraph scaffold, split the monolith.

---

## Standing constraints

- No Exa or Tavily. Do not request `EXA_API_KEY` / `TAVILY_API_KEY`.
- Do not weaken identity, evidence, or founder-ready gates.
- No fixture fallback in live mode. No autonomous outbound sending.
- Autonomous discovery stays experimental and untouched.
- Do not merge PR #1, merge to `main`, tag, or deploy.
- No force push, reset, rebase, or history rewrite.
- Never commit secrets.
- Protect the subsystems listed in audit §27.
