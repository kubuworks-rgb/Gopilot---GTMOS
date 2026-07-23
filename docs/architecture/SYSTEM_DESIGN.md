# System Design

The web client consumes only `/api/v1` typed JSON. FastAPI resolves the principal and
membership before repository access. Domain services enforce evidence and state
transition invariants. Research requests create workflow records immediately; a
worker can resume checkpointed stages. The local fixture provider completes the same
contract deterministically so the entire product remains demonstrable offline.

Production adapters use async SQLAlchemy with PostgreSQL/pgvector. Redis provides
jobs, bounded retries, and short-lived capability caches. Source payloads can be
moved to object storage while normalized text, passages, hashes, and provenance stay
queryable. List endpoints return summaries and never large source bodies.

The Research Gateway is a separate trust boundary. It performs scheme/host/DNS/
redirect/content validation before fetching and exposes only typed internal routes.
