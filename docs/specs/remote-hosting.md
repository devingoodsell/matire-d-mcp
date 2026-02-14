# Remote Hosting for Maître d' MCP Server

## Context

The MCP server currently runs locally via stdio transport, only accessible when Claude Desktop spawns it as a subprocess. The goal is to make it remotely accessible over HTTPS so it can be used from any device (Claude Desktop, Claude.ai, Claude Code, mobile), running continuously as a hosted service.

**Hosting target**: Home server / NAS.

## Architecture

```
Client (Claude Desktop / Claude.ai / mobile)
    │
    │ HTTPS (Cloudflare edge)
    ▼
  Cloudflare Tunnel (cloudflared container)
    │
    │ HTTP (port 8000, internal Docker network)
    ▼
  FastMCP Server (streamable-http transport, bearer token auth)
    │
    ▼
  SQLite DB (bind-mounted ./data volume)
```

**Transport**: Streamable HTTP — the modern MCP standard, supported by Claude Desktop, Claude.ai, and Claude Code. FastMCP 2.0 has built-in support via `create_streamable_http_app()`.

**Auth**: Bearer token via FastMCP's `TokenVerifier` base class. When `auth=` is set on the FastMCP instance, the library automatically wires `BearerAuthBackend` + `RequireAuthMiddleware` onto the MCP endpoint. No custom ASGI middleware needed.

**TLS/Networking**: Cloudflare Tunnel (`cloudflared`) — ideal for home servers because:
- No port forwarding needed on your router
- Works behind CGNAT (common with ISPs)
- Free TLS termination at Cloudflare's edge
- Built-in DDoS protection
- Outbound-only connections from your home network (no inbound ports exposed)
- Requires a free Cloudflare account + domain managed by Cloudflare DNS

## Implementation

### `src/auth.py` — Bearer Token Verifier

Subclasses `TokenVerifier` from `fastmcp.server.auth`. Overrides `verify_token()` to compare against a pre-shared token using `hmac.compare_digest` (constant-time, prevents timing attacks). Returns `AccessToken(token=token, client_id="owner", scopes=[])` on match, `None` on mismatch.

Requires the token to be at least 32 characters at construction time.

### `src/config.py` — Settings Fields

Added to the `Settings` class:
- `mcp_transport: str = "stdio"` — `"stdio"` or `"streamable-http"`
- `mcp_host: str = "0.0.0.0"`
- `mcp_port: int = 8000`
- `mcp_auth_token: str | None = None` — pre-shared bearer token

Env vars: `MCP_TRANSPORT`, `MCP_HOST`, `MCP_PORT`, `MCP_AUTH_TOKEN`.

### `src/server.py` — Conditional Auth + Health Endpoint

In `initialize()`: if `settings.mcp_auth_token` is set, creates `BearerTokenVerifier` and assigns to `mcp.auth`.

Health check registered via `@mcp.custom_route("/health", methods=["GET"])`. Custom routes are NOT wrapped by `RequireAuthMiddleware`, so the health endpoint is unauthenticated — correct for Docker health checks.

### `src/__main__.py` — Conditional Transport

Reads settings and branches:
- `"stdio"` → `app.run()` (current behavior, backward compatible)
- `"streamable-http"` → `app.run(transport="streamable-http", host=..., port=...)`

### `Dockerfile`

- Base: `python:3.13-slim`
- System deps: `curl` + Chromium shared libs
- Non-root `mcpuser`
- `HEALTHCHECK` via `curl -f http://localhost:8000/health`

### `docker-compose.yml`

Two services:
- **mcp**: Build from Dockerfile, bind mount `./data:/app/data`, env vars from `.env`
- **cloudflared**: Stock `cloudflare/cloudflared` image, depends on mcp health check

No ports exposed to the host — all traffic flows through the Cloudflare Tunnel.

## Verification

1. **Backward compatibility** — `MCP_TRANSPORT=stdio python -m src` works as before
2. **Local HTTP mode** — `MCP_TRANSPORT=streamable-http MCP_AUTH_TOKEN=<token> python -m src` starts on port 8000
3. **Docker** — `docker compose up --build`
4. **Unit tests** — `pytest tests/test_auth.py`

## Client Configuration

**Claude Desktop** (remote MCP):
```json
{
  "mcpServers": {
    "restaurant": {
      "url": "https://your-domain.example.com/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_MCP_AUTH_TOKEN"
      }
    }
  }
}
```

**Claude Code**:
```
claude mcp add restaurant --transport streamable-http \
  --url https://your-domain.example.com/mcp \
  --header "Authorization: Bearer YOUR_TOKEN"
```
