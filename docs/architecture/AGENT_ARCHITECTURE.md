# Agent and Workflow Architecture

The MVP workflow is bounded and stage-based: product analyst -> research planner ->
market/competitor intelligence -> ICP generator -> account discovery -> account
research -> scoring -> opportunity brief -> campaign draft. Each stage reads typed
state and emits schema-validated domain data. In fixture mode, a deterministic
provider produces the same shapes without pretending to be live AI.

Agents may request `research.web`, `research.rss`, `research.github`, and
`research.youtube_transcript`. They never receive arbitrary shell, secret, raw DB
admin, approval, or outbound-send tools. External text is delimited untrusted input.
Prompts are versioned and require evidence IDs, confidence, and claim status.

Workflow runs store identifiers, stage, timestamps, completion mode
(`completed|partial|failed`), budgets, and typed errors. Stages run as a fixed,
checkpointable sequence in `apps/api/app/services/live_research.py`; the
deterministic provider drives the acceptance path without an LLM or unconstrained
agent loop.

> This document predates a later simplification pass and its stage list may not
> match `live_research.py` exactly. Treat the code as authoritative until this is
> revised.
