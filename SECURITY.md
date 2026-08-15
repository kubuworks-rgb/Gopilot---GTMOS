# Security Policy

## Reporting a vulnerability

Please report security issues privately, not as a public GitHub issue.

Use [GitHub Security Advisories](https://github.com/kubuworks-rgb/Gopilot---GTMOS/security/advisories/new)
for this repository. That opens a private conversation with maintainers before
anything is public.

Please include:

- What you found and why it's a security issue, not just a bug.
- Steps to reproduce, or a minimal proof of concept.
- The affected file(s)/endpoint(s) if you know them.

You should get an acknowledgement within a few days. There's no bug bounty —
this is a portfolio project, not a funded product — but real reports get fixed
and credited.

## What counts

This project takes authentication, tenant isolation, and evidence integrity
seriously, because they're the parts of the product that are supposed to be
trustworthy by construction, not by luck. In scope:

- Authentication or session handling (`apps/api/app/security/`,
  `apps/api/app/api/dependencies.py`, `apps/api/app/api/live_routes.py`)
- Cross-tenant data access (workspace membership checks)
- The research gateway's URL/SSRF handling (`services/research_gateway`)
- Anything that lets untrusted retrieved web content gain tool authority
- Secrets handling — see `scripts/secret_scan.py` for what's already checked
- CSV export injection or other output-encoding issues

Not particularly interesting to report: rate-limit tuning, missing security
headers on the local dev server, or anything that only affects
`services/dev_oidc` (a test issuer that authenticates nobody and refuses to
start outside development — see its docstring).

## Track record

This isn't a claim of a clean record — it's the opposite. During development,
an internal review found that the invite-gate (`assert_invited`) was enforced
by only one of the two API routers, so a validly-signed but uninvited identity
could reach the fixture-mode router unchallenged. It was fixed, and a
regression test (`test_both_routers_enforce_the_invite_gate` in
`apps/api/tests/test_router_contract_parity.py`) now fails the build if that
specific class of bug reappears. Mentioned here factually, not as a badge —
real projects have real bugs, and what matters is whether they get found and
closed with a test that outlives the fix.

## Supported versions

This is a single-branch project without long-term-support releases. Security
fixes land on `main`; there's no older version being patched separately.
