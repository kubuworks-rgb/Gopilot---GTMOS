# SupportPilot Real GTM Intelligence QA

Date: 2026-07-23
Test product: `SupportPilot AI` — test profile, not a claim that a real company exists.

## Acceptance runs

- Diagnostic top-10 run: `a85e9a35-09f3-4dd8-b77e-7d3941adacd7`
- Post-identity-fix run: `8f832a47-75ce-40c2-a418-5573ecb1a729`
- Post-fix result: six borderline accounts, zero verified current signals.
- Fixture contamination: none. API health reported `mode=live`; every source row had `demo_data=false`.

The diagnostic ten-account run is retained for manual failure analysis. The post-fix
run is the classification source of truth. It removed the wrong-entity funding signal
but did not reach the required ten accounts before anonymous provider capacity became
unavailable.

## Manual top-10 diagnostic QA

| Rank | Company | Real? | Domain Correct? | ICP 0–3 | Signal 0–3 | Evidence | Brief 0–3 |
| ---- | ------- | ----- | --------------- | ------: | ---------: | -------- | --------: |
| 1 | HROne | REAL | INCORRECT | 2 | 0 | UNSUPPORTED | 0 |
| 2 | BharatBuild AI | REAL | CORRECT | 1 | 0 | PARTIAL | 1 |
| 3 | GainTrace | REAL | CORRECT | 1 | 0 | PARTIAL | 1 |
| 4 | BiggerWide | REAL | CORRECT | 1 | 0 | PARTIAL | 1 |
| 5 | ComplyDP | REAL | CORRECT | 1 | 0 | PARTIAL | 1 |
| 6 | Zeeks | REAL | CORRECT | 1 | 0 | SUPPORTED | 1 |
| 7 | SaaSoty | REAL | CORRECT | 1 | 0 | PARTIAL | 1 |
| 8 | asintellect | REAL | CORRECT | 1 | 0 | PARTIAL | 1 |
| 9 | Optivian | REAL | CORRECT | 1 | 0 | SUPPORTED | 1 |
| 10 | Foresiet | REAL | CORRECT | 2 | 0 | SUPPORTED | 2 |

## Measured quality

| Metric | Actual | Target |
| ------ | -----: | -----: |
| Real company/product rate | 100% | 100% |
| Correct canonical domain | 90% | at least 95% |
| Useful ICP relevance (score 2–3) | 20% | at least 80% |
| Fully supported account evidence | 30% | at least 95% |
| Relevant claimed signals | 0% (0 of 1) | at least 80% |
| Duplicate rate | 0% | under 5% |
| Accounts with unsupported important claims | 30% | under 5% |
| Primary evidence-link success | 100% | at least 95% |

## Failure analysis

- `go.hrone.cloud` was an official HROne subdomain, but the domain label produced
  the entity name `Go`. A news result about Japanese robotaxi company Go was then
  attached as an HROne funding signal.
- `4,832 employees` appeared inside an HROne payroll product mock and was incorrectly
  treated as HROne's workforce size.
- External account research admitted social pages and, for a generic product title,
  unrelated Amazon-product domains.
- Several real products were too early-stage or had no defensible 50–500 employee
  evidence, making them weak matches for the selected ICP.
- The clean post-fix run produced no verified current buying triggers.

## Corrective controls implemented

- External news must match the company domain brand before it can become evidence.
- Social and excluded hosts cannot enter account news enrichment.
- Company-size extraction requires explicit workforce language and uses official-domain
  text only.
- Deterministic fit awards the size component only for a verified in-range size.
- Regression tests cover wrong-entity news and product-UI employee numbers.

## Classification

`B — PARTIAL`, but not acceptable for merge to `develop` or `main`.

The source-aware infrastructure and evidence chain work with real public inputs.
Account usefulness, current-signal coverage, and final post-fix shortlist size do not
meet the release bar.
