# Live Research Implementation Plan

Last updated: 2026-07-23

Branch: `feature/live-research-engine`

## Objective

Convert GoPilot's deterministic demo into a strict dual-mode system:

- `RESEARCH_MODE=fixture` keeps the existing deterministic acceptance path and
  displays `DEMO DATA`.
- `RESEARCH_MODE=live` uses PostgreSQL, Redis jobs, the Research Gateway, and real
  public-source adapters. It never falls back to fixtures.

## Verified baseline

- `origin/develop` and released `origin/main` have identical trees.
- Baseline: 18 Python tests and 2 web tests pass.
- Ruff, ESLint, Mypy, TypeScript, and the Next.js production build pass.
- Fixture and live routers are selected explicitly at startup.
- PostgreSQL, Redis, the worker, and the gateway are now executable bindings.

## Decisions

1. Preserve public API response shapes and the working command-center UI.
2. Select fixture or live services explicitly at startup; provider failure is a
   typed partial/failed live run, never a fixture response.
3. Keep subprocesses inside gateway adapters with explicit argument arrays,
   bounded output, timeouts, and a sanitized environment.
4. Pin Agent Reach `v1.4.2` at commit
   `97e9e63f42c89cbf527386343723c1fde610b4cb` (MIT), reviewed from upstream source
   on 2026-07-23. This version supports `doctor --json`.
5. Treat Agent Reach as capability health/setup. Search, webpage, GitHub, RSS, and
   YouTube retrieval use separately allowlisted adapters.
6. Use additive Alembic migrations. Do not rewrite published migration history.
7. Persist source text, hashes, passages, evidence, findings, ICPs, accounts,
   signals, score factors, briefs, jobs, tool calls, and audit events.
8. Without a configured LLM, source retrieval and deterministic evidence
   extraction remain available; unsupported synthesis returns a typed error or
   conservative evidence-grounded output rather than invented facts.

## Phase status

| Phase | Scope | Status | Verification |
|---|---|---|---|
| 0 | Audit, branch, baseline | Complete | Full baseline green |
| 1 | PostgreSQL runtime and Redis jobs | Complete | Migration applied; 27 tables; queue round trip |
| 2 | Fixture/live provider separation | Complete | No live-to-fixture imports or fallback |
| 3 | Agent Reach pin and capability health | Complete | v1.4.2 doctor JSON executed |
| 4 | Search/web/GitHub/RSS/YouTube gateway | Complete | Typed routes and failure modes |
| 5 | Normalization, hashing, dedupe | Complete | Contract tests and durable integration |
| 6 | Evidence extraction and validation | Complete | Exact-passage DB assertions |
| 7 | Planning and market intelligence | Complete | Bounded durable workflow |
| 8 | Three evidence-backed ICPs | Complete | Integration assertion |
| 9 | Account discovery and research | Complete | Durable integration assertion |
| 10 | Intent signals and decay | Complete | Evidence-only signal path |
| 11 | Deterministic scoring | Complete | Versioned snapshots and factors |
| 12 | Briefs, evidence UI, actions | Complete | UI/API actions wired |
| 13 | Live proof, security, docs, release | In progress | Public proof complete; final gates and publication pending |

## Public live proof

The approved two-stage GDELT smoke completed on 2026-07-23:

- Kubu Works result: `NO_RELEVANT_RESULTS`. All four approved queries ultimately
  received HTTP 200 and returned zero articles. No irrelevant or fixture records
  were persisted. A fully successful zero-result run terminates as `completed`
  with stage `no_relevant_results`; it is not mislabeled as a provider failure.
- Known-positive control: query `"OpenAI"`, backend `gdelt-doc-2`, HTTP 200, five
  real results before and after relevance filtering.
- Isolated control run `3fc0f321-5a58-4864-9969-0f3e40e828fb` safely fetched and
  normalized three public articles, persisted 31 overlapping chunks, six evidence
  facts, and six findings.
- Two other returned URLs timed out. Their failures were recorded as
  `FETCH_TIMEOUT`; no bypass or fixture substitution occurred.
- All six evidence passages were programmatically found in both their source
  documents and at least one persisted source chunk. The evidence API resolved a
  chunk ID for every fact.
- Fixture backend, fixture provenance, and the fixture-only names NovaLedger,
  SignalForge AI, and CloudKite each had a zero count.

## Provider strategy

GDELT remains a news-intelligence channel for funding, announcements, expansion,
leadership, partnerships, and other time-sensitive signals. It is not the only
search provider. The Research Gateway retains separate general-web, safe-reader,
GitHub, RSS, and YouTube capabilities. A stronger general-web discovery provider
is still needed for official websites, products, pricing, careers, and technical
documentation.

## Remaining operational notes

- GitHub CLI is installed but its Agent Reach doctor check reports unauthenticated.
- YouTube transcript retrieval is optional and returns
  `YOUTUBE_TRANSCRIPT_UNAVAILABLE` when no public subtitle file is downloaded.
