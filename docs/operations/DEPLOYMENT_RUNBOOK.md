# GoPilot — Private Alpha Deployment Runbook

**Scope:** a limited, invite-only private alpha of `BYOA_CORE` on a single host.
Not a public launch. Not an autonomous-discovery release.

This runbook has been executed end to end, not merely written. Where a step has a
known caveat, it says so.

---

## 1. What gets deployed

| Service | Image | Exposed | Purpose |
|---|---|---|---|
| `web` | `apps/web/Dockerfile` | **yes**, `WEB_PORT` | Next.js UI |
| `api` | `Dockerfile.python` | no | FastAPI |
| `worker` | `Dockerfile.python` | no | Redis job consumer |
| `gateway` | `Dockerfile.python` | no | Public-source retrieval |
| `migrate` | `Dockerfile.python` | no | Runs once, before `api`/`worker` |
| `postgres` | `pgvector/pgvector:pg17` | no | Persistence |
| `redis` | `redis:7.4-alpine` | no | Job queue |

**Only `web` publishes a port.** The gateway retrieves arbitrary public URLs on
request; if it were reachable from outside the compose network it would be an open
fetch service. Keep it internal.

`docker-compose.yml` remains the local-development file (infrastructure only).
`docker-compose.private-alpha.yml` runs the whole product.

---

## 2. Prerequisites

- Docker Engine 24+ with Compose v2
- A host with 4 GB RAM and 10 GB free disk
- An OIDC issuer publishing a standard JWKS document (any provider; the free tier
  of a hosted identity service is sufficient)
- Outbound HTTPS from the host, for fetching applicant company websites

---

## 3. Configure

```bash
cp .env.private-alpha.example .env.private-alpha
```

Generate each secret locally. Never reuse a value from the template:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Fill in, at minimum:

| Variable | Notes |
|---|---|
| `POSTGRES_PASSWORD` | generated |
| `RESEARCH_GATEWAY_TOKEN` | generated, **32+ characters**; the gateway refuses to start in production without it |
| `JWT_ISSUER`, `JWT_AUDIENCE`, `JWKS_URL` | from your OIDC issuer |
| `PRIVATE_ALPHA_ALLOWED_SUBJECTS` or `PRIVATE_ALPHA_ALLOWED_EMAILS` | the invite list; **at least one must be non-empty** |

`.env.private-alpha` is covered by `.gitignore`. Confirm before proceeding:

```bash
git check-ignore -v .env.private-alpha
```

### Configuration that fails closed at startup

These are startup errors, not warnings. A misconfigured deployment does not boot:

- `APP_ENV=production` with `DEMO_AUTH_ENABLED=true` → refuses to start
- `APP_ENV=production` with `AUTH_MODE` other than `oidc` → refuses to start
- `AUTH_MODE=oidc` missing issuer, audience, or JWKS URL → refuses to start
- `JWT_ALGORITHMS` containing an HMAC algorithm → refuses to start (a JWKS public
  key must never be usable as a shared secret)
- `APP_ENV=production` without `RESEARCH_GATEWAY_TOKEN` → gateway refuses to start
- `PRIVATE_ALPHA_ENABLED=true` with both invite lists empty → refuses to start,
  because admitting nobody is far more likely a mistake than an intent

---

## 4. Deploy

```bash
docker compose -f docker-compose.private-alpha.yml --env-file .env.private-alpha up -d --build
```

Startup order is enforced by compose conditions, so nothing serves traffic against
an unmigrated schema:

```
postgres/redis healthy → migrate runs to completion → gateway → api → web
                                                    → worker
```

Watch it settle:

```bash
docker compose -f docker-compose.private-alpha.yml --env-file .env.private-alpha ps
docker compose -f docker-compose.private-alpha.yml --env-file .env.private-alpha logs -f api worker
```

---

## 5. Verify

```bash
# API health (from inside the network; the port is not published)
docker compose -f docker-compose.private-alpha.yml --env-file .env.private-alpha \
  exec api curl -fsS http://127.0.0.1:8000/health

# Migrations are at head
docker compose -f docker-compose.private-alpha.yml --env-file .env.private-alpha \
  exec api python -m alembic -c apps/api/alembic.ini current

# UI
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/
```

Then run the smoke test. It exercises the whole BYOA journey — invite gate,
workspace, product, run, import validation, import, duplicate detection, worker
research against **real company websites**, evidence-backed briefs, the outreach
gate, review, export and tenant isolation.

`--user` must name an identity on the invite list, otherwise the very first
workspace call is correctly refused with `403`:

```bash
docker compose -f docker-compose.private-alpha.yml --env-file .env.private-alpha \
  exec api python scripts/private_alpha_smoke.py --user <an invited subject>
```

It leaves its workspace behind for inspection and prints the exact command to
remove it (section 11).

---

## 6. Invites

Access is invite-only while `PRIVATE_ALPHA_ENABLED=true`. There is no public signup.

