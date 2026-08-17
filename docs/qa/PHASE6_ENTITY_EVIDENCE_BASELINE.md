# GoPilot Phase 6 — Entity and Evidence Baseline

This document preserves the Phase 5 holdout before any Phase 6 implementation.
It does not replace or modify the Phase 5 reports.

## Preserved Run

- Research run: `9c481dc9-9af2-48a2-b5d2-ebd2995373bb`
- Workspace: `d49c8f7a-d7aa-4431-a4f4-2e56abcd440c`
- Documents: 76
- Evidence facts: 144
- Final accounts: 7
- Phase 5 classification: B — IMPROVED BUT NOT READY

## Seven-Account Baseline

| Account | Domain | Qualification | Evidence | Sources | Persisted signals | Brief state before Phase 6 | Manual QA |
|---|---|---|---:|---:|---:|---|---|
| OpenHR India | `openhr.tech` | `QUALIFIED_WITH_UNCERTAINTY` | 17 | 9 | 3 `NEW_PRODUCT` | implicit research candidate | useful; 2/3; founder YES |
| CloudSEK | `cloudsek.com` | `QUALIFIED_WITH_UNCERTAINTY` | 18 | 9 | 1 `CUSTOMER_GROWTH_INDICATOR` | implicit research candidate | useful; 2/3; founder MAYBE |
| Optivian Cloud | `optivian.cloud` | `QUALIFIED_WITH_UNCERTAINTY` | 18 | 9 | 4 mixed signals | implicit research candidate | cross-entity failure; 0/3; founder NO |
| Fortifyze | `fortifyze.com` | `QUALIFIED_WITH_UNCERTAINTY` | 8 | 4 | 0 | implicit research candidate | useful but weak; 1/3; founder MAYBE |
| ComplyZero | `complyzero.com` | `QUALIFIED_WITH_UNCERTAINTY` | 11 | 6 | 0 | implicit research candidate | useful but weak; 1/3; founder MAYBE |
| BiggerWide | `biggerwide.com` | `QUALIFIED_WITH_UNCERTAINTY` | 23 | 12 | 0 | implicit research candidate | employee evidence outside target; 1/3; founder NO |
| BizBMS | `bizbms.com` | `DISQUALIFIED` | 14 | 7 | 0 | implicit research candidate | not useful; 1/3; founder NO |

### Source-domain baseline

- OpenHR: `openhr.tech`
- CloudSEK: `cloudsek.com`, `job-boards.greenhouse.io`
- Optivian Cloud: `optivian.cloud`, `docs.optivian.cloud`, `optivian.ai`,
  `einpresswire.com`
- Fortifyze: `fortifyze.com`
- ComplyZero: `complyzero.com`, `echai.ventures`
- BiggerWide: `biggerwide.com`, `biggerwide365.com`
- BizBMS: `bizbms.com`, `jobaaj.com`

Every Phase 5 brief marked one `why_it_fits` claim as supported and copied the
first five attached facts into `verified_facts`. OpenHR had three `why_now`
claims, CloudSEK had one, Optivian Cloud had four, and the other accounts had
none.

## Phase 5 Manual QA Baseline

| Metric | Phase 5 |
|---|---:|
| Real companies | 100% |
| Canonical domains | 100% |
| Useful ICP relevance | 71.43% |
| Founder YES+MAYBE | 57.14% |
| Supported important claims | 85.71% |
| Unsupported important claims | 14.29% |
| Signal precision | 50% |
| False-entity attachment | 14.29% |
| Mean brief usefulness | 1.14/3 |

## Exact Executable Attachment Path

| Hop | File and function | Input | Output | Identity/domain check | Relationship/scope check | Failure behavior |
|---|---|---|---|---|---|---|
| Search result | `live_research.py::_research_account_sources` | provider result | candidate result to fetch | official-purpose results require matching domain; news calls `_news_result_matches_company` | none | non-matches are skipped |
| News entity match | `live_research.py::_news_result_matches_company` | title, snippet, account name, account domain | boolean | accepts the registrable-domain brand token or full account name in text | no alias evidence; no relation type; no conflict detection | shared brand token returns true |
| Fetch | `LiveResearchProvider.fetch` through the Research Gateway | result URL | sanitized source input | gateway URL safety only | none | provider/fetch errors are skipped |
| Source persistence | `live_research.py::_persist_source` | source input and extraction focus | `SourceDocumentRow`, `EvidenceFactRow[]` | source role is intrinsic to the fetched URL, not relative to the target account | none | exact-passage validation; no account-identity rejection |
| Account research aggregation | `live_research.py::_research_account_sources` | every accepted source and fact | one mixed `sources` and `facts` list | only official sources are filtered for firmographics and qualification | none | external facts remain in the mixed list |
| Account attachment | `live_research.py::discover_accounts` | mixed `facts` | `AccountRow.evidence_ids` | none at attachment lines 1857/1865 | none | every fact attaches |
| Signal extraction | `live_research.py::_signals_from_facts` | mixed facts and source map | signal/fact matches | first-party checks exact domain; external evidence reuses the permissive name matcher | none | a brand-token match is accepted |
| Signal persistence | `live_research.py::_score_and_brief` | signal matches | `IntentSignalRow`, API `Signal` | cross-domain signals receive hard-coded entity score `0.95` | none | accepted signals affect score |
| Account score | `live_research.py::_score_and_brief` | every fact and accepted signal | score snapshot and factors | none | none | mixed facts increase coverage and source-quality inputs |
| Snapshot | `live_research.py::_score_and_brief` | every fact and source | research snapshot | none | none | all fact/source IDs persist |
| Brief | `live_research.py::_score_and_brief` | every fact, signal, and source | opportunity brief and campaign | none | none | first fact becomes fit; signals become `why_now`; first five facts become verified facts; all facts support the campaign |
| Regeneration | `live_research.py::regenerate_brief` | `AccountRow.evidence_ids` | new score and brief | none | none | previously contaminated account evidence is reused |

## Exact Optivian Root Cause

The Optivian Cloud target was keyed correctly as `optivian.cloud`. External
results from `optivian.ai` were nevertheless admitted because the news entity
matcher reduced the target domain to the shared token `optivian`. That token
appeared in the external result, so the result passed despite the registrable
domain conflict.

The fetched `optivian.ai` sources were independently labelled `FIRST_PARTY`
because source role described the source itself rather than its relationship to
the target account. All extracted facts then entered the unfiltered account
fact list. Four event-like facts became Optivian Cloud signals, each receiving a
hard-coded cross-domain entity score of `0.95`. Those signals affected intent
scoring and became supported `why_now` claims.

The defect is therefore not canonical-domain discovery. It is the absence of
an account-relative entity relation and claim-scope decision between source
persistence and every downstream attachment.
