# GoPilot — Private Alpha Readiness Assessment

> **Historical record.** This is a point-in-time snapshot. The blocker it
> describes (browser sign-in never exercised against a real issuer) was resolved
> later the same effort — see `scripts/verify_oidc_flow.py` and
> `docs/operations/DEPLOYMENT_RUNBOOK.md`. Left as-is rather than rewritten, as a
> record of what was verified when.

**Date:** 2026-08-08
**Branch:** `feature/private-alpha-hardening` (`5b2c2f3`)
**Base:** `develop` (`e5d1598`, PR #1 merged)
**Assessor:** Claude (lead engineer)

## Classification: **B — FUNCTIONAL BUT BLOCKED**

One blocker, and it is specific: **the browser sign-in flow has never been exercised
against a real OIDC issuer.** Everything else on the private-alpha checklist is
implemented and verified against real infrastructure.

I am not classifying this A. A private-alpha deployment requires `AUTH_MODE=oidc`
(production startup refuses anything else), so every invited user reaches the
product through a login path that has been written and type-checked but never once
completed end to end. Calling that ready would authorise a release of an unverified
front door.

---

## What was verified against real infrastructure

Not fixtures, not mocks. The full stack was built and deployed, and the smoke test
drove it against **real company websites** over the real internet.

| Check | Result |
|---|---|
| All 7 services healthy; migrations applied before any service took traffic | pass |
| Invite gate refuses an uninvited identity | pass (`403`) |
| `BYOA_CORE = AVAILABLE` with **no** search provider configured | pass |
| `AUTONOMOUS_DISCOVERY_EXPERIMENTAL = CONFIGURATION_REQUIRED` | pass |
| Unsafe domains rejected (`localhost`, `169.254.169.254`, directories) | pass |
| Accounts imported; duplicates reported, not silently merged | pass |
| Worker researched accounts via real HTTPS fetches | pass |
| Briefs evidence-backed (2–3 real source documents each) | pass |
| **No cross-company evidence attachment** | pass |
| Outreach draft cannot be approved unless `FOUNDER_READY` | pass (`409`) |
| `FOUNDER_READY` cannot be granted by hand | pass (`409`) |
| Export contains only approved rows, leaks no credentials | pass |
| Tenant isolation: another user cannot reach the workspace | pass (`403`) |
| `alembic check` against real PostgreSQL | **"No new upgrade operations detected."** |
| Deletion leaves zero orphans, other tenant untouched | pass |
| CI, all four jobs on this branch | pass |

Test suite: **275 passed, 9 skipped** (baseline at takeover was 172 with 2 errors).

---

## What clicking through the UI found that the smoke test never did

The smoke test passed. The product was still wrong in ways only reading a rendered
brief could reveal — the API returned a correct-looking payload, and the founder-facing
meaning of that payload was false.

**Site chrome was presented as verified evidence.** The brief for `djangoproject.com`
listed, under **VERIFIED PUBLIC EVIDENCE** and marked `SUPPORTED` at 82% confidence:

> "Menu Main navigation Overview Download Documentation News Code Issues Community
> Foundation Donate Search Submit Toggle theme (current theme: auto)…"

That is the product's central promise exactly inverted. `BOILERPLATE_TERMS` was only
applied inside `_evidence_passages`, and the fallback added earlier in this takeover
bypassed it — improving extraction recall had silently destroyed its precision.

**Fit was 0 for a correctly verified company.** Only `size_match` ever passed `None`,
so absent industry and geography evidence was scored as a hard `0` — unknown treated
as a verified mismatch, the one thing the product principles most explicitly forbid.
My own audit called scoring "correct" because I checked the renormalising mechanism
and never checked what was fed into it. Geography was also hardcoded to Indian
cities, so any founder targeting elsewhere could never score above zero.

**A non-mismatch was labelled a mismatch.** "Competitor overlap requires research; no
automatic rejection" was surfaced as **"Mismatch:"** because the classifier matched
the substring "competitor" — reading to a founder as a competitor conflict the system
had explicitly declined to assert.

**The dashboard asserted completion that had not happened** — a hardcoded active-run
count of 1, "Research is complete", "All above confidence threshold", and five ticked
workflow steps regardless of state.

All four are fixed, with regression tests built from the verbatim text the deployed
app rendered. The lesson mirrors the one below, one level up: a passing API contract
is not a truthful brief.

## What the real run found that fixtures never did

This is the most important finding of the whole takeover.

The offline evaluation reported "BYOA CORE QUALITY PASS". The deployed product
**could not move a single account out of `IDENTITY_REVIEW_REQUIRED`.**

1. **Every imported account was pinned to identity review, permanently.** Import
   wrote a "not yet verified" marker; nothing cleared it once research verified the
   domain. `decide_brief_state` returns `IDENTITY_REVIEW_REQUIRED` whenever any
   warning is present, so `MONITOR`, `RESEARCH_CANDIDATE` and `FOUNDER_READY` were
   all unreachable. The core workflow was broken end to end.

2. **A real company was reported as unverifiable.** `_sentences` discarded any
   segment over 700 characters, so `sqlalchemy.org` — whose homepage is one long run
   with almost no full stops — produced zero passages, and the account was labelled
   "the supplied official domain could not be verified". That was false: the domain
   had been fetched and its canonical form matched. Identity verification had been
   conflated with evidence extraction.

Both are fixed with regression tests. After the fix, both accounts reach
`RESEARCH_CANDIDATE` and `sqlalchemy.org` verifies with 2 real source documents.

**A fixture suite cannot find defects of this shape.** Every offline metric in the
historical QA record was measured against a product that could not produce a
non-review account.

---

## Remaining blocker

### 1. Browser sign-in is unverified (needs external credentials)

`apps/web/lib/auth.ts` implements Authorization Code with PKCE, discovered from the
issuer's well-known document — no client secret in the browser, no vendor hardcoded.
It type-checks, lints, and builds. It has never completed a real sign-in.

To close it I need, from an OIDC issuer of your choice (any free tier works):

- `JWT_ISSUER`, `JWT_AUDIENCE`, `JWKS_URL`
- `OIDC_CLIENT_ID` for a public client with PKCE
- the redirect URI `http://<host>:<port>/auth/callback` registered

Then the deployment can be brought up with `AUTH_MODE=oidc` and the flow driven end
to end. **Do not send me a client secret** — the PKCE flow does not use one, and I
would refuse to put one in a browser bundle.

---

## Accepted gaps (documented, not blocking)

Stated so nobody meets them by surprise in production. All are in the runbook.

| Gap | Why acceptable at alpha |
|---|---|
| No automatic data retention expiry | invite-only and small; deletion tooling exists and is verified |
| Observability is audit events, not the full metric set | events cover imports, runs, failures, exports; queue depth is one `redis-cli llen` |
| Invite changes need a service restart | avoids a migration for a table that may not survive contact with real usage |
| Single host, single worker, no TLS in compose | put it behind a reverse proxy; the runbook says so |
| Official-site failure matrix only partly exercised | redirects, oversized pages, 4xx and cross-domain redirects verified; robots, parked domains and expired TLS not |
| Evidence confidence is a hardcoded 0.82 for every passage | the per-fact confidence number carries no information and should be derived or removed |
| ~2,600 lines of historical acceptance scripts | inert; archiving is P2 |

---

## Readiness by dimension

| Dimension | Takeover | Now | Reasoning |
|---|---:|---:|---|
| BYOA product quality | 68 | **86** | Signal honesty fixed; identity review no longer terminal; site chrome no longer cited as evidence; unknown no longer scored as mismatch. Verified end to end against real sites and by reading rendered briefs. |
| Engineering quality | 62 | **78** | 275 tests, CI green, worker reliability, migration parity guarded by an executing test. Monolith and duplication remain. |
| Security | 55 | **86** | Gateway fails closed, addresses pinned against rebinding, invite gate, limits, secret scan tested against planted credentials. |
| Authentication | 8 | **72** | Backend verification is complete and thoroughly tested. Browser flow written but unverified. |
| Deployment | 15 | **80** | Full stack built, deployed and smoke-tested. No TLS, single host. |
| Autonomous discovery | 35 | **35** | Untouched and still correctly experimental — off by default in the private alpha. |
| **Overall** | **38** | **79** | One blocker, clearly scoped. |

---

## Recommendation

1. Provide OIDC issuer details and a public client ID (no secret).
2. I complete a real sign-in against the deployed stack.
3. Re-run the smoke test with `AUTH_MODE=oidc`, then re-read a rendered brief —
   the API passing is not sufficient evidence that the brief is truthful.
4. Re-classify. I expect **A** at that point.

Note for whoever continues this: every defect found after the audit was found by
running the product, and each one was invisible to the layer below it. Unit tests
missed what the deployed stack revealed; the deployed stack's passing smoke test
missed what reading the rendered brief revealed. Budget for looking at the output,
not just at green checks.

Until then: do not merge to `main`, do not tag, do not deploy publicly.
