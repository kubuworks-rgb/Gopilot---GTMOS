# MVP Build Plan

Last updated: 2026-07-23

| Phase | Scope | Status | Evidence |
|---|---|---|---|
| 0 | Repository/docs/baseline | Complete | Baseline gates green on `develop` |
| 1 | PostgreSQL and Redis foundation | Complete | Alembic head applied; 27 public tables; Redis job round trip |
| 2 | Fixture/live provider separation | Complete | Import-time router selection; explicit provider failures |
| 3 | Research Gateway and Agent Reach | Complete | Pinned v1.4.2 package, doctor JSON, typed adapters, URL policy |
| 4 | Source normalization and evidence | Complete | Hash/dedupe/chunks/exact-passage validation |
| 5 | Bounded workflow and observability | Complete | Durable stages/tasks/agent runs/tool calls/errors |
| 6 | ICP and account intelligence | Complete | Exactly three ICPs; durable accounts/signals/scores/briefs |
| 7 | Live UI actions | Complete | Start, select, refresh, research, regenerate, capability health |
| 8 | Local durable integration | Complete | PostgreSQL research-to-account test and Redis test pass |
| 9 | Public-web live smoke | Complete | GDELT control run persisted 3 sources, 31 chunks, 6 evidence facts, and 6 findings |
| 10 | Final gates and publication | In progress | Release only after every local gate is green |

Important boundary: the completed integration test uses a test-only controlled
transport to prove the production persistence and orchestration path. The approved
2026-07-23 public smoke separately proved real GDELT search, safe public fetching,
normalization, PostgreSQL persistence, and exact evidence lineage. The Kubu-specific
queries returned `NO_RELEVANT_RESULTS`; the isolated `"OpenAI"` control run proved
the transport without contaminating Kubu research.
