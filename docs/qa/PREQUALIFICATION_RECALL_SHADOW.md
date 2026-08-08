# Prequalification Recall Shadow Evaluation

Status: credential-free development evaluation

Calibration dataset: first 30 rows of baseline run
`37355f0a-d439-4c38-ae8d-837c25dd8974`

Full safe diagnostic export:
`docs/qa/PREQUALIFICATION_RECALL_REPLAY.json`

## Exact root cause

The old policy collapsed candidate relevance, identity, evidence availability,
and research worthiness into one score and applied one 45-point cutoff.

| Dominant old factor | Count | Percentage |
|---|---:|---:|
| Threshold failure | 59 | 98.33% |
| Provider relevance contribution unavailable | 60 | 100% |
| No additional query-agreement contribution | 59 | 98.33% |
| No cross-provider contribution | 60 | 100% |

The most common combination was missing provider relevance, one query hit, one
provider, and score below 45: `59/60` candidates (`98.33%`).

No baseline row was rejected because of a verified wrong geography, verified
wrong business model, direct-competitor proof, directory/news role, duplicate,
or invalid domain. Those checks either passed during candidate extraction or had
not yet occurred.

## First-30 labels

The development labels are in
`apps/api/tests/fixtures/prequalification_recall_baseline.csv`.

| Label | Count |
|---|---:|
| `USEFUL_RAW_CANDIDATE` | 25 |
| `NOT_USEFUL_RAW_CANDIDATE` | 2 |
| `UNCERTAIN` | 3 |

The three uncertain rows are excluded from the confusion matrices. A useful raw
candidate is worth bounded research; it is not yet a qualified account.

## Baseline confusion matrix

|  | Predicted research-worthy | Predicted reject |
|---|---:|---:|
| Useful raw candidate | 1 | 24 |
| Not useful raw candidate | 0 | 2 |

| Metric | Old policy |
|---|---:|
| Precision | 100.00% |
| Recall | 4.00% |
| F1 | 7.69% |
| False-negative rate | 96.00% |

## New development confusion matrix

`PREQUALIFIED` and `PREQUALIFIED_WITH_UNCERTAINTY` count as bounded-research
decisions. `REVIEW_REQUIRED` remains outside automatic deep research.

|  | Predicted research-worthy | Predicted reject/review |
|---|---:|---:|
| Useful raw candidate | 25 | 0 |
| Not useful raw candidate | 2 | 0 |

| Metric | New shadow policy | Development target |
|---|---:|---:|
| Precision | 92.59% | >=70% |
| Recall | 100.00% | >=85% |
| F1 | 96.15% | — |
| False-negative rate | 0.00% | <=15% |

The policy does not accept every candidate automatically. Rows below the
middle threshold remain `REVIEW_REQUIRED`, and verified hard mismatches always
reject.

## Threshold calibration

The score bands were selected from the first-30 labelled development set before
any fresh holdout:

| Score/evidence condition | Outcome |
|---|---|
| Verified non-company, duplicate, verified hard mismatch, or evidenced direct competitor | `REJECTED` |
| Relevance >=35 with plausible software model | `PREQUALIFIED` |
| Relevance 30–34 | `PREQUALIFIED_WITH_UNCERTAINTY` |
| Relevance 25–29 | `REVIEW_REQUIRED` |
| Relevance <25 | `REJECTED` |

Unknown employee size, support operations, soft preferences, or snippet-level
geography does not become a mismatch. It becomes a visible research
requirement.

## Shadow-mode comparison

| Metric | Old policy | New shadow policy |
|---|---:|---:|
| `PREQUALIFIED` | 1 | 5 |
| `PREQUALIFIED_WITH_UNCERTAINTY` | 0 | 30 |
| `REVIEW_REQUIRED` | 0 | 25 |
| Rejected before research | 59 | 0 |
| First-30 false negatives | 24 | 0 |
| First-30 false positives | 0 | 2 |
| First-30 recall | 4.00% | 100.00% |
| First-30 precision | 100.00% | 92.59% |

The automatic deep-research pool changes from 1 to 35 candidates. The existing
20-account research budget still bounds downstream work. Twenty-five lower-band
rows remain review-only rather than consuming that budget.

## Old versus new baseline funnel

| Stage | Old | New shadow |
|---|---:|---:|
| Raw candidates | 60 | 60 |
| Automatic research candidates | 1 | 35 |
| Review required | 0 | 25 |
| Maximum deep research | 1 | 20 |

This is a development replay, not a final qualification result. Qualified and
founder-usable account counts can only be measured on the fresh credentialed
holdout.

## Unknown handling

The new diagnostic contract exposes:

- `VERIFIED_MATCH`
- `ESTIMATED_MATCH`
- `UNKNOWN`
- `VERIFIED_MISMATCH`

Unknown fields do not receive match points, and missing weights are not silently
redistributed. Candidate relevance, identity confidence, evidence coverage, and
research worthiness are stored separately.

## Evidence stages

- `DISCOVERY_HINT`: search result and query provenance; may support research
  worthiness only.
- `PREQUALIFICATION_EVIDENCE`: bounded official-source evidence suitable for
  a provisional decision.
- `VERIFIED_ACCOUNT_EVIDENCE`: durable account evidence used by strict final
  qualification and briefs.

The baseline replay uses only `DISCOVERY_HINT`.

## Competitor classification

The structured classifications are:

- `DIRECT_COMPETITOR`
- `ADJACENT_VENDOR`
- `POTENTIAL_BUYER_WITH_OVERLAPPING_FEATURES`
- `NOT_COMPETITOR`
- `UNKNOWN`

Automatic rejection requires high-confidence evidence for product overlap,
buyer overlap, core-use-case overlap, and commercial substitution. Generic words
such as AI, automation, support, agent, chatbot, or workflow are insufficient.
Classification, confidence, evidence IDs, overlap dimensions, and automatic
rejection eligibility are persisted in candidate/account diagnostics after
account research.
