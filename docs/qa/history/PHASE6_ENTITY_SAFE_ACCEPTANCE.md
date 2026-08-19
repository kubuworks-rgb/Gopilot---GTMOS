# GoPilot Phase 6 — Entity-Safe Acceptance

## Classification

**B — IMPROVED BUT NOT READY**

The primary defect is fixed: the fresh holdout attached no `optivian.ai`
evidence or signals to `optivian.cloud`, and manual QA found a 0% false-entity
attachment rate. Phase 6 is still not an A because the fresh holdout missed the
useful-ICP, founder-value, claim-support, evidence-link, and signal-precision
targets. No push, merge, deployment, or additional Exa holdout is permitted.

Fresh authenticated run:

- Research run: `3a699420-ea2e-47f5-8056-679ba0ef4709`
- Workspace: `cf3addea-dcd6-40e1-945d-06c4402882b9`
- Exa REST: authenticated pass
- Exa MCP: authenticated pass
- Anonymous MCP capacity: false
- Tavily: `NOT_CONFIGURED`
- Reliability: 5/5 queries and 25/25 relevant results
- Fixture fallback: false
- Positive-signal control: 100% precision and 100% recall

## Exact Cross-Entity Root Cause

Phase 5 discovered Optivian Cloud correctly at `optivian.cloud`, but
`live_research.py::_news_result_matches_company` reduced the target domain to
the shared brand token `optivian`. Results from `optivian.ai` therefore passed
the news matcher despite the registrable-domain conflict.

The fetched `optivian.ai` pages were then labelled first-party relative to
themselves, not relative to the target account. The mixed fact list had no
account-relative entity or claim-scope gate. Every fact attached to the account,
four event-like facts became Optivian Cloud signals with a hard-coded
cross-domain entity score, and those signals affected scoring and the brief.

The missing control was between source persistence and account attachment:
there was no deterministic account-relative entity relation plus compatible
claim-scope decision. The full pre-fix path is preserved in
`PHASE6_ENTITY_EVIDENCE_BASELINE.md`.

## Identity Model

Phase 6 adds deterministic relations:

`SAME_ENTITY`, `PRODUCT_OF`, `SUBSIDIARY_OF`, `PARENT_OF`, `SISTER_BRAND`,
`REBRAND_OF`, `ACQUIRED_BY`, `PARTNER_OF`, `UNRELATED`, and `UNKNOWN`.

It also adds claim scopes:

`COMPANY_LEVEL`, `PRODUCT_LEVEL`, `PARENT_LEVEL`, `SUBSIDIARY_LEVEL`,
`MARKET_LEVEL`, and `PARTNER_LEVEL`.

An account attachment now requires both identity compatibility and claim-scope
compatibility. Matching brand prefixes no longer imply the same entity, and a
different registrable domain requires verified relationship evidence. Ambiguous
facts become `UNATTACHED_ENTITY_AMBIGUOUS`; related but out-of-scope facts become
`RELATED_ENTITY_ONLY`.

Each account persists a company-identity record containing its canonical name
and registrable domain, verified official domains, evidenced aliases and
relationships, product/parent/subsidiary fields, confidence, and unresolved
warnings. Only attached evidence can affect signals, scores, snapshots, briefs,
or campaign output.

## Phase 5 Evidence Replay

The Phase 5 run `9c481dc9-9af2-48a2-b5d2-ebd2995373bb` was replayed without
external search:

| Measure | Result |
|---|---:|
| Documents replayed | 76 |
| Evidence facts loaded | 144 |
| Old account attachments replayed | 109 |
| Run-level facts with no old account attachment | 35 |
| Correct attachments retained | 86 |
| Ambiguous or related-only attachments removed | 23 |
| False attachments after replay | 0 |
| Old persisted signals | 8 |
| Valid signals retained | 4 |
| Rebuilt signal precision | 100% |
| Supported rebuilt important claims | 100% |
| Unsupported rebuilt important claims | 0% |
| Mean structural brief usefulness | 2.0/3 |

The complete 109-row attachment audit is preserved in
`PHASE6_ENTITY_EVIDENCE_REPLAY.md` and
`PHASE6_ENTITY_EVIDENCE_REPLAY.json`.

## Old vs New Attachments

