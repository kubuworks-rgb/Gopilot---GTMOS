# BYOA Core Product Decision

## Decision

Bring Your Own Accounts is the dependable GoPilot core MVP. Autonomous account
discovery remains available only as a separately labelled Experimental workflow.

## Core workflow

The default `BYOA_CORE` workflow is:

```text
Import Accounts -> Validate Accounts -> Research Accounts ->
Review Priorities -> Inspect Opportunity Briefs ->
Approve or Change Status -> Export
```

Users may supply one company and domain, paste domains, upload CSV content, or
call the account-import API. Each accepted account retains its import source and
`IMPORTED` provenance. Canonical registrable-domain deduplication prevents the
same company from entering a workspace twice.

## Provider independence

BYOA works without Exa or Tavily. It fetches bounded, allowed pages from the
supplied official domain through the existing safe Research Gateway. Search
providers are optional enrichment for imported accounts.

Automatic discovery requires `EXA_API_KEY` or `TAVILY_API_KEY` and returns
`CONFIGURATION_REQUIRED` when neither is configured. It never falls back to demo
accounts or anonymous production capacity.

## Evidence and identity safety

Official-domain evidence passes through the entity-attachment and claim-scope
gate before it may affect signals, scores, verified claims, or outreach. Unknown
criteria remain unknown. Unsupported or cross-company material remains visible
as rejected evidence and cannot promote an account.

All numeric scores are deterministic. A brief is `FOUNDER_READY` only when
identity, ICP support, important claims, actionable evidence, entity attachment,
and competitor safety satisfy the documented gate. `MONITOR`,
`RESEARCH_CANDIDATE`, `IDENTITY_REVIEW_REQUIRED`, and `DO_NOT_TARGET` are useful
outcomes rather than failures.

## Human control

Human review is mandatory. Users can approve a result or request changes, but
cannot manually override the evidence gate to create a founder-ready account.
Only founder-ready briefs may expose draft outreach language. GoPilot does not
send outreach autonomously.

## Release boundary

The private-alpha decision is based on a credential-free controlled BYOA
evaluation plus the full engineering gates. It does not promote Experimental
discovery, tune discovery thresholds, introduce another provider, or replace the
Phase 6 evidence.
