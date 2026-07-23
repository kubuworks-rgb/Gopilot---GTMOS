# MVP Build Plan

Last updated: 2026-07-23

| Phase | Scope | Status | Gate |
|---|---|---|---|
| 0 | Repository and architecture docs | Complete | Required docs/config exist |
| 1 | API/web foundation and auth boundary | Complete for demo | Health and tenant tests pass; production auth fails closed |
| 2 | Evidence foundation and fixtures | Complete | Evidence integrity tests pass |
| 3 | Research gateway safety | Complete boundary | SSRF/injection tests pass; live adapters deferred |
| 4-8 | Research, ICP, accounts, scores, brief | Complete in fixture mode | Acceptance flow and LangGraph test pass |
| 9-10 | Approval, CSV, audit | Complete | Edit/approve/export/audit tests pass |
| 11 | Full QA and hardening | Complete for vertical slice | Tests/lint/types/build/browser smoke pass |

Decisions: fixture mode is the complete offline acceptance path; production-shaped
database and worker boundaries coexist with it. Live adapters never fall back to
fixtures. Agent Reach v1.4.2/97e9e63 is reviewed but not installed at request time.

Final verification: 18 Python tests and 2 frontend contract tests pass; Ruff, ESLint,
Mypy (29 source files), TypeScript, Next.js 16.2.10 production build, Alembic offline
SQL generation, Docker Compose validation, API health, and HTTP 200 web smoke pass.
Rendered browser checks confirm GoPilot branding, ICP reselection, refreshed ranked
accounts, account-brief provenance, and the evidence drawer. Remaining production
integrations are recorded in `README.md`.
