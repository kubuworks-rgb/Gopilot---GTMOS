# System Design

## Runtime selection

`RESEARCH_MODE=fixture` loads the in-memory fixture router. `RESEARCH_MODE=live`
loads the PostgreSQL router. Production validation forbids fixture mode and demo
authentication. The import-time selection prevents a failed live provider from
reaching the fixture repository.

## API and tenancy

Live dependencies open an async SQLAlchemy session and resolve membership by the
server-side user principal plus optional `X-Workspace-Id`. Repository methods scope
resource reads by workspace and return not-found for cross-tenant identifiers.
Local development may explicitly enable `X-Demo-User`; it fails closed when demo
auth is disabled.

## Jobs and workflow

The API creates a durable run, commits it, and pushes a `ResearchJob` JSON object to
`gtm:research-jobs`. Its `kind` is a Pydantic literal:

- `research`
- `discover_accounts`
- `research_account`
- `regenerate_brief`

The worker decodes the object and dispatches only those operations. Arbitrary code,
shell commands, and provider installation are impossible through the queue.

Run stages are explicit (`queued`, `planning`, `researching`, `extracting`,
`awaiting_icp`, `discovering_accounts`, `completed`, `partial`, `failed`). Searches,
documents, elapsed time, and account candidates are bounded by settings. Individual
source failures are persisted on research tasks/tool calls. Zero evidence fails the
run instead of substituting fixtures.

## Source trust boundary

The Research Gateway exposes typed internal endpoints. Web fetching performs DNS
validation, blocks private and metadata addresses, disables automatic redirects,
revalidates each redirect, limits bytes/content types/time, and strips active HTML.
Retrieved text receives prompt-injection classification and is always data.

URL canonicalization lowercases hosts, removes fragments/default ports/tracking
parameters, sorts the query, and normalizes trailing slashes. Normalized text is
SHA-256 hashed and deduplicated within a run. Chunks and provenance remain queryable.

## Evidence and scores

The conservative extractor stores exact source sentences as both passage and claim.
Before commit, each non-hypothesis fact must reference the same workspace and its
passage must exist in source text. Findings and brief claims reference those IDs.

Account evidence has a second, account-relative gate after source persistence.
The gate compares the source registrable domain, canonical company identity,
evidence-backed aliases and entity relationships, and claim scope. A source can be
first-party for its own entity without being first-party for the target account.
Different first-party domains are never merged by name or brand prefix alone.
Ambiguous facts remain in the attachment audit as
`UNATTACHED_ENTITY_AMBIGUOUS`; verified related-entity facts with incompatible
scope remain `RELATED_ENTITY_ONLY`. Neither can affect account signals, scores,
verified brief claims, or campaigns.

Persisted account identity records include the canonical name/domain, verified
official domains, evidence-backed aliases and relationships, identity confidence,
and unresolved warnings. Opportunity briefs expose one of `FOUNDER_READY`,
`RESEARCH_CANDIDATE`, `MONITOR`, `DO_NOT_TARGET`, or
`IDENTITY_REVIEW_REQUIRED`. Outreach copy is generated only for
`FOUNDER_READY`; every other state presents the missing evidence, reason not to
target when applicable, and next bounded research step.

Fit, Intent, and Confidence keep independent factors. Priority uses the existing
confidence-gated deterministic policy:

```text
priority = (fit * 0.55 + intent * 0.45) * confidence / 100
```

Unknown company size, location, or industry is displayed as `Unverified`, not
inferred. Intent exists only when source text contains a configured change-event
term; otherwise intent inputs are zero and the UI states that no signal is verified.

## Agent Reach

The pinned Agent Reach package is installed only during controlled development or
build setup. The gateway invokes `doctor --json` with no shell, a sanitized
environment, bounded output, a timeout, JSON validation, and caching. Its health
does not authorize tools. Direct gateway adapters retain their own capability
status, so a missing optional Agent Reach channel cannot crash the workflow.

## Observability

The schema persists research tasks, agent runs, tool calls, latency, backend, status,
error category, audit events, score versions, and brief versions. Logs and public
responses use safe error categories; credentials and raw authorization values are
not persisted.
