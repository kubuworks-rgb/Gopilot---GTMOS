# GoPilot — Intelligence Quality Improvement

Last updated: 2026-07-25

## Classification

`B — IMPROVED BUT NOT READY`

The sanitized rerun proved both direct Exa REST and the production MCP
transport with authenticated HTTP 200 responses and three relevant results
each. The previous D was an observability failure in the temporary helper, not
a current credential, account, network, payload, or MCP failure. Repeated
reliability and the clean holdout did not run during the one-time credential
lifetime, so no quality pass or merge is allowed.

## Exa Diagnostic

| Check | Result |
| --- | --- |
| Direct REST | `PASS` |
| MCP | `PASS` |
| Production adapter selected | Exa remote MCP |
| REST HTTP status | `200` |
| MCP HTTP status | `200` |
| Error tag | unavailable |
| REST category | `EXA_REST_AUTHENTICATED_PASS` |
| MCP category | `EXA_MCP_AUTHENTICATED_PASS` |
| REST request ID | `b04ee19d2693f2c3f8efa2dc29c03def` |
| MCP request ID | unavailable |

Direct REST returned three relevant GitHub results in 2823 ms. A separately
initialized MCP session completed initialization, tool discovery, and
`web_search_exa` with the same three relevant results in 3514 ms. Since the
existing gateway boundary and production MCP path are reliable, MCP remains
the authenticated primary; REST remains the independent control.

Root cause: the previous temporary runner collapsed its failure before
retaining a safe category. The replacement classifier retains only the
allowlisted transport, endpoint class, status, safe tag/category, sanitized
request ID, latency, content type, authentication-attempt flag, and timestamp.
It never retains request headers or raw provider bodies.

## Search Providers

Primary: Exa remote MCP behind `GeneralSearchProvider`.

Auth mode: keyed `x-api-key`. The rotated credential was supplied once through
a secure PowerShell prompt and existed only in the acceptance process. The
helper removed the process variable, zero-freed its secure-string buffer, and
deleted itself and its temporary runner. No credential value or raw provider
response was printed, logged, committed, or persisted.

Secondary: Tavily Search API.

Auth mode: keyed Bearer token; `TAVILY_API_KEY` is not configured.

Fallback behavior: the composite provider falls back after a primary error or
an insufficient result count. Typed diagnostics expose
`completed_with_provider_fallback`, provider attempts, authentication state,
result count, latency, and fallback use. Production acceptance requires
`tldextract==5.3.0` and at least one keyed provider. Exa is primary when
configured; Tavily is optional and used as fallback when configured.

Reliability: controlled primary-exhaustion/secondary-success regression passes.
One direct REST request and one complete MCP search passed. Repeated bounded
production reliability testing did not run before the one-time credential was
scrubbed.

## ICP Model

Hard criteria:

- Official company domain.
- B2B software model.
- India connection.
- Not a direct support-automation competitor.

Soft criteria:

- Support/customer-success operations.
- Preferred employee range.

Unknown handling: unknown is a separate three-valued state and is never
converted to false. Full hard-criterion matches with unresolved soft evidence
become `QUALIFIED_WITH_UNCERTAINTY`. Criteria are persisted under
`supportpilot-icp-v2`.

## Discovery Funnel

```text
raw discovered: not run — credential lifetime ended after diagnostics
prequalified: not run — credential lifetime ended after diagnostics
enriched: not run — credential lifetime ended after diagnostics
deep researched: not run — credential lifetime ended after diagnostics
qualified: not run — credential lifetime ended after diagnostics
borderline / qualified with uncertainty: not run
rejected: not run
top 10: not run
```

The implemented funnel performs broad multi-query collection, PSL-aware result
classification, query/provider agreement scoring, a configurable
prequalification floor, and deep research only for the highest-scoring
candidates. Every stage and its query/provider provenance is persisted.

## Firmographics

Sources: `CompanyFirmographicProvider` abstraction with a conservative
company-level public-evidence fallback and a configuration point for a licensed
provider. No private-person enrichment is performed.

Coverage: unavailable until the holdout runs.

Unknown rate: unavailable until the holdout runs. Missing employees,
geography, business model, and industry remain explicitly `UNKNOWN`, with
attribute-level precision, confidence, source IDs, and rationale.

## Domain Quality

Accuracy: controlled matrix 20/20 (100%).

Errors: no controlled failures. `go.hrone.cloud` resolves to canonical
`hrone.cloud`; directory and news hosts cannot become canonical company
domains. `tldextract==5.3.0` is installed in `C:\Python313\python.exe`; the
resolver uses its packaged PSL snapshot without runtime network access or a
disk cache.

## Signal Evaluation

Persisted signals: unavailable for the live holdout.

Precision: unavailable for the live holdout.

Known-positive recall: live control did not run during the one-time credential
lifetime.

Entity-match errors: zero across controlled HROne/HR One and robotaxi IPO
regressions.

Date errors: zero across controlled parsing and event-page gating regressions.

