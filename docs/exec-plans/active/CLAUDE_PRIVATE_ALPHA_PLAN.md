# GoPilot — Private Alpha Execution Plan

**Owner:** Claude (lead engineer)
**Opened:** 2026-08-08
**Baseline commit:** `ef2467c` (`feature/byoa-core-product`)
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

¹ Environmental: `PermissionError [WinError 5]` on the `tmp_path` fixture directory.
Not code defects. Accounts for the historical "174 passed" figure.

---

## Stage status

| Stage | Work | Blocker class | Status |
|---|---|---|---|
| 0 | Forensic audit + baseline | — | **DONE** |
| 1 | P0-2 signal honesty | alpha | **DONE** |
| 2 | P0-1 authentication | alpha | **DONE** (backend); login UI outstanding |
| 3 | P1-4 migration `0007` | deployability | TODO |
| 4 | P1-1 CI | deployability | TODO |
| 5 | P1-2 / P1-6 gateway hardening | deployability | TODO |
| 6 | P1-3 worker reliability | deployability | TODO |
| 7 | P1-8 alpha limits + observability | deployability | TODO |
| 8 | P1-5 deployment path | deployability | TODO |
| 9 | P1-7 UX honesty | quality | TODO |
| 10 | P2 cleanup / simplification | maintainability | TODO |

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

## Stages 3–10

See audit §29. Summary of intent:

- **3** Additive migration `0007` for 22 model-declared indexes. Defensive creation for
  the one unique index (`uq_source_chunk_ordinal`). No migration needs *correcting* —
  the drift is one-directional and additive.
- **4** Credential-free CI. All checks already pass locally; this is workflow authoring.
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
