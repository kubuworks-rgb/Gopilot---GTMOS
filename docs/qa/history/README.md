# QA history

A build log, kept for transparency rather than for reading.

These are the phase-by-phase QA artifacts produced while GoPilot was built:
acceptance runs, evaluation replays, recall baselines, and the raw `.json`
dumps behind them. They record what was measured at the time, against the code
as it stood at the time. Several describe behaviour that has since changed —
the scoring fix in particular means numbers here will not match the current
implementation.

They are kept because deleting evidence after the fact is worse than keeping
evidence that has aged. If you want to know whether a claim in this repo was
measured or asserted, the answer is usually in here.

**Nothing in this folder is a current statement about the system.** For that,
read the two documents deliberately left at `docs/qa/`:

- [`LIVE_E2E_FINDINGS.md`](../LIVE_E2E_FINDINGS.md) — the full scenario walked
  against real infrastructure and real company websites, including the P0 that
  run found, how it was fixed, and the live re-verification.
- [`CLAUDE_PROJECT_TAKEOVER_AUDIT.md`](../CLAUDE_PROJECT_TAKEOVER_AUDIT.md) —
  the forensic audit of the codebase as inherited.

Names carry their original phase numbering (`PHASE5_`, `PHASE6_`,
`SUPPORTPILOT_` — a former product name). They have not been renamed, because
renaming an archive to look tidier makes it harder to match against the commit
history it belongs to.
