# GoPilot — Private Alpha Data Handling

**Scope:** what the private alpha stores, for how long, what it never stores, and
how to delete it. Written for an operator answering a founder who asks "what do you
have on my company, and can you remove it?"

---

## 1. What is stored

| Data | Where | Origin |
|---|---|---|
| Workspace, membership | `workspaces`, `memberships` | user |
| Product profile | `product_profiles` | user-confirmed input |
| Imported accounts | `accounts` | user's import (name, domain, optional metadata) |
| Fetched public pages | `source_documents.cleaned_text` | public company websites |
| Page passages | `source_chunks` | derived from the above |
| Evidence facts | `evidence_facts` | derived passages with provenance |
| Signals | `intent_signals` | derived |
| Scores | `account_score_snapshots`, `account_score_factors` | deterministic computation |
| Briefs | `opportunity_briefs` | derived |
| Campaign drafts | `campaign_drafts` | generated, never sent |
| Audit events | `audit_events` | system |
| Feedback, QA | `feedback_events`, `qa_evaluations` | user |

Everything retrieved from the public web is **normalized text**, capped by
`GATEWAY_MAX_BYTES`. Raw HTML is not retained.

---

## 2. What is never stored or logged

- **Credentials.** No token, API key, JWKS response, database password, or
  `Authorization` header is written to a table or a log line. The secret scanner in
  CI enforces this against the repository, and when it reports a finding it prints
  only the file and line — never the value.
- **Raw uploaded files.** A CSV is parsed in memory; only validated rows persist.
  The original file is never written to disk.
- **Private personal data.** No social-cookie scraping, no CAPTCHA or paywall
  bypass, no scraping behind authentication. Only public pages, fetched as an
  anonymous client.
- **Full page bodies in logs.** Fetched content goes to the database as evidence,
  never to application logs.
- **Third-party enrichment.** No data broker, no CRM write-back.

Retrieved content is tagged `{"untrusted": true}` and never gains tool authority —
a fetched page cannot instruct the system.

---

## 3. Retention

At alpha there is **no automatic expiry**. Data persists until deleted, because
silently discarding a founder's evidence would be worse than keeping it.

| Data | Retention |
|---|---|
| Everything in section 1 | until workspace or account deletion |
| Redis job queue | transient; entries vanish once a job settles |
| Dead-letter queue | until manually drained |
| Container logs | Docker's default rotation |

Before general availability this needs a documented per-tenant retention window.
Tracked as a post-alpha item; the alpha is small enough and invite-only, so the
exposure is bounded and known.

---

## 4. Deletion

All deletion is workspace-scoped. `scripts/delete_workspace_data.py` refuses to
touch anything outside the workspace it is given.

```bash
# Preview - always run this first; it writes nothing
docker compose -f docker-compose.private-alpha.yml --env-file .env.private-alpha \
  exec api python scripts/delete_workspace_data.py --workspace-id <uuid> --dry-run

# Delete one account and everything derived from it
... --workspace-id <uuid> --account-id <uuid> --confirm

# Delete a research run and its evidence, keeping the accounts
... --workspace-id <uuid> --run-id <uuid> --confirm

# Delete the entire workspace
... --workspace-id <uuid> --confirm
```

Deletion relies on `ON DELETE CASCADE` from `workspaces`, so evidence, chunks,
signals, scores, briefs, drafts and audit rows are removed with the parent. Nothing
is soft-deleted: when an operator says data is gone, it is gone.

**Backups are separate.** A workspace deleted today still exists in yesterday's
`pg_dump`. Rotate backups on a schedule you can describe to a user, and record it
here once chosen.

---

## 5. Observability

Operational events recorded for the alpha (see `audit_events`):

- import accepted or rejected, with validation failure counts
- research run started, completed, failed
- account state distribution
- evidence counts, cross-entity rejections, signal accept/reject
- brief state distribution
- export completed
- worker job failures and dead-letter arrivals

Each carries a workspace ID, an actor ID, and a timestamp — never a token, never a
raw CSV, never a private note, never a page body.

---

## 6. Answering a data request

1. `SELECT * FROM audit_events WHERE workspace_id = ...` — what happened.
2. `SELECT canonical_url, retrieved_at FROM source_documents WHERE workspace_id = ...`
   — every public page fetched, and when.
3. Export approved accounts via `/api/v1/exports/accounts.csv`.
4. To erase: section 4, then confirm with the `--dry-run` preview showing zero rows.

Every stored fact traces to a source URL and a retrieval timestamp, so "where did
you get this?" always has a concrete answer.
