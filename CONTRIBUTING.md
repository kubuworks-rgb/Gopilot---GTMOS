# Contributing to GoPilot

## Non-negotiable design principles

These come from the product blueprint and are enforced by tests, not just
convention. A PR that violates one of these will be asked to change, regardless
of how well the rest of it is written.

**Deterministic where it matters.** Identity resolution, security decisions,
qualification rules, score calculation, evidence gating, and permissions are all
plain code with explicit rules — never an LLM call. An LLM is only used for
summarisation, research synthesis, claim interpretation, and brief composition —
places where the output is prose a human reads and judges, not a number the
system acts on. If you're adding a feature that computes a score, a state
transition, or an access decision, it must not depend on a model's output.
`apps/api/app/services/scoring.py` is the reference: every component is a
plain function with a documented weight, and `_breakdown_missing_aware` treats
"unknown" as a distinct case from "measured and failing" rather than defaulting
unknowns to zero.

**Every material claim traces to evidence.** A `Finding`, a score component, or
a brief claim carries `evidence_ids` pointing at a real, retrieved passage — not
a paraphrase asserted without a source. If your change produces a claim with no
evidence path, it's not done.

**Fail closed, not silent.** A limit that's exceeded returns an explicit,
machine-readable error (see `LimitExceeded` in
`apps/api/app/services/private_alpha.py`) — it never silently truncates a
result. A misconfigured production deployment refuses to start (see the
validation block in `apps/api/app/config.py`) rather than running in a degraded
but plausible-looking state.

**No autonomous outbound action.** Campaign drafts can be edited, approved, or
rejected by a human. Nothing in this codebase sends a message on its own, and a
PR that adds that capability will be rejected regardless of how it's gated.

## Before you open a PR

```bash
npm run lint
npm run typecheck
npm run test
```

That's `ruff` + `mypy` + `pytest` for the Python side
(`apps/api`, `services/research_gateway`, `services/worker`, `services/dev_oidc`),
and `eslint` + `tsc` + the Node test runner for `apps/web`. All four must pass;
CI runs the same commands and will not merge otherwise.

Also run the secret scanner if you touched anything that looks like config or a
credential:

```bash
python scripts/secret_scan.py
```

It reports only the file and line of a match, never the value, so a false
positive doesn't compound into a leak — see it in `scripts/secret_scan.py` for
the exact patterns.

## Code conventions actually used in this codebase

- **No comments unless the *why* is non-obvious.** A comment that restates what
  the code does is noise; well-named functions and variables already say what.
  A comment earns its place when it explains a hidden constraint, a subtle
  invariant, or something that would surprise a reader — see the comment on
  `_breakdown_missing_aware`'s callers in `scoring.py`, or the one on
  `completeSignIn` in `apps/web/lib/auth.ts` explaining the React StrictMode
  double-invoke.
- **Frozen dataclasses for anything that looks like config or a value object**
  (`Settings`, `Principal`, `LimitExceeded` — all `@dataclass(frozen=True)`).
  Mutable shared state is the exception, not the default.
- **Type hints everywhere**, `from __future__ import annotations` at the top of
  every Python module, and mypy runs in strict-enough mode that an untyped
  `Any` leak will usually get caught.
- **Tests exercise real behavior, not source text.** A test that checks whether
  a string appears in a file, or reimplements the logic under test as a
  parallel copy, can pass against a version that's actually broken — this
  project has hit that failure mode twice (`tests/account-filters.test.mjs` and
  `tests/auth.test.mjs` both used to do this) and fixed it both times by
  importing and calling the real module instead. Do the same: import the code
  under test, don't paraphrase it.
- **A regression test should fail without the fix.** When you fix a bug, verify
  the new test actually catches it — temporarily revert the fix, confirm the
  test goes red, then restore the fix. `test_router_contract_parity.py`'s
  invite-gate test and `tests/auth.test.mjs`'s StrictMode test were both
  verified this way.

## How PRs are reviewed

- Does it hold up against the non-negotiable principles above?
- Do the new/changed tests actually exercise the change, per the convention
  above — not just raise coverage numbers?
- Is anything silently truncated or defaulted that should instead be an
  explicit error?
- No secrets, no real credentials in test fixtures (use `secret-scan: allow`
  with an obviously-fake value if you need a credential-shaped string in a
  test — see `apps/api/tests/test_secret_scan.py` for the pattern).

## Where things live

- `apps/web` — Next.js command center (App Router, Turbopack).
- `apps/api` — FastAPI API, domain services, Alembic migrations, tests.
  `api/routes.py` is the fixture-mode router, `api/live_routes.py` is the real
  one; `tests/test_router_contract_parity.py` enforces that they agree on
  every shared endpoint.
- `services/research_gateway` — isolated public-source adapters, SSRF/URL
  policy, and content-size limits. The only thing allowed to make outbound
  fetches.
- `services/worker` — the async job consumer for live-mode research runs.
- `services/dev_oidc` — a test OIDC issuer for local development and CI. It
  authenticates nobody and refuses to start when `APP_ENV=production`.
- `docs/architecture` — how the system fits together.
- `docs/product` — what it's for and why it's scoped the way it is.
- `docs/operations` — how to actually deploy and run it.