| Account | Domain | Evidence old → retained | Signals old → retained | Rebuilt state |
|---|---|---:|---:|---|
| OpenHR India | `openhr.tech` | 17 → 17 | 3 → 3 | `RESEARCH_CANDIDATE` |
| CloudSEK | `cloudsek.com` | 18 → 14 | 1 → 1 | `RESEARCH_CANDIDATE` |
| Fortifyze | `fortifyze.com` | 8 → 8 | 0 → 0 | `MONITOR` |
| ComplyZero | `complyzero.com` | 11 → 10 | 0 → 0 | `MONITOR` |
| Optivian Cloud | `optivian.cloud` | 18 → 6 | 4 → 0 | `IDENTITY_REVIEW_REQUIRED` |
| BiggerWide | `biggerwide.com` | 23 → 21 | 0 → 0 | `IDENTITY_REVIEW_REQUIRED` |
| BizBMS | `bizbms.com` | 14 → 10 | 0 → 0 | `DO_NOT_TARGET` |

The replay removed the `optivian.ai` and unresolved third-party attachments
without introducing company-specific production rules.

## Signal Precision

Credential-free replay signal precision improved from 50% to 100% after the
four Optivian cross-entity signals were removed.

Fresh-holdout signal precision was 75%: three OpenHR product-launch signals
were supported, while CloudSEK's static “Trusted by 100+ Customers” page did
not prove a current customer-growth event. Identity was correct, but event
semantics were not. This misses the preferred 90% target.

## Supported Claims

Credential-free rebuilt briefs reached 100% supported important claims and 0%
unsupported claims.

Fresh manual QA reached 85.71% supported important claims and 14.29%
unsupported claims because the CloudSEK customer-growth label was treated as a
current event. The Phase 6 targets are at least 95% supported and under 5%
unsupported, so this gate fails.

## Prequalification Distribution

The old “62 prequalified” export collapsed distinct outcomes. Replaying the
persisted Phase 5 decisions showed:

| Outcome | Count |
|---|---:|
| `PREQUALIFIED` | 7 |
| `PREQUALIFIED_WITH_UNCERTAINTY` | 31 |
| `REVIEW_REQUIRED` | 24 |
| `REJECTED` | 0 |

The fresh 60-candidate run preserved the distinctions:

| Outcome | Count |
|---|---:|
| `PREQUALIFIED` | 5 |
| `PREQUALIFIED_WITH_UNCERTAINTY` | 33 |
| `REVIEW_REQUIRED` | 22 |
| `REJECTED` | 0 |

The separate preserved first-30 labelled control passed with 92.59% precision,
100% recall, and 0% false-negative rate. Those are controlled-development
metrics; the fresh discovery set does not have independent exhaustive labels.

## Fresh Holdout Funnel

The one permitted fresh holdout used 58 searches, 72 documents, and 136 facts:

```text
60 raw candidates
→ 5 PREQUALIFIED
→ 33 PREQUALIFIED_WITH_UNCERTAINTY
→ 22 REVIEW_REQUIRED
→ 38 shortlisted for deep research
→ 7 deeply researched / final accounts
→ 0 qualified
→ 6 qualified with uncertainty
→ 1 disqualified
```

No further provider run was performed after this holdout.

## Top-10 QA

The holdout yielded seven final accounts, so independent manual QA reviewed all
seven rather than padding the sample to ten.

| Rank | Account | Domain | State | Useful ICP | Important claim | Founder value | QA result |
|---:|---|---|---|---|---|---|---|
| 1 | OpenHR India | `openhr.tech` | `RESEARCH_CANDIDATE` | Yes | Supported | Yes | First-party launch evidence; size and B2B status remain unresolved |
| 2 | CloudSEK | `cloudsek.com` | `RESEARCH_CANDIDATE` | Yes | Unsupported | Maybe | Static customer page is not a dated growth event |
| 3 | Fortifyze | `fortifyze.com` | `MONITOR` | Yes | Supported | Maybe | Missing size/model evidence is exposed |
| 4 | ComplyZero | `complyzero.com` | `MONITOR` | Yes | Supported | Maybe | Ambiguous third-party evidence is excluded |
| 5 | Optivian Cloud | `optivian.cloud` | `MONITOR` | Yes | Supported | Maybe | No `optivian.ai` evidence or signal attached |
| 6 | BiggerWide | `biggerwide.com` | `IDENTITY_REVIEW_REQUIRED` | No | Supported | No | BiggerWide365 relation unresolved; known 4+ employees outside target |
| 7 | BizBMS | `bizbms.com` | `DO_NOT_TARGET` | No | Supported | No | Correctly disqualified and outreach suppressed |

