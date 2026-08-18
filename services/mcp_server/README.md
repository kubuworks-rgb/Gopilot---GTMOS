# GoPilot MCP server

Exposes GoPilot's research capability — and, more usefully, its entity-safety
gate — over the Model Context Protocol, so an agent can use them directly.

Speaks MCP over stdio. No SDK dependency: the protocol surface needed here is
small enough that the standard library covers it.

## Tools

| tool | needs a running API | what it does |
|---|---|---|
| `check_entity_attachment` | **no** | Decide whether a passage may support a claim about a company, or whether it is about a different or merely related one. Returns a decision plus the reason. |
| `list_accounts` | yes | Researched accounts with deterministic fit / intent / confidence / priority. |
| `get_account_brief` | yes | A brief with the evidence passage and source URL behind each claim, what is still unknown, and how much of the site was actually read. |

`check_entity_attachment` is the interesting one and deliberately needs nothing
running — it is useful to anyone building a retrieval pipeline, whether or not
they care about GTM. It is the [entity-safety](../../packages/entity-safety)
package behind a protocol.

## Read-only by construction

GoPilot never acts: it sends no outreach, and `FOUNDER_READY` is earned from
evidence rather than granted. An agent protocol is exactly where that would
quietly erode, so it is enforced rather than documented:

- No tool approves, sends, promotes, or writes anything — there is no such tool
  to call.
- The server can only issue `GET`. `ALLOWED_HTTP_METHODS` is a single-element
  constant, and a test asserts no mutating verb appears anywhere in the source,
  so a future tool cannot add one quietly.
- `apps/api/tests/test_mcp_server.py` walks the advertised tool list and fails
  if any tool is *named* for an action.

Approving a draft or changing an account's state remains a human action in the
GoPilot UI.

## Running it

The entity tool alone needs nothing:

```bash
pip install -e packages/entity-safety
python -m services.mcp_server.main
```

For the two research tools, start GoPilot in demo mode first — no API keys, no
Docker, no database:

```bash
npx gopilot -y
```

Point an MCP client at the command. For Claude Desktop, in
`claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "gopilot": {
      "command": "python",
      "args": ["-m", "services.mcp_server.main"],
      "cwd": "/absolute/path/to/Gopilot---GTMOS",
      "env": { "PYTHONPATH": "/absolute/path/to/Gopilot---GTMOS" }
    }
  }
}
```

### Configuration

| variable | default | meaning |
|---|---|---|
| `GOPILOT_API_BASE` | `http://127.0.0.1:8000/api/v1` | Where the API is. |
| `GOPILOT_DEMO_USER` | `demo-user` | Demo-mode identity. |
| `GOPILOT_TOKEN` | — | Bearer token, when the API runs with OIDC instead of demo auth. |

## Trying it without a client

It is line-delimited JSON-RPC, so a pipe is enough:

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize"}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | python -m services.mcp_server.main
```

The entity check, on the collision the gate exists to catch:

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"check_entity_attachment","arguments":{"target_name":"Optivian","target_domain":"optivian.ai","source_url":"https://optivian.cloud/press/series-b","source_role":"FIRST_PARTY","passage":"Optivian today announced a $40M Series B."}}}' \
  | python -m services.mcp_server.main
```

Returns `UNATTACHED_ENTITY_AMBIGUOUS` — *"Different first-party domain has no
verified account relationship."* Same brand token, same industry, plausible
headline, wrong company.
