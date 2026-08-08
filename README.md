# GoPilot — GTM OS

GoPilot is an evidence-backed GTM research and account-intelligence operating
system for founder-led B2B teams. Its core MVP is **Bring Your Own Accounts
(BYOA)**: import known company domains, validate their identity, research allowed
official sources, calculate deterministic scores, inspect opportunity briefs,
review the result, and export approved records.

GoPilot exposes two product modes:

- `BYOA_CORE` is the default and works without Exa, Tavily, or another search
  provider.
- `AUTONOMOUS_DISCOVERY_EXPERIMENTAL` is a separate, secondary workflow. It
  requires a configured search provider, is explicitly labelled Experimental,
  and requires human review of every discovered account.

The repository has two deliberately separate modes:

- `fixture`: the default offline product demo. Every fixture source is marked
  `DEMO DATA`.
- `live`: PostgreSQL persistence, Redis jobs, an isolated public-source gateway,
  normalized source documents, exact-passage evidence, and no fixture fallback.

Live mode never converts an upstream failure into demo output. A run records a
typed failed or partial state instead. A successful search with no relevant
articles completes explicitly at `no_relevant_results`.

Runtime data mode (`fixture` or `live`) is separate from product mode
(`BYOA_CORE` or `AUTONOMOUS_DISCOVERY_EXPERIMENTAL`). Live BYOA uses the supplied
official domains directly and never substitutes fixture accounts.

## Product contract

The primary unit of value is an `AccountOpportunityBrief`, not a scraped lead.
Each brief contains:

- separate Fit, Intent, Confidence, and confidence-gated Priority scores;
- editable score factors with their inputs, weights, contributions, and evidence;
- evidence-linked “Why it fits” and “Why now” claims;
- current signals only when a persisted source passage supports them;
- source URLs, retrieval timestamps, hashes, and provenance;
- explicit hypotheses where evidence is absent;
- explicit ICP matches, mismatches, and unknown criteria;
- ambiguous or rejected evidence that cannot affect scoring;
- one of `FOUNDER_READY`, `RESEARCH_CANDIDATE`, `MONITOR`,
  `IDENTITY_REVIEW_REQUIRED`, or `DO_NOT_TARGET`;
- an editable draft only when the brief is `FOUNDER_READY`.

Human approval is mandatory before outbound use. GoPilot does not autonomously
send outreach.

## Architecture

```mermaid
flowchart LR
    Web["Next.js command center"] --> API["FastAPI /api/v1"]
    API --> DB["PostgreSQL"]
    API --> Queue["Redis typed jobs"]
    Queue --> Worker["Bounded worker"]
    Worker --> Gateway["Research Gateway"]
    Gateway --> WebSearch["General web search"]
    Gateway --> GDELT["GDELT news intelligence"]
    Gateway --> HTTP["Safe public webpage fetch"]
    Gateway --> GitHub["Public GitHub via gh"]
    Gateway --> RSS["RSS and Atom"]
    Gateway --> YouTube["YouTube metadata and public subtitles"]
    Gateway --> Reach["Agent Reach capability health"]
```

Application requests cannot install tools or execute arbitrary commands. Retrieved
text is untrusted data and never gains tool authority. Agent Reach is a reviewed,
pinned capability router; source retrieval uses separately allow-listed adapters.

See [ARCHITECTURE.md](ARCHITECTURE.md),
[SYSTEM_DESIGN.md](docs/architecture/SYSTEM_DESIGN.md), and
[SOURCE_POLICY.md](docs/security/SOURCE_POLICY.md).

## Repository structure

```text
apps/web/                    Next.js command center and live actions
apps/api/                    FastAPI routes, domain services, repositories, migrations
services/research_gateway/   Public-source adapters and URL/content policy
services/worker/             Typed Redis job consumer
scripts/live_smoke.ps1       End-to-end public-source smoke harness
scripts/gdelt_control_smoke.py  Isolated known-positive GDELT control
docs/                        Product, architecture, security, and execution plans
```

## Local setup

Prerequisites: Node.js 22+, Python 3.11+, npm, and Docker Desktop.

```powershell
python -m pip install -r apps/api/requirements-dev.txt
npm.cmd install
docker compose up -d
python -m alembic -c apps/api/alembic.ini upgrade head
```

Fixture mode remains the default:

```powershell
npm.cmd run dev
```