To invite someone, add their OIDC subject or email to
`PRIVATE_ALPHA_ALLOWED_SUBJECTS` / `PRIVATE_ALPHA_ALLOWED_EMAILS`, then:

```bash
docker compose -f docker-compose.private-alpha.yml --env-file .env.private-alpha \
  up -d api worker
```

Uninvited callers receive `403` even with a perfectly valid token. Revoking is the
same edit in reverse; it takes effect on the next restart.

**Caveat:** the invite list lives in configuration, so a change needs a service
restart. That is acceptable at alpha scale and avoids a migration for a table that
may not survive contact with real usage.

---

## 7. Limits

All configurable in `.env.private-alpha`. Every one returns an explicit `429` with
a machine-readable `code`, `limit` and `attempted` — **nothing is silently
truncated**, because a user who imports 300 accounts and receives 100 without being
told has been given a wrong answer, not a partial one.

| Variable | Default | Applies to |
|---|---:|---|
| `MAX_ACCOUNTS_PER_IMPORT` | 100 | one import request |
| `MAX_ACCOUNTS_PER_WORKSPACE` | 500 | total accounts held |
| `MAX_IMPORTS_PER_DAY` | 20 | rolling 24 h per workspace |
| `MAX_CONCURRENT_RESEARCH_RUNS` | 2 | in-flight runs per workspace |
| `MAX_WORKSPACES_PER_USER` | 3 | memberships per user |
| `MAX_EXPORT_ROWS` | 1000 | CSV export |
| `MAX_PAGES_PER_ACCOUNT` | 8 | official pages fetched per account |

---

## 8. Backup and restore

```bash
# Backup
docker compose -f docker-compose.private-alpha.yml --env-file .env.private-alpha \
  exec -T postgres pg_dump -U "$POSTGRES_USER" gtm | gzip > backup-$(date +%F).sql.gz

# Restore into an empty database
gunzip -c backup-YYYY-MM-DD.sql.gz | \
  docker compose -f docker-compose.private-alpha.yml --env-file .env.private-alpha \
  exec -T postgres psql -U "$POSTGRES_USER" gtm
```

Redis holds only the job queue. Losing it loses queued research, not evidence;
re-running research re-creates it. Back up PostgreSQL, not Redis.

---

## 9. Rollback

```bash
git checkout <previous-tag>
docker compose -f docker-compose.private-alpha.yml --env-file .env.private-alpha up -d --build
```

If the rollback crosses a migration, downgrade **before** starting the older code:

```bash
docker compose -f docker-compose.private-alpha.yml --env-file .env.private-alpha \
  run --rm migrate python -m alembic -c apps/api/alembic.ini downgrade -1
```

Take a backup first (section 8). Migration `0007` is index-only and reverses
cleanly; earlier migrations drop columns and are not loss-free.

---

## 10. Incidents

**Worker stopped processing.** Jobs are claimed with `BLMOVE` into a per-worker
in-flight list and released only once they settle, so an interrupted job is not
lost. Restarting reclaims it:

```bash
docker compose -f docker-compose.private-alpha.yml --env-file .env.private-alpha restart worker
```

Inspect the queues:

```bash
docker compose -f docker-compose.private-alpha.yml --env-file .env.private-alpha \
  exec redis redis-cli llen gtm:research-jobs
docker compose -f docker-compose.private-alpha.yml --env-file .env.private-alpha \
  exec redis redis-cli llen gtm:research-jobs:dead
```

A non-empty dead-letter queue means jobs exhausted `WORKER_MAX_ATTEMPTS`. The
failure is also recorded on the run or account, so the UI shows it rather than
appearing to still be working.

**Scaling out:** each worker instance needs a distinct `WORKER_NAME`. Recovery is
keyed on it, and duplicates would let one worker reclaim another's live job.

**Gateway returns 401.** `RESEARCH_GATEWAY_TOKEN` differs between `api`/`worker`
and `gateway`. They read the same variable, so restart the whole stack rather than
one service.

**Everything returns 403.** The caller is not on the invite list (section 6).

---

## 11. Data handling and deletion

See [PRIVATE_ALPHA_DATA_HANDLING.md](../security/PRIVATE_ALPHA_DATA_HANDLING.md).

---

## 12. Shutdown

```bash
# Stop, keep data
docker compose -f docker-compose.private-alpha.yml --env-file .env.private-alpha down

# Stop and destroy all data - irreversible, back up first
docker compose -f docker-compose.private-alpha.yml --env-file .env.private-alpha down -v
```

---

## 13. Known limitations at alpha

Stated plainly so nobody discovers them in production:

1. **The web app has no login screen.** The API verifies bearer tokens correctly,
   but the browser cannot yet obtain one. Until that lands, `AUTH_MODE=oidc` is not
   usable end to end from the UI.
2. **Single host, single worker.** No horizontal scaling, no load balancer.
3. **No TLS termination in compose.** Put the host behind a reverse proxy with a
   certificate before exposing it beyond localhost.
4. **Invite changes require a restart** (section 6).
5. **Autonomous discovery remains experimental** and is off by default. Do not
   present it as production-quality.
