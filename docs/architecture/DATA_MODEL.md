# Data Model

Tenant roots: users, workspaces, memberships. Product profiles, research runs,
workflow runs, source documents, relevant passages, evidence facts, findings,
competitors, ICPs, accounts, signals, score snapshots, opportunity briefs, campaigns,
approvals, feedback, exports, audit events, and agent/tool runs all carry workspace
scope either directly or through a scoped parent.

Evidence facts have claim, passage IDs, source IDs, confidence, status, observed time,
and provenance. Findings and personalization statements reference evidence facts.
Database constraints prevent invalid enum states; service validation prevents
dangling evidence references. See `docs/generated/DB_SCHEMA.md` for tables and keys.
