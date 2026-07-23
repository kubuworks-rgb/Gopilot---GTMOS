# GoPilot — GTM OS Architecture

GoPilot has one product surface and two explicit provider modes. Fixture mode is a
deterministic offline demo. Live mode binds the FastAPI routes to async SQLAlchemy,
PostgreSQL, Redis jobs, the worker, and the isolated Research Gateway. There is no
fallback from live to fixture.

```text
Next.js -> FastAPI -> fixture repository                         (fixture)
                 \-> PostgreSQL repository -> Redis -> worker    (live)
                                                     \-> gateway -> public adapters
```

The API resolves the principal and workspace membership before tenant queries. A
live research request commits its run before enqueueing a typed job. The worker
accepts only an allow-listed job kind and identifier; queue payloads cannot contain
commands or tool instructions.

The gateway owns public network access, URL and redirect validation, content-size
limits, exact-domain rules, and untrusted-content classification. Agent Reach is
used only for capability discovery. General-web search, GDELT news intelligence,
safe webpage reading, GitHub, RSS, and YouTube call their reviewed upstream
transports directly. GDELT is an additive news channel, not a substitute for
general-web or official-site discovery.

Durable lineage is:

```text
research_run -> research_task -> source_document -> source_chunk
                                             \-> evidence_fact -> finding / ICP
account -> account_research_snapshot -> intent_signal
       \-> account_score_snapshot -> score_factor
       \-> opportunity_brief -> campaign_draft -> approval_request
research_run -> agent_run -> tool_call
```

Supported claims carry evidence IDs. Each persisted passage is validated as a
substring of its source document, overlapping chunks ensure passages can resolve
to a durable chunk, and the evidence API exposes that chunk ID. Numeric scores are
calculated by deterministic policy; a model can never supply the final score.

See [docs/architecture/SYSTEM_DESIGN.md](docs/architecture/SYSTEM_DESIGN.md) for
runtime details.
