# GoPilot Phase 5 — Complete Acceptance

## Classification

**B — IMPROVED BUT NOT READY**

The prequalification-recall regression is recovered and the authenticated live
pipeline is technically sound. Product-quality targets are not met because the
final shortlist contains one cross-entity signal attachment, only 71.43% useful
ICP relevance, 50% signal precision, 1.14/3 mean brief usefulness, and 57.14%
founder YES+MAYBE value.

## Secure Runtime

- Runtime: `C:\Python313\python.exe`
- `tldextract==5.3.0`: verified
- Exa credential: process-local in the secure parent; now scrubbed
- Tavily: `NOT_CONFIGURED`, accepted under Exa-or-Tavily gate semantics
- Fixture fallback: disabled

## Exa REST and MCP

- Authenticated Exa REST sanity check: PASS
- Authenticated Exa MCP sanity check: PASS
- Anonymous MCP capacity: false
- Primary provider: Exa

## Reliability

All 5 bounded reliability queries passed. All 25 evaluated results were
relevant.

## Discovery Funnel

Fresh run: `9c481dc9-9af2-48a2-b5d2-ebd2995373bb`

| Stage | Count |
|---|---:|
| Raw unique candidates | 62 |
| Prequalified | 62 |
| Rejected at prequalification | 0 |
| Rejected after deep research | 0 |
| Final accounts | 7 |
| Qualified | 0 |
| Qualified with uncertainty | 6 |
| Disqualified | 1 |
| Insufficient evidence | 0 |

The completed run used 59 searches, 76 documents, and persisted 144 evidence
facts.

## Prequalification Recall Recovery

The Phase 5 fix recovered the prior funnel collapse: 62/62 candidates reached
post-prequalification consideration instead of uncertainty being treated as an
automatic rejection.

## Candidate Precision and Recall

| Metric | Result | Target | Outcome |
|---|---:|---:|---|
| Precision | 92.59% | at least 70% | PASS |
| Useful-candidate recall | 100% | at least 85% | PASS |
| False-negative rate | 0% | at most 15% | PASS |

## Positive-Signal Control

The separate positive control passed with 100% precision and 100% recall.

## Top-10 QA

Only seven accounts reached the final list, so all seven were independently
reviewed.

| Rank | Account | Status | Signal | Brief /3 | Founder |
|---:|---|---|---|---:|---|
| 1 | OpenHR India | Qualified with uncertainty | New product | 2 | YES |
| 2 | CloudSEK | Qualified with uncertainty | Customer growth | 2 | MAYBE |
| 3 | Optivian Cloud | Qualified with uncertainty | Partnership | 0 | NO |
| 4 | Fortifyze | Qualified with uncertainty | NO_SIGNAL | 1 | MAYBE |
| 5 | ComplyZero | Qualified with uncertainty | NO_SIGNAL | 1 | MAYBE |
| 6 | BiggerWide | Qualified with uncertainty | NO_SIGNAL | 1 | NO |
| 7 | BizBMS | Disqualified | NO_SIGNAL | 1 | NO |

All seven are real companies and all seven canonical domains are correct.
However, only 5/7 are useful ICP candidates. BiggerWide has verified evidence
of only 4+ employees, outside the requested 50–500 band. BizBMS is not a useful
target.

The decisive QA defect is Optivian Cloud: the deployment product at
`optivian.cloud` received sales-product evidence and partnership signals from
the unrelated `optivian.ai` entity. This produces a 14.29% false-entity
attachment rate instead of the required 0%.

## Evidence-Link Validation

- Reachable evidence links: 100% — PASS
- Duplicate accounts: 0% — PASS
- Fully supported important claims: 85.71% — FAIL (target at least 95%)
- Unsupported important claims: 14.29% — FAIL (target below 5%)

## Opportunity Brief Quality

Mean usefulness is **1.14/3**, below the 2.0/3 target. OpenHR and CloudSEK are
the only briefs that reach 2/3. Optivian is 0/3 because its “why now” evidence
crosses company entities. The remaining briefs mostly preserve uncertainty
correctly but do not add enough timely, decision-useful evidence.

## Founder Value

Founder YES+MAYBE is **4/7 (57.14%)**, below the 80% target. The result is
meaningfully better than the pre-Phase-5 zero-yield funnel, but not yet strong
enough to replace broad web research plus spreadsheet review.

## Engineering Gates

- Python: 132 passed, 2 skipped
- PostgreSQL/Redis integration: 2 passed
- Gateway security: 12 passed
- Frontend tests: 2 passed
- Ruff, Mypy, ESLint, TypeScript: PASS
- Next.js production build: PASS
- Alembic: `0006_intelligence_quality (head)`
- Docker Compose validation: PASS
- PowerShell parse: PASS
- Final-gate stderr regression and orchestration suite: 7 passed

The original post-holdout interruption was caused by PowerShell converting
ordinary redirected native stderr into a terminating `RemoteException` under
the runner's global stop policy. The gate wrapper now captures the native exit
code, records the individual result, restores the prior policy, and continues.

## Security Cleanup

The credential is absent from the current process, the secure buffer was freed,
runner-created child processes stopped, and credential-bearing temporary
artifacts were removed. Only safe run identifiers, aggregate metrics, public
URLs, and QA conclusions are retained.

## Git State

The verified runner correction, regression test, and these safe QA artifacts
are committed locally on `feature/intelligence-quality-improvement`.

## Release State

No push, merge, or deployment is permitted for classification B.

P0:

- Prevent evidence and signals from crossing registrable company entities.

P1:

- Raise persisted signal precision from 50% to at least 90%.
- Raise mean brief usefulness from 1.14/3 to at least 2.0/3.
- Raise founder YES+MAYBE yield from 57.14% to at least 80%.

P2:

- Improve employee-band coverage and suppress proven out-of-band accounts.
- Refine direct-competitor classification for broad category overlap.

## Final Answer

Would a real founder receive a meaningfully better evidence-backed shortlist
than broad web searching and spreadsheet research?

**NO.**
