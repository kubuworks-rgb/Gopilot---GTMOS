# Third-Party Notices

## Agent Reach

- Project: `Panniantong/Agent-Reach`
- Reviewed release: `v1.4.2`
- Reviewed release commit: `97e9e63`
- Review date: 2026-07-19

Agent Reach is a capability and setup router. It does not expose generic
`agent-reach search` or `agent-reach read` commands. This repository uses only the
documented `agent-reach doctor --json` health operation through a bounded wrapper;
research adapters invoke separately allowlisted upstream tools. Installation is a
controlled build/setup operation and is never request-triggered.

See the upstream repository for its license and transitive-tool terms.

## LangGraph

- Package: `langgraph`
- Pinned version: `1.2.9`
- License: MIT
- Use: fixed-stage checkpointable research workflow; no autonomous swarm.
