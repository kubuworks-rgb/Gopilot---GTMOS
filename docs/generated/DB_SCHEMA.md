# Database Schema Summary

The Alembic base migration creates `workspaces`, `memberships`, `product_profiles`,
`research_runs`, `source_documents`, `evidence_facts`, `icps`, `accounts`, `signals`,
`score_snapshots`, `campaigns`, and `audit_events`. UUID primary keys, workspace
indexes, foreign keys, timestamps, JSONB payloads, and status checks preserve tenant
and workflow structure. `vector` is enabled for future passage embeddings.

The fixture repository mirrors these aggregate boundaries in memory for deterministic
development; it is rejected by production configuration.
