# GoPilot — Exposing a Deployment Safely

**Scope:** what is required to put GoPilot on the public internet, and what happens
if a step is skipped.

The operational runbook — startup order, backups, incidents, invites — is
[PRIVATE_ALPHA_DEPLOYMENT_RUNBOOK.md](PRIVATE_ALPHA_DEPLOYMENT_RUNBOOK.md). This
document covers exposure only.

---

## The three requirements

Public exposure needs all three. **None of them is optional, and none is a default.**

| # | Requirement | Without it |
|---|---|---|
| 1 | Reverse proxy with TLS | Credentials and evidence cross the internet in plaintext |
| 2 | Real OIDC credentials | The app refuses to start; there is no way in |
| 3 | Invite list | Startup fails rather than admitting everyone |

### 1 · Reverse proxy with TLS

`docker-compose.private-alpha.yml` publishes `web` on a plain HTTP port. That is
correct for `localhost` and **wrong for anything else**.

```bash
# in .env.private-alpha
DOMAIN=gopilot.example.com
ACME_EMAIL=ops@example.com
```

```bash
docker compose -f docker-compose.private-alpha.yml -f docker-compose.tls.yml \
  --env-file .env.private-alpha up -d
```

The overlay adds Caddy, which obtains and renews certificates automatically, and
**removes the published port from `web`** so it is reachable only through the proxy.
That ordering is deliberate: forgetting the overlay leaves the service unreachable
from outside rather than silently serving plaintext.

Caddy was chosen over nginx + certbot because renewal is automatic. A forgotten
`certbot renew` is the most common way a small deployment ends up serving a browser
warning, and a warning is exactly the wrong first impression for a product whose
argument is trustworthiness.

**Only `web` is ever exposed.** `api`, `worker` and `gateway` stay on the internal
network. The gateway fetches arbitrary public URLs on request; exposing it would
hand anyone a fetch proxy.

### 2 · Real OIDC credentials

Production requires `AUTH_MODE=oidc` with a real issuer:

```bash
AUTH_MODE=oidc
DEMO_AUTH_ENABLED=false
JWT_ISSUER=https://<issuer>/
JWT_AUDIENCE=<audience>
JWKS_URL=https://<issuer>/.well-known/jwks.json
OIDC_CLIENT_ID=<public client id>
```

Register `https://<DOMAIN>/auth/callback` as a redirect URI. The browser flow is
Authorization Code with PKCE, so **there is no client secret** — if a provider hands
you one for this client, you have configured a confidential client by mistake.

> **Known gap.** The browser sign-in flow has never completed against a real issuer.
> The API's token verification is complete and tested; the front door is not
> verified. Do not invite users until it has been.

### 3 · Invite list

```bash
PRIVATE_ALPHA_ENABLED=true
PRIVATE_ALPHA_ALLOWED_SUBJECTS=<oidc subject>,<another>
# or
PRIVATE_ALPHA_ALLOWED_EMAILS=founder@example.com
```

Both empty with the private alpha on is a startup error, not a warning: an empty
list would admit nobody, which is far more likely a mistake than an intent.

---

## What fails loudly, and what does not

The configuration is designed so that unsafe states refuse to start rather than
running in a degraded mode.

| Mistake | What happens |
|---|---|
| `APP_ENV=production` with `DEMO_AUTH_ENABLED=true` | Refuses to start |
| `APP_ENV=production` with `AUTH_MODE=demo` | Refuses to start |
| `AUTH_MODE=oidc` missing issuer/audience/JWKS | Refuses to start |
| An HMAC algorithm in `JWT_ALGORITHMS` | Refuses to start |
| Production without `RESEARCH_GATEWAY_TOKEN` | Gateway refuses to start |
| Private alpha with both invite lists empty | Refuses to start |
| `RETENTION_AUTO_DELETE=true` | Refuses to start — not implemented |
| A gateway token under 32 characters | Refuses to start |
| Production with `http://` in `JWT_ISSUER`, `JWKS_URL` or `AGENT_REACH_GATEWAY_URL` | Refuses to start |
| Production with a non-loopback `http://` origin in `CORS_ALLOWED_ORIGINS` | Refuses to start |

The last two are the TLS checks. `JWKS_URL` is the one that matters most: fetched
over plaintext, the token signing keys can be substituted in transit, and the API
will then accept tokens minted by whoever substituted them. That is an
authentication bypass that leaves no trace and looks like normal operation, so a
production configuration naming an `http://` JWKS endpoint is refused outright.

Loopback origins stay allowed, because the proxy reaches the app over `127.0.0.1`
and that hop never leaves the host.

**What still does not fail loudly:** whether the proxy in front of you is actually
terminating TLS correctly. The checks above prove the configuration was written
for https; they cannot prove a certificate is valid, current, or served. An
operator who sets `APP_ENV=production` and the right URLs but never starts the
overlay still gets a service answering in plaintext on the published port.
Nothing inside the application can see that, so verify it from outside:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' http://<DOMAIN>/    # expect 308 → https
curl -sSI https://<DOMAIN>/ | head -3                          # expect 200 + HSTS
```

If the first returns `200` rather than a redirect, the overlay is not running and
the service is answering in plaintext. Do not announce the URL.

---

## Pre-exposure checklist

- [ ] TLS overlay running; `http://` redirects to `https://`
- [ ] `web` is the only service with published ports
- [ ] `AUTH_MODE=oidc` against a real issuer, redirect URI registered
- [ ] **Browser sign-in completed end to end at least once** ← currently unverified
- [ ] Invite list populated with real identities
- [ ] `RESEARCH_GATEWAY_TOKEN` set, 32+ characters, generated not reused
- [ ] `POSTGRES_PASSWORD` generated, not the template default
- [ ] Backup taken and a restore rehearsed
- [ ] Retention window agreed and stated on the Settings screen
- [ ] `docker compose ... exec api python scripts/private_alpha_smoke.py --user <invited>` passes

## Not covered

Multi-host deployment, load balancing, log shipping, uptime monitoring and paging
are out of scope for a private alpha and are not configured. A single host with
backups is the intended shape.
