# Prequalification Code Trace

Status: pre-change trace
Baseline run: `37355f0a-d439-4c38-ae8d-837c25dd8974`

## End-to-end path

| Step | File | Function/model | Input | Output and decision behavior |
|---|---|---|---|---|
| Search result | `services/research_gateway/app/schemas.py` | `SearchResult` | Provider URL, title, snippet, optional provider relevance | Typed untrusted search data |
| Candidate extraction | `apps/api/app/services/live_research.py` | `discover_accounts_job`, `_is_candidate_company_page` | `SearchResult` | Keeps official root/subdomain pages with allowed root/about paths; rejects known directory/news roles and list/review titles |
| Entity classification | `apps/api/app/services/company_identity.py` | `classify_result_page` | Result URL | `ResultPageRole` |
| Domain resolution | `apps/api/app/services/company_identity.py` | `resolve_company_identity` | Result URL | `CompanyDomainIdentity` containing host, registrable domain, canonical domain, role, confidence |
| Candidate aggregation | `apps/api/app/services/live_research.py` | `DiscoveryCandidate` | First result per canonical domain | Result plus query/provider provenance sets |
| Relevance factors | `apps/api/app/services/intelligence_quality.py` | `candidate_relevance_score` | Title, snippet, target terms, official-page flag, provider score, query hits, provider hits | One integer from 0–100 |
| Persistence | `apps/api/app/db/models.py` | `ResearchCandidateRow` | Identity, score, provenance | Durable candidate row and diagnostic JSON |
| Threshold | `apps/api/app/config.py` | `candidate_prequalification_floor` | Default `45` | One brittle cutoff |
| Final prequalification decision | `apps/api/app/services/live_research.py` | `discover_accounts_job` | Candidate score | `PREQUALIFIED` when score is at least 45; otherwise `REJECTED_PREQUALIFICATION` |
| Deep research | `apps/api/app/services/live_research.py` | `_research_account_sources` | Only shortlisted candidates | Official/account/news source evidence |
| ICP criteria | `apps/api/app/services/live_research.py` | `_qualify_account` | Deep-research text, validated domain, size state | Strict account-level qualification; unknown hard criteria remain explicit |
| Account decision | `apps/api/app/services/intelligence_quality.py` | `decide_qualification` | `CriterionEvaluation[]` | `QUALIFIED`, `QUALIFIED_WITH_UNCERTAINTY`, `INSUFFICIENT_EVIDENCE`, or `DISQUALIFIED` |

## Old score factors

`candidate_relevance_score` used:

| Factor | Maximum | Missing/default handling |
|---|---:|---|
| Target-term coverage | 45 | Zero when no target terms overlap |
| Official page | 25 | All persisted baseline rows received 25 |
| Provider relevance | 15 | `None` became zero |
| Additional query agreement | 10 | A single query received zero |
| Additional provider agreement | 5 | A single provider received zero |

The denominator was effectively all possible points, including unavailable
provider relevance and cross-provider evidence. Identity confidence and evidence
coverage were not separate decision dimensions. Unknown discovery-stage
firmographics were not explicitly represented; their effect was an absent score
contribution.

## Baseline factor values

- Page roles: 59 `OFFICIAL_ROOT`, 1 `OFFICIAL_SUBDOMAIN`.
- Identity confidence: 59 at `0.88`, HROne at `0.80`.
- Provider relevance score: missing for all 60.
- Provider agreement: one provider for all 60.
- Query agreement: 59 candidates appeared in one query; BizBMS appeared in three.
- Employee size: not evaluated before the threshold.
- Support operations: not evaluated before the threshold.
- Competitor status: not evaluated before the threshold.
- Final rejection reason for 59 rows: score below the single 45-point threshold.

## Dominant rejection rule

The 45-point threshold rejected `59/60` candidates (`98.33%`). It made repeated
query discovery a practical prerequisite even though the discovery queries were
category-specific and most valid companies naturally appeared once. Missing
provider relevance was treated as zero contribution. This is the dominant,
candidate-level root cause.

## Boundary to preserve

Prequalification should decide whether bounded research is warranted. It must not
promote discovery hints to verified account evidence, and it must not replace the
strict `_qualify_account` decision that runs after official-site and account-level
research.
