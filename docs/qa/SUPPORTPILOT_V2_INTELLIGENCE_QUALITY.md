# GoPilot — Intelligence Quality Improvement

Last updated: 2026-07-25

## Classification

`CONFIG_REQUIRED_FOR_PRODUCTION_ACCEPTANCE`

This is not an A, B, C, or D quality classification. The clean holdout did not
start because authenticated production providers and the pinned PSL dependency
are not configured in this environment. Per the Phase 4 policy, no anonymous
or degraded result is accepted as production evidence, no quality pass is
claimed, and no merge is allowed.

## Search Providers

Primary: Exa remote MCP behind `GeneralSearchProvider`.

Auth mode: keyed `x-api-key`; credential presence passed the 2026-07-25
preflight. The value was neither logged nor persisted by the acceptance run.

Secondary: Tavily Search API.

Auth mode: keyed Bearer token; `TAVILY_API_KEY` is not configured.

Fallback behavior: the composite provider falls back after a primary error or
an insufficient result count. Typed diagnostics expose
`completed_with_provider_fallback`, provider attempts, authentication state,
result count, latency, and fallback use. Production acceptance fails closed if
either keyed route is absent.

Reliability: controlled primary-exhaustion/secondary-success regression passes.
Repeated authenticated public-web reliability testing is config-blocked.

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
raw discovered: config-blocked
prequalified: config-blocked
enriched: config-blocked
deep researched: config-blocked
qualified: config-blocked
borderline / qualified with uncertainty: config-blocked
rejected: config-blocked
top 10: config-blocked
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
domains. The pinned `tldextract` dependency could not be installed because
third-party package installation approval was denied. A bounded degraded
resolver supports local gates; installed environments use the packaged PSL
snapshot without runtime network access.

## Signal Evaluation

Persisted signals: unavailable for the live holdout.

Precision: unavailable for the live holdout.

Known-positive recall: live control blocked by provider configuration.

Entity-match errors: zero across controlled HROne/HR One and robotaxi IPO
regressions.

Date errors: zero across controlled parsing and event-page gating regressions.

Signals now use event-specific queries, require entity proof, persist event
confidence separately from GoPilot relevance, reject vendor-marketing signal
evidence, and permit a valid no-signal/monitor outcome.

## Top 10

No top-10 QA table exists because the clean SupportPilot V2 holdout correctly
stopped at provider preflight.

| Rank | Company | Domain | ICP | Claims | Signal | Brief | Result |
| ---: | --- | --- | --- | --- | --- | --- | --- |
| — | Not run | Not run | Not run | Not run | Not run | Not run | Config blocked |

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

- Python/API/gateway: 63 passed, 2 skipped in the ordinary suite.
- PostgreSQL/Redis integration after migration: 2 passed.
- Intelligence-quality plus gateway contract regression: 40 passed.
- Domain matrix: 20/20.
- Web: 2 passed.
- Alembic: `0006_intelligence_quality (head)`.
- Ruff and Mypy: passed.
- ESLint, TypeScript, Next.js build: see final engineering-gate run.
- `git diff --check`: passed.
- SupportPilot V2 preflight: authenticated Exa was detected, then correctly
  returned `CONFIG_REQUIRED_FOR_PRODUCTION_ACCEPTANCE` for missing Tavily and
  PSL configuration; no live run started.

## Git

Branch: `feature/intelligence-quality-improvement`

Commits:

- `a5838a7` — preserve Phase 3 real GTM intelligence acceptance.
- `02e2727` — authenticated primary/secondary provider fallback.
- `c905119` — identity, qualification, discovery, scoring, briefs, UI, migration,
  and regression suite.

Remote SHAs: no Phase 4 remote SHA; the branch has not been pushed.

Merge status: **DO NOT MERGE**. No merge to `develop` or `main`, and no public
deployment.

## Known Limitations

- Authenticated Exa passed credential-presence preflight.
- `TAVILY_API_KEY` is absent from the acceptance process.
- The pinned PSL dependency is not installed.
- Authenticated repeat reliability, first-30 precision, known-positive live
  signal recall, clean SupportPilot V2, evidence-link reachability, and manual
  top-10 QA remain blocked.
- The optional licensed firmographic provider has an interface and config gate
  but no licensed vendor was selected or configured.
- Local PSL tests used the bounded degraded resolver because package download
  was not approved; CI/deployed environments must install
  `tldextract==5.3.0`.

## Final Question

> Would a real founder receive a meaningfully better shortlist than manual broad web searching and spreadsheet research?

**NO — not yet proven.**

The implementation makes materially better decisions in controlled tests,
especially for identity, unknowns, provenance, source compatibility, and false
signals. But the required authenticated holdout and top-10 manual QA did not
run, so founder value cannot honestly be promoted from an engineering
improvement to an acceptance result.
