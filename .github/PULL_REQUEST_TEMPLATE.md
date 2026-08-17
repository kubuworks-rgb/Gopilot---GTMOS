## What this changes and why

<!-- One or two sentences. Link an issue if there is one. -->

## Checklist

- [ ] `npm run lint` passes
- [ ] `npm run typecheck` passes
- [ ] `npm run test` passes
- [ ] `python scripts/secret_scan.py` passes (if you touched config, env
      handling, or anything credential-shaped)
- [ ] New/changed tests exercise real behavior (import and call the code under
      test — don't reimplement it as a parallel copy, and don't just check that
      a string appears in a file). See `CONTRIBUTING.md` for why this matters.
- [ ] If this fixes a bug, the new test was confirmed to fail without the fix
      (temporarily revert, watch it go red, then restore)
- [ ] No secrets, tokens, or real credentials anywhere in the diff — including
      test fixtures. Use an obviously-fake value with `# secret-scan: allow` if
      you need a credential-shaped string for a test.
- [ ] Doesn't cross a non-negotiable principle in `CONTRIBUTING.md`
      (deterministic scoring/identity/security, evidence-backed claims,
      fail-closed limits, no autonomous outbound action)
