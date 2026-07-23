# GoPilot — GTM OS Architecture

The MVP is a typed Next.js 16 command center backed by a versioned FastAPI API.
Long-running research is represented as checkpointed workflow runs and executed by
a worker boundary. The default local experience uses deterministic fixtures, while
the same provider contracts support configured live research.

The primary aggregate is `AccountOpportunityBrief`. Findings link to validated
evidence facts, evidence links to passages, and passages retain original source
metadata. Fit, intent, confidence, and priority are computed by deterministic policy.

```text
Next.js -> FastAPI -> domain services -> repository
                   -> workflow queue -> worker
                   -> Research Gateway -> allowlisted public-source adapters
                                         -> Agent Reach/upstream tools
```

Production persistence targets PostgreSQL + pgvector through async SQLAlchemy;
Redis is the queue/cache. The fixture repository is an explicit development adapter,
not a production fallback. See `docs/architecture/` for detailed decisions.
