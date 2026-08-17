# Real GTM Intelligence Acceptance

Last updated: 2026-07-23

## Goal

Prove that GoPilot can turn the user-confirmed SupportPilot AI test profile into
inspectable market intelligence, three differentiated ICPs, 10-20 real accounts,
evidence-only signals, deterministic scores, and human-reviewable opportunity
briefs without fixture substitution or autonomous outreach.

## Acceptance profile

- Product: SupportPilot AI
- Category: AI customer-support automation
- Market: India B2B SaaS
- Preferred company size: 50-500 employees
- Important profile claims use one of `USER_CONFIRMED`, `SOURCE_SUPPORTED`,
  `INFERRED`, or `UNKNOWN`.

## Source routing

| Intent | Primary source | Secondary source | Notes |
|---|---|---|---|
| Market and competitor discovery | Exa remote MCP | Official site fetch | General-web search; no key is required for the bounded free tier |
| Company discovery | Exa remote MCP | Official site fetch | Candidate pages are not accepted as company domains without validation |
| Official-domain validation | Official site fetch | Exa result context | Redirects and public-address policy remain enforced by the gateway |
| Company size | Official about/careers pages | Reputable public source | Stored as `VERIFIED`, `ESTIMATED`, or `UNKNOWN` |
| Current events | GDELT DOC 2.0 | Official newsroom/careers | GDELT is news-only and never substitutes for general web |
| Account research | Official about/product/pricing/customers/careers/news pages | Exa + GDELT | Bounded pages, queries, bytes, and elapsed time |

## Deterministic research intents

- `PRODUCT_UNDERSTANDING`
- `MARKET_LANDSCAPE`
- `COMPETITOR_DISCOVERY`
- `ICP_EVIDENCE`
- `ACCOUNT_DISCOVERY`
- `OFFICIAL_DOMAIN_VALIDATION`
- `COMPANY_SIZE_VALIDATION`
- `ACCOUNT_SIGNAL_RESEARCH`

Each persisted research task records its intent and source strategy. Retrieved
content is untrusted data and never authorizes tools.

## Implementation phases

| Phase | Scope | Status | Exit evidence |
|---|---|---|---|
| 0 | Baseline, branch, provider audit | Complete | `feature/real-gtm-intelligence`; baseline test/lint/typecheck/build green |
| 1 | Source-aware general-web provider | Complete | Exa MCP contract tests and live no-key search passed; GDELT remains news-only |
| 2 | Product understanding and research plan | Complete | Structured provenance profile and persisted intent tasks |
| 3 | Evidence-backed ICP generation | Complete | Exactly three differentiated ICPs; deterministic recommended ICP |
| 4 | Real account discovery and qualification | Complete | Domain validation, dedupe, size status, qualification reasons |
| 5 | Per-account signals, scoring, briefs | Complete | Evidence-only signal classes, decay, factor breakdown, allowed actions |
| 6 | Feedback and command-center UI | Complete | Feedback and QA persistence APIs plus visible qualification detail |
| 7 | Live SupportPilot acceptance | Complete | Manual top-10 QA persisted; post-fix live rerun measured honestly |
| 8 | Full gates and release decision | Complete | All engineering gates green; B-partial is not acceptable for merge |

## Quality gates

- Real-company rate: 100%
- Correct official-domain rate: at least 95%
- Useful ICP match: at least 80%
- Evidence coverage: at least 95%
- Relevant-signal rate: at least 80% where a signal is claimed
- Duplicate rate: under 5%
- Unsupported important claims: under 5%
- Working source links: at least 95%

An account without enough support is `INSUFFICIENT_EVIDENCE`, not silently
qualified. A company with no verified current event has no intent signal.

## Release rule

Classification `A` may merge. Classification `B` may merge only when limitations
are explicit and do not undermine the core proof. Classifications `C` and `D` must
not merge. No public deployment is part of this plan.

Final decision: `B — PARTIAL`, not acceptable for release. The post-fix live run
returned six borderline accounts and no verified current intent signals. Keep the
feature branch unmerged and proceed with an intelligence-quality improvement phase.