| Manual-QA metric | Target | Fresh result | Gate |
|---|---:|---:|---|
| Real companies | 100% | 100% | Pass |
| Canonical domains | ≥98% | 100% | Pass |
| Useful ICP relevance | ≥80% | 71.43% | Fail |
| Founder YES+MAYBE | ≥80% | 71.43% | Fail |
| False entity attachment | 0% | 0% | Pass |
| Supported important claims | ≥95% | 85.71% | Fail |
| Unsupported important claims | <5% | 14.29% | Fail |
| Evidence links | ≥98% | 97.56% (40/41) | Fail |
| Duplicate rate | <5% | 0% | Pass |
| Signal precision | ≥90% preferred | 75% | Fail |
| Mean brief usefulness | ≥2.0/3 | 2.0/3 | Pass |

The only unreachable evidence URL was an OpenHR launch page. No duplicate
account was found.

## Brief States and Usefulness

Fresh brief-state distribution:

| State | Count |
|---|---:|
| `FOUNDER_READY` | 0 |
| `RESEARCH_CANDIDATE` | 2 |
| `MONITOR` | 3 |
| `IDENTITY_REVIEW_REQUIRED` | 1 |
| `DO_NOT_TARGET` | 1 |

Mean usefulness improved from 1.14/3 in Phase 5 to 2.0/3. Weak or ambiguous
accounts are no longer presented as founder-ready, and generic outreach is
suppressed when there is no supported reason to contact. The state model is
working, but none of the fresh accounts met the `FOUNDER_READY` bar.

## Founder Value

Five of seven accounts were judged YES or MAYBE (71.43%), up from 57.14% in
Phase 5 but below the 80% target. The result is useful for bounded research and
monitoring, not yet reliable enough for founders to treat broad autonomous
discovery as a production-ready account feed.

## Engineering Gates

Final credential-free gates after the fresh holdout:

| Gate | Result |
|---|---|
| Python suite | 155 passed, 2 skipped |
| PostgreSQL/Redis integration | 2 passed |
| Gateway security | 12 passed |
| Acceptance orchestration | 7 passed |
| Frontend tests | 2 passed |
| Ruff | Pass |
| Mypy | Pass, 51 source files |
| ESLint | Pass |
| TypeScript | Pass |
| Next.js production build | Pass |
| Alembic | `0006_intelligence_quality (head)` |
| Docker Compose validation | Pass |
| PowerShell acceptance scripts | 3 parsed |
| Credential-free mock orchestration | Every required stage reached |
| `tldextract` | `5.3.0` |
| Secret scan | 0 credential-assignment matches |
| `git diff --check` | Pass |

The paused live runner exposed one reporting-only harness defect:
`Invoke-LoggedGate` accepted `[hashtable]`, causing PowerShell to copy an
`[ordered]` result dictionary and omit individual gate keys from
`final_gates.json`. Commit `2d31b14` changes the contract to
`[System.Collections.IDictionary]` and adds regression coverage. The gates had
run successfully; the fix preserves their individual results.

## Security Cleanup

- The Exa key was entered once through `Read-Host -AsSecureString`.
- It was never placed in chat, command-line arguments, tracked configuration,
  or the final evidence.
- The secure runner is no longer active.
- The current process contains neither `EXA_API_KEY` nor `TAVILY_API_KEY`.
- Tracked and untracked workspace files have zero credential-assignment
  matches.
- Tavily remained `NOT_CONFIGURED`.
- Temporary live acceptance outputs are deleted after this report is recorded.
- Local PostgreSQL and Redis containers started for final integration tests
  were stopped with their data volumes preserved.

## Git State

Local checkpoint commits:

- `6140f7c fix: prevent cross-company evidence attachment`
- `2d31b14 fix: preserve complete acceptance gate results`

This report and its safe JSON evidence are committed locally only. Because the
classification is B, nothing is pushed, merged, or deployed.

## Product Decision

Choose **C: both, with autonomous discovery marked experimental**.

Bring-your-own-account research and prioritisation should be the dependable
product path: Phase 6 now enforces entity-safe evidence, separates unknowns and
ambiguities, uses explicit brief states, and suppresses unsupported outreach.

Autonomous discovery should remain available only as an experimental source of
research candidates. It still misses the required useful-account,
founder-value, claim-support, evidence-link, and signal-precision targets, and
it produced no `FOUNDER_READY` account in this holdout. That is insufficient
for a production promise, but the 100% real-company/domain results and 71.43%
useful-account rate justify retaining it as a labelled experiment rather than
removing it.

This is the hard stop required by Phase 6. Do not begin another tuning phase or
spend additional provider credits without a new product decision.
