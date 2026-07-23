# Threat Model

Primary threats are cross-tenant access, SSRF/DNS rebinding, unsafe redirects,
prompt injection in sources, secret leakage, CSV formula execution, authorization
bypass, unapproved campaign state changes, and demo configuration in production.

Controls include server-side membership resolution, scoped repository methods,
HTTP(S)-only URL policy with private/link-local/loopback/metadata blocking and DNS
validation, redirect revalidation, content/time/size limits, untrusted-content
delimiting/classification, deterministic policy-owned scoring, redacted structured
logs, explicit approval transitions, and formula-safe exports. Production config
rejects demo auth and fixtures.

Residual risk: live upstream behavior and robots/terms vary. Adapters are disabled
unless configured and capability health never implies legal permission to fetch.
