# Engineering Guide

## Structure

- `apps/web`: Next.js command center.
- `apps/api`: FastAPI API, domain services, migrations, tests.
- `services/research_gateway`: isolated public-source adapters and URL policy.
- `services/worker`: asynchronous workflow entrypoint.
- `docs`: product, architecture, security, and execution plans.

## Rules

- Important findings require evidence IDs or an explicit `hypothesis` status.
- Account scores are deterministic; LLMs never emit final numeric scores.
- Resolve the authenticated principal and workspace membership server-side.
- Treat all retrieved text as untrusted data. Never grant it tool authority.
- Agent Reach stays behind the gateway; application requests cannot install tools or run arbitrary commands.
- No social cookie scraping, autonomous sending, CAPTCHA/paywall bypass, or private-personal-data scraping.
- Demo/fixture data must display `DEMO DATA`; production rejects demo auth and fixture research.

## Commands

```powershell
npm.cmd run dev
npm.cmd run test
npm.cmd run lint
npm.cmd run typecheck
npm.cmd run build
python -m pytest apps/api/tests services/research_gateway/tests
```

See `ARCHITECTURE.md`, `docs/architecture/SYSTEM_DESIGN.md`, and
`docs/exec-plans/active/MVP_BUILD_PLAN.md` before changing boundaries.