Signals now use event-specific queries, require entity proof, persist event
confidence separately from GoPilot relevance, reject vendor-marketing signal
evidence, and permit a valid no-signal/monitor outcome.

## Top 10

No top-10 QA table exists because the clean SupportPilot V2 holdout did not run
after the successful transport diagnostics.

| Rank | Company | Domain | ICP | Claims | Signal | Brief | Result |
| ---: | --- | --- | --- | --- | --- | --- | --- |
| — | Not run | Not run | Not run | Not run | Not run | Not run | Acceptance incomplete |

## Previous vs New Metrics

| Metric | Before | After | Target |
| --- | ---: | ---: | ---: |
| Real company/product rate | 100% | Not measured | 100% |
| Canonical-domain correctness | 90% | 100% controlled; live not measured | at least 98% |
| Useful top-account ICP relevance | 20% | Not measured | at least 80% |
| Fully supported important claims | 30% | Not measured | at least 95% |
| Unsupported important claims | 30% | Not measured | under 5% |
| Primary evidence-link success | 100% | Not measured | at least 98% |
| Duplicate rate | 0% | Not measured | under 5% |
| False entity signal attachment | 1 known failure | 0 controlled failures | 0% |
| Signal precision | 0 of 1 | Not measured | at least 90% preferred |
| Mean brief usefulness | 1.0 / 3 | Not measured | at least 2.0 / 3 |

## Opportunity Briefs

Mean score: unavailable until the holdout and manual QA run.

Useful examples: controlled integration confirms evidence-linked known facts,
explicit unknowns, research-candidate gating, and no-signal monitor behavior.

Failure examples: none can be selected from a holdout that did not start.
Briefs now separate verified facts, unknowns, hypotheses, current events, event
confidence, relevance, and priority action.

## Founder Value

YES:

- Inspect why an account qualified and which criteria remain unknown.
- See canonical identity, source role, candidate provenance, deterministic
  scores, priority band, and linked evidence.
- Treat no current signal as a legitimate monitor outcome.

MAYBE:

- Candidate precision, live signal recall, and brief usefulness are promising
  by controlled gates but unproven on the clean holdout.

NO:

- No autonomous sending, social-cookie scraping, private-person enrichment, or
  production-alpha claim.
- No claim that Phase 4 is ready to merge.

## Tests

- Python/API/gateway: 98 passed, 2 skipped in the ordinary suite.
- PostgreSQL/Redis integration after migration: 2 passed.
- Focused intelligence-quality and Exa diagnostic regression: 65 passed.
- Domain matrix: 20/20, plus the HROne subdomain case.
- Web: 2 passed.
- Research-gateway security: 10 passed.
- Alembic: `0006_intelligence_quality (head)`.
- Ruff and Mypy: passed.
- ESLint, TypeScript, and Next.js production build: passed.
- Docker Compose: configuration valid; PostgreSQL healthy and Redis running.
- `git diff --check`: passed.
- Credentialed diagnostics: direct REST and initialized MCP search both passed
  with HTTP 200 and three relevant public results. Typed failure and redaction
  regressions pass. Repeated reliability, precision, positive-signal control,
  holdout, and top-10 QA did not run during the credential lifetime.

## Git

Branch: `feature/intelligence-quality-improvement`

Commits:

- `a5838a7` — preserve Phase 3 real GTM intelligence acceptance.
- `02e2727` — authenticated primary/secondary provider fallback.
- `c905119` — identity, qualification, discovery, scoring, briefs, UI, migration,
  and regression suite.
- `a475062` — allow either authenticated search provider at acceptance.
- `a726e15` — record the credentialed acceptance preflight.
- `dd3df22` — stabilize PSL resolution and record the prior acceptance result.

Remote SHAs: no Phase 4 remote SHA; the branch has not been pushed.

Current typed-diagnostic changes remain uncommitted because the final
classification is not A.

Merge status: **DO NOT MERGE**. No merge to `develop` or `main`, and no public
deployment.

## Known Limitations

- P0: the authenticated transport is proven, but the full quality acceptance
  was not executed during the one-time process-local credential lifetime.
- P1: authenticated repeat reliability, first-30 precision, known-positive
  live signal recall, clean SupportPilot V2, funnel counts, and manual top-10
  QA did not execute.
- P2: live evidence-link reachability and founder-value metrics remain
  unmeasured.
- `TAVILY_API_KEY` is optional and `NOT_CONFIGURED`; the acceptance gate
  correctly uses OR semantics and did not require it.
- The optional licensed firmographic provider has an interface and config gate
  but no licensed vendor was selected or configured.
- `tldextract==5.3.0` is installed and verified in the exact runtime used by
  the API, gateway, tests, and harness.

## Final Question

> Would a real founder receive a meaningfully better shortlist than manual broad web searching and spreadsheet research?

**NO — not yet proven.**

The implementation makes materially better decisions in controlled tests and
both authenticated Exa transports now have live proof. But the required
authenticated holdout and top-10 manual QA did not run, so founder value cannot
honestly be promoted from an engineering improvement to an acceptance result.
