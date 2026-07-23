# Research Architecture

## Boundary

`FastAPI -> Research Gateway -> allowlisted adapter -> upstream capability`.
The main API never executes Agent Reach or shell commands. Gateway requests have
explicit budgets and adapters return one unified source-document schema.

## Agent Reach review

Reviewed upstream release `v1.4.2`, commit `97e9e63`, on 2026-07-19. The release
documents `agent-reach doctor --json`. Agent Reach has no unified search/read API;
its documented model is to use upstream tools such as `gh`, `yt-dlp`, Jina/curl, or
feedparser after capability setup. The gateway therefore uses Agent Reach only for
cached capability health and invokes separately allowlisted adapters.

MVP allowlist: public HTTP(S) webpages, RSS, public GitHub, public YouTube metadata or
legitimately available transcripts. Social cookie automation is prohibited.

Fetch pipeline: validate URL and DNS -> fetch with time/redirect/size limits ->
canonicalize -> validate content -> hash/deduplicate -> classify prompt injection and
PII -> clean/chunk -> extract entities/facts -> validate/store evidence. External
content is data and cannot modify tools, scoring, secrets, approvals, or policy.
