# MCP connection guide

CorpusGate exposes one Streamable HTTP endpoint at `/mcp`. Remote connections must
send `Authorization: Bearer <token>` on every request. REST's `X-API-Key` is intentionally not an
MCP credential.

## Private Tailscale connection (recommended)

Keep Compose bound to `127.0.0.1`, publish it to the tailnet with Tailscale Serve, and allow only
the intended users/devices in tailnet policy:

```bash
sudo tailscale serve --bg --https=443 http://127.0.0.1:8000
tailscale serve status
```

The client URL is `https://YOUR-NODE.YOUR-TAILNET.ts.net/mcp`. Add that hostname to
`CORPUSGATE_ALLOWED_HOSTS`; never open TCP 8000 in Oracle Cloud.

## Public HTTPS connection

Use the Caddy `public` profile only when private access is not possible. The client URL is
`https://documents.example.com/mcp`; Caddy handles TLS and the gateway still requires Bearer auth,
rate limits, and response budgets.

## Generic client configuration

Client configuration formats change independently. Use the client's current official
documentation and map these two values:

```json
{
  "url": "https://YOUR_PRIVATE_OR_PUBLIC_HOST/mcp",
  "transport": "streamable-http",
  "headers": {
    "Authorization": "Bearer YOUR_MCP_TOKEN"
  }
}
```

This is a field mapping, not a claim that every client accepts this exact JSON wrapper. Do not put
the token in a committed configuration file.

## Connection and tool smoke test

The official MCP Inspector supports a remote HTTP URL and custom headers. With Node.js/npm
available, start its UI against the server:

```bash
npx @modelcontextprotocol/inspector \
  --server-url https://YOUR_PRIVATE_OR_PUBLIC_HOST/mcp \
  --transport http \
  --header "Authorization: Bearer YOUR_MCP_TOKEN"
```

Then initialize the connection, list tools, call `list_documents`, and call `search_documents`
with a synthetic query and a small `max_tokens`. The repository integration test performs the same
protocol-level list/call smoke path in process.

## Common failures

| Symptom | Check |
|---|---|
| `401` | Header is exactly `Authorization: Bearer …`; token is current and at least 24 characters. |
| `421` / host rejection | Remote hostname is in `CORPUSGATE_ALLOWED_HOSTS`; recreate the gateway. |
| `429` | Slow the client or review the per-client rate limit. |
| Timeout during streaming | Proxy buffering is disabled and timeouts match `deploy/Caddyfile`. |
| Semantic request reports `lexical_fallback` | Run `./corpusgate doctor`, then check model cache and Qdrant health. |
| Empty search | Run `./corpusgate list-documents`, confirm `ready`, and try an exact lexical term. |

Protocol references: [MCP Streamable HTTP transport](https://modelcontextprotocol.io/specification/latest/basic/transports#streamable-http)
and [official Inspector repository](https://github.com/modelcontextprotocol/inspector).
