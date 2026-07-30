# Intelligence Quality Improvement

Last updated: 2026-07-30

## Objective

Raise GoPilot from the Phase 3 `B — PARTIAL` baseline to a measured
`A — QUALITY PASS`. This phase changes research precision, provenance,
qualification, ranking, and evaluation. It does not add outreach automation,
personal enrichment, CRM, billing, or production auth.

## Preserved baseline

- Phase 3 source commit: `a5838a7`
- Phase 4 branch: `feature/intelligence-quality-improvement`
- PostgreSQL/Redis baseline: 35 passed
- Web baseline: 2 passed
- Ruff, Mypy, ESLint, TypeScript, Next.js: passed
- Alembic baseline: `0005_source_provenance_identity`

| Metric | Baseline | Phase 4 target |
| --- | ---: | ---: |
| Real company/product rate | 100% | 100% |
| Canonical-domain correctness | 90% | at least 98% |
| Useful top-account ICP relevance | 20% | at least 80% |
| Fully supported important claims | 30% | at least 95% |
| Unsupported important claims | 30% | under 5% |
| Primary evidence-link success | 100% | at least 98% |
| Duplicate rate | 0% | under 5% |
| False entity signal attachment | 1 known failure | 0% |
| Signal precision | 0 of 1 | at least 90% preferred |
| Mean brief usefulness | 1.0 / 3 | at least 2.0 / 3 |

## Quality work ledger

| Root cause | Implementation | Test | Live result | Risk / next step |
| --- | --- | --- | --- | --- |
| Anonymous search exhaustion | Authenticated Exa primary, optional keyed Tavily fallback, fail-closed OR gate, and typed safe diagnostics | Provider-state and redaction regressions pass | Direct REST and MCP both authenticated pass | Run bounded repeats in the next secure acceptance session |
| Weak candidate precision | Broad collection, result roles, agreement score, persisted prequalification | Candidate scoring tests pass | Not run after diagnostics | Run first-30 comparison |
| Ambiguous ICP semantics | Versioned HARD/SOFT/INFORMATIONAL criteria and three-valued state | Unknown tests pass | Controlled pass | Measure live coverage |
| Canonical subdomain errors | PSL-aware registrable domains and separate discovered/canonical identity | HROne plus 20-domain matrix passes | 20/20 controlled | Pinned PSL installed and verified |
| Weak firmographics | Provider abstraction and conservative company-level public fallback | Unknown/exact/range tests pass | Controlled pass | Select licensed provider if needed |
| Weak source compatibility | Source roles, quality components, claim/source policy | Vendor-market regression passes | Controlled pass | QA holdout claims |
| Generic signals | Event queries, entity/date/relevance gates, no-signal outcome | Wrong-entity/no-signal tests pass | Positive live control not run | Run known-positive control |
| Unknown-heavy scoring | Missing-aware deterministic scoring and priority floors | Score matrix passes | Controlled pass | Compare live ranking |
| Generic briefs | Verified facts, unknowns, hypotheses, event/relevance split, candidate label | Integration/API tests pass | Controlled pass | Grade top 10 |

## Evaluation design

### Development track

- Phase 3 failure regressions.
- Twenty-case canonical-domain matrix.
- Controlled provider exhaustion/fallback.
- Source compatibility and wrong-entity signal tests.
- PostgreSQL/Redis durable-flow integration.

### Holdout track

- Fresh SupportPilot V2 workspace and search run.
- No manually seeded final accounts.
- At least one authenticated provider; Exa is primary when configured and
  Tavily is an optional fallback.
- Separate known-positive signal control.
- Manual top-10 QA without changing target thresholds.

Current holdout state: `B — IMPROVED BUT NOT READY`.
`tldextract==5.3.0` is installed and all provider OR-gate regressions pass. The
rotated Exa credential was supplied once through a secure process-local prompt.
Direct REST and a separately initialized MCP search both returned authenticated
HTTP 200 responses with three relevant results. The one-time credential was
scrubbed after diagnostics, before the repeated reliability and holdout gates
ran. Tavily is optional and `NOT_CONFIGURED`; no anonymous result was accepted.

## Release rule

Only `A — QUALITY PASS` may merge to `develop`, followed by final verification
and `main`. B, C, D, or a configuration blocker remains on the feature branch.
No public deployment occurs in this phase.

## Phase 5: prequalification recall recovery

The preserved credentialed baseline was:

```text
60 raw -> 1 prequalified -> 1 disqualified -> 0 founder-usable
```

The exact candidate-level trace found that 59/60 candidates failed only the
single 45-point cutoff. All provider relevance scores were unavailable, 59/60
candidates had one query hit, all had one provider, and all had an official
root/subdomain role with identity confidence of at least 0.80.

Phase 5 separates candidate relevance, identity confidence, evidence coverage,
and research worthiness. It introduces explicit match states, three evidence
stages, structured competitor classifications, and these calibrated outcomes:

- `PREQUALIFIED`
- `PREQUALIFIED_WITH_UNCERTAINTY`
- `REVIEW_REQUIRED`
- `REJECTED`

The first-30 labelled development replay improved recall from 4.00% to 100.00%,
kept precision at 92.59%, and reduced the false-negative rate from 96.00% to
0.00%. The 60-row shadow replay produced 5 prequalified, 30
prequalified-with-uncertainty, and 25 review-required candidates. The automatic
research pool is therefore 35, still bounded by the existing 20-account deep
research limit.

Credential-free Phase 5 gates:

- prequalification regressions: 25 passed
- full Python/API/gateway suite: 125 passed, 2 skipped
- PostgreSQL/Redis integration: 2 passed
- gateway security: 10 passed
- web tests: 2 passed
- Ruff, Mypy, ESLint, TypeScript, Next.js build: passed
- Alembic: `0006_intelligence_quality (head)`
- Docker Compose validation, secret scan, and `git diff --check`: passed

No fresh holdout has been used for calibration. Final classification remains
pending one fresh credentialed SupportPilot V2 holdout.
