# GoPilot

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/kubuworks-rgb/Gopilot---GTMOS/actions/workflows/ci.yml/badge.svg)](https://github.com/kubuworks-rgb/Gopilot---GTMOS/actions/workflows/ci.yml)

An evidence-backed GTM (go-to-market) research tool. Give it a list of companies
you're already interested in and it researches each one against its own official
website, scores it with a deterministic (non-LLM) formula, and produces a brief
where every material claim links back to the exact passage and source it came
from. It answers one question, rigorously: *out of the companies I could target,
which deserve my attention, why, and how confident should I be?*

It is not a lead scraper, a company database, a chatbot, or a CRM.

```
Import accounts → Verify identity → Research → Evidence → Score
                → Opportunity brief → Human review → Export
```

## Why this exists

The claim isn't "we're better at everything." It's narrower, and the parts of it
that are actually load-bearing are tested, not just asserted:

**No paid data provider required.** BYOA (Bring Your Own Accounts) — importing
companies you already have and researching them against their own domain — needs
zero API keys. Not a trial tier, not "some features work" — the core loop runs
with `EXA_API_KEY` and `TAVILY_API_KEY` both unset, verified by CI at the
workflow level so the property can't silently regress. Most comparable tools
require a paid key before you can research a single account.

**It won't confuse one company for another.** Entity resolution runs 10 relation
types (same entity, subsidiary, acquired-by, sister brand, unrelated, ...)
against 6 claim scopes, and a claim from the wrong entity is rejected rather than
silently attached to your target. 22 tests cover 17 real near-miss pairs — the
kind of company-name collision ("Optivian" the fintech vs. "Optivian" the totally
unrelated firm two letters off) that has burned other tools in production.

**It won't tell you something it doesn't know.** When evidence for a scoring
dimension is missing, the score renormalizes across what *is* known instead of
defaulting the unknown to zero — whether that's one factor within a dimension or
every factor in it. A live run against 20 real companies found the second case
unhandled: when a dimension was *entirely* unknown, it fell through to a
confident-looking `0` instead of "not determined," which measurably changed one
account's ranking (`fly.io` scored priority 29 instead of 64 because an unknown
fit was silently treated as a confirmed poor one). Found, fixed, pinned by a
regression test built from that exact case, and re-verified against a fresh live
run — full history in
[docs/qa/LIVE_E2E_FINDINGS.md](docs/qa/LIVE_E2E_FINDINGS.md#2-p0--unknown-fit-was-scored-as-zero-and-it-changed-the-ranking-fixed).
It's kept in the README rather than quietly dropped from history, because a
repo claiming unknown-aware reasoning should show its work when that property
was once broken, not just assert it now holds.

Full honest comparison against Clay, Common Room, 6sense, and others — including
where GoPilot is *not* differentiated — is in
[docs/product/COMPETITOR_POSITIONING.md](docs/product/COMPETITOR_POSITIONING.md).

## Quickstart — zero API keys, zero signup, under 5 minutes

```bash
git clone https://github.com/kubuworks-rgb/Gopilot---GTMOS.git
cd Gopilot---GTMOS
npm install && npx gopilot
```

That's it. `gopilot` checks your Node and Python versions, installs whatever is
missing, asks up to three short questions, starts the stack, waits until it is
genuinely serving, and opens your browser at `http://localhost:3000`.

In a hurry, or scripting it? `npx gopilot -y` skips the questions and goes
straight to demo mode. Later runs remember your answers and start immediately —
`npx gopilot --reconfigure` if you want to change them.

The default needs **no API keys, no Docker, and no database.** It runs in
**fixture mode** (a deterministic offline dataset — seeded companies, fully
researched, scored, and briefed) with **demo auth**, so the browser never
redirects to a sign-in screen. You are looking at the real product surface and
the real evidence-linked scoring logic, just not live network calls yet.

The wizard offers two other modes. **Live research** runs the real pipeline —
import a domain, the gateway fetches that company's actual public pages,
extracts evidence, scores it, produces a brief — still with no search-provider
key. It needs Postgres and Redis; if Docker is running, the CLI offers to start
them for you, and that option is hidden entirely when Docker is not available.

### Manual setup

If you would rather see exactly what is happening than run a wizard, the CLI is
a convenience wrapper and nothing depends on it:

```bash
pip install -r apps/api/requirements-dev.txt
npm install
npm run dev                                                    # demo / fixture mode
```

```bash
docker compose -f deploy/docker-compose.dev-infra.yml up -d    # Postgres + Redis
npm run dev:live                                               # live research
```

This is the mode `scripts/verify_e2e_scenario.py` and
[docs/qa/LIVE_E2E_FINDINGS.md](docs/qa/LIVE_E2E_FINDINGS.md) exercise.

To try real browser sign-in (Authorization Code + PKCE against an OIDC issuer)
without registering with a provider:

```bash
npm run dev:oidc
```

This starts `services/dev_oidc`, a bundled test issuer that authenticates
nobody and refuses to start outside development — see its module docstring. It
exists so the sign-in flow is reproducible without a real identity provider.
Production points `JWT_ISSUER` at a real one; see
[docs/operations/DEPLOYMENT_RUNBOOK.md](docs/operations/DEPLOYMENT_RUNBOOK.md).

### Requirements

**Node 20.9+** (Next.js 16 requires it; 22.6+ if you want to run `npm run test`,
which uses `--experimental-strip-types`) and **Python 3.11+** (the API uses
`StrEnum` and `datetime.UTC`). `npx gopilot` checks both and tells you exactly
what to upgrade rather than failing halfway through.

## What's actually verified

Not marketing language — these are the actual current numbers, reproducible with
`npm run test`:

- **456 backend tests passing** (`pytest`, 9 skipped because they need a live
  Postgres/Redis not present in the default fixture-mode run — set
  `RUN_LIVE_DB_TESTS=1` / `RUN_LIVE_REDIS_TESTS=1` to include them), **43 web
  tests passing** (Node's built-in test runner against the real TypeScript
  modules, not reimplementations of them).
- **A real scoring bug was found on a live run, fixed, and the fix was
  re-verified live, not just unit-tested.** An account whose fit was entirely
  unknown was scored as a confident 0 instead of being excluded and
  renormalized, silently costing it more than half its priority. Fixed in
  `_priority_from` ([scoring.py](apps/api/app/services/scoring.py)), pinned by
  `test_a_fully_unknown_fit_is_excluded_rather_than_scored_zero`, and confirmed
  by tearing down and rebuilding the live stack from an empty database and
  re-running the full scenario — full before/after in
  [docs/qa/LIVE_E2E_FINDINGS.md](docs/qa/LIVE_E2E_FINDINGS.md#6-live-scoring-fix-re-verification).
- **22 tests over 17 real confusable company-name pairs**
  (`apps/api/tests/test_confusable_pairs.py`) for entity resolution. Confirmed
  to actually catch regressions: deliberately reintroducing naive brand-token
  matching broke 6 of them, including the specific case the suite was built to
  prevent.
- **A real authentication bypass was found and fixed during development, not
  hypothesized.** The invite-gate (`assert_invited`) was enforced by only one
  of the two API routers; a validly-signed but uninvited identity reached the
  fixture-mode router unchallenged. Fixed, and
  `test_both_routers_enforce_the_invite_gate` in
  `apps/api/tests/test_router_contract_parity.py` now fails the build if that
  class of bug reappears — confirmed by reverting the fix and watching the test
  go red before restoring it. Full writeup in [SECURITY.md](SECURITY.md).
- **The live-mode end-to-end scenario has actually been run against real
  infrastructure** — real Postgres, real Redis, a real worker, real HTTP
  requests to real company websites — not just fixture data. Results, including
  what passed and what didn't, are in
  [docs/qa/LIVE_E2E_FINDINGS.md](docs/qa/LIVE_E2E_FINDINGS.md).
- **`scripts/verify_oidc_flow.py`** drives the whole browser sign-in protocol
  programmatically — PKCE enforcement, code replay rejection, refresh, logout,
  tenant isolation — 12 groups, all passing, reproducible with one command
  against the bundled dev issuer.

## Architecture

Two runtime modes share one API contract:

```
Next.js → FastAPI → fixture repository                         (fixture mode)
               \-> PostgreSQL repository -> Redis -> worker    (live mode)
                                                   \-> gateway -> public adapters
```

Scoring, identity resolution, and access control are deterministic code, never
an LLM. An LLM is only used for summarization and brief composition — never for
anything the product acts on. See
[ARCHITECTURE.md](ARCHITECTURE.md) for the one-page version and
[docs/architecture](docs/architecture) for the rest — data model, agent/workflow
architecture, and the research gateway's request handling.

## Building on this

If you want to use this as the foundation for your own GTM tooling rather than
run it as-is, **[docs/EXTENDING.md](docs/EXTENDING.md)** maps the five seams —
adding a research source, changing the scoring formula, changing what counts as
valid evidence, changing qualification states, and adding an API endpoint — with
the exact file and function for each, plus the four invariants the test suite
will hold you to.

The short version of what's worth taking: the evidence pipeline. Turning a
domain into attributed, identity-checked evidence and a number you can defend is
the part that's genuinely hard, and it's the part that works without any paid
provider.

## Repository layout

```
cli/          `npx gopilot` — prerequisite checks, setup wizard, process supervision
apps/
  api/        FastAPI backend — routes, domain services, migrations, tests
  web/        Next.js command center
services/
  research_gateway/   the only thing allowed to make outbound HTTP fetches
  worker/             async job consumer for live-mode research runs
  dev_oidc/           test OIDC issuer for local dev and CI — not for production
deploy/       Docker Compose files and the Caddy TLS reverse-proxy config
docs/
  product/       what GoPilot is, why it's scoped this way, competitor positioning
  architecture/   how the system fits together
  operations/     deployment runbook, TLS/exposure requirements
  security/       data handling, threat model, source policy
  qa/             evaluation history and live-verification findings
scripts/      operational tooling — retention, deletion, verification, secret scan
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) — including the non-negotiable design
principles (deterministic scoring, evidence-backed claims, fail-closed limits,
no autonomous outbound action) that a PR is checked against regardless of how
well-written it otherwise is.

## Security

See [SECURITY.md](SECURITY.md) for how to report a vulnerability.

## License

[MIT](LICENSE).