Open [http://localhost:3000](http://localhost:3000). The API listens on
[http://127.0.0.1:8000](http://127.0.0.1:8000).

## Live mode

Copy `.env.example` to `.env`, then set at least:

```text
RESEARCH_MODE=live
DEMO_AUTH_ENABLED=true
DATABASE_URL=postgresql+asyncpg://gtm:gtm@127.0.0.1:5432/gtm
REDIS_URL=redis://127.0.0.1:6379/0
AGENT_REACH_ENABLED=true
AGENT_REACH_GATEWAY_URL=http://127.0.0.1:8010
```

`DEMO_AUTH_ENABLED=true` is only for local live development. Production startup
rejects demo auth and fixture research, and production needs a verified auth
integration.

Run the services in separate terminals:

```powershell
python -m uvicorn services.research_gateway.app.main:app --port 8010
python -m uvicorn apps.api.app.main:app --port 8000
python -m services.worker.app.main
npm.cmd run dev --workspace apps/web
```

The primary UI workflow is:

```text
Import Accounts -> Validate Accounts -> Research Accounts ->
Review Priorities -> Inspect Opportunity Briefs ->
Approve or Change Status -> Export
```

Single-company, pasted-domain-list, and CSV imports are supported. Imported and
discovered provenance are displayed separately. When no search provider is
configured, the UI states: “Account research is available. Automatic account
discovery requires a configured search provider.”

The public-source smoke harness sends the confirmed product and target-market query
to the configured search provider and fetches returned public URLs:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/live_smoke.ps1
```

Review that egress before running it in a controlled environment.

Search transports are configured explicitly and are optional for BYOA enrichment.
Automatic discovery requires `EXA_API_KEY` or `TAVILY_API_KEY`; Exa is primary
when both are configured. The production path does not depend on anonymous MCP
capacity. Requests with the `news` purpose may route to GDELT for time-sensitive
company events. GDELT is never used as a replacement for official-site, pricing,
careers, product, or technical-documentation discovery.

## Research lifecycle

1. Store a user-confirmed product profile.
2. Create a `BYOA_CORE` run and select the user-confirmed ICP.
3. Import and validate company names and public official domains.
4. Fetch bounded, allowed official pages through the gateway without web search.
5. Canonicalize URLs, normalize text, hash and deduplicate documents, and chunk
   durable content.
6. Attach claims only when exact evidence belongs to the supplied company.
7. Separate verified facts, unknowns, hypotheses, and rejected evidence.
8. Detect current signals only when supported and dated.
9. Calculate deterministic Fit, Intent, Confidence, and Priority scores.
10. Generate a stateful opportunity brief for human review and safe export.

The separate Experimental workflow adds provider-backed account discovery before
steps 4-10. It never implies that discovered accounts are founder-ready.

Every run persists counters, stage, errors, agent runs, tool calls, and audit events.

## Agent Reach

Agent Reach is pinned to release `v1.4.2`, full commit
`97e9e63f42c89cbf527386343723c1fde610b4cb`. The dependency is installed during
controlled project setup, never by an application request.

The gateway runs `agent-reach doctor --json` through an argument-vector subprocess
with a sanitized environment, timeouts, output limits, validated JSON, and a cache
TTL. On Windows it safely falls back to `python -m agent_reach.cli` when the user
Scripts directory is not on `PATH`.

## Gateway routes

All routes are under `/internal/v1`:

- `GET /health`
- `GET /capabilities`
- `POST /search`
- `POST /fetch`
- `POST /github`
- `POST /rss`
- `POST /youtube`
- `POST /fetch/validate`

Set `RESEARCH_GATEWAY_TOKEN` on both API and gateway to require an internal header.

## Verification

```powershell
npm.cmd run test
npm.cmd run lint
npm.cmd run typecheck
npm.cmd run build
python -m alembic -c apps/api/alembic.ini upgrade head --sql
```

With migrated PostgreSQL and Redis running:

```powershell
$env:RUN_LIVE_DB_TESTS="1"
python -m pytest apps/api/tests/test_live_database_integration.py
```

The integration suite proves durable product/run/source/evidence/ICP/account/score/
brief records and a Redis job round trip using a test-only controlled transport.
It does not claim that a public-web smoke occurred.

## Security invariants

- Resolve membership server-side before tenant data access.
- Reject cross-workspace resources.
- Reject fixture research and demo auth in production.
- Require evidence IDs for supported findings and claims.
- Keep numeric scoring deterministic and outside LLM output.
- Block localhost, private/link-local addresses, URL credentials, unsafe schemes,
  DNS rebinding, and lookalike platform domains.
- Revalidate every redirect.
- Do not bypass CAPTCHAs, paywalls, authentication, robots, or platform controls.
- Do not scrape private personal data or reuse social cookies.
- Do not send outreach autonomously.
- Neutralize CSV formula prefixes.

## Current limitations

- Production JWT/JWKS authentication is not implemented; local live mode uses the
  explicitly enabled demo principal.
- The current extraction and brief generator are deterministic and conservative;
  no live LLM or embedding provider is required.
- Automatic discovery is unavailable until an authenticated search provider is
  configured; BYOA import, research, review, and export remain available.
- Account identity, industry, geography, and employee size remain `Unverified`
  unless source text proves them.
- Public search availability and result quality depend on the configured upstream.
- The no-key Exa tier is rate-limited; production workloads should configure an
  API key and retain explicit partial/failure behavior.
- The public-web smoke must only run in an environment that explicitly permits
  sending its queries to the configured provider.

## License and notices

No repository license has been granted unless the owner adds one. Third-party
details are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
