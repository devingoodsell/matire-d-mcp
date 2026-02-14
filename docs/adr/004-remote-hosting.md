# ADR-004: Remote Hosting via Docker and Streamable HTTP

**Date:** 2026-02-14
**Status:** Accepted

## Context

The MCP server previously ran only via stdio transport, requiring Claude Desktop to spawn it as a local subprocess. This limited access to a single machine. Users wanted to run the server on a home server or NAS and connect from any device — Claude Desktop, Claude.ai, Claude Code, or mobile.

## Decisions

### 1. Streamable HTTP Transport

**Decision:** Support `streamable-http` as an alternative transport alongside the existing `stdio` default, controlled by `MCP_TRANSPORT` env var.

**Rationale:**
- Streamable HTTP is the modern MCP standard, supported by Claude Desktop, Claude.ai, and Claude Code
- FastMCP 2.0 has built-in support via `run(transport="streamable-http")`
- The `MCP_TRANSPORT` setting defaults to `"stdio"` for full backward compatibility — existing local setups are unaffected

### 2. Bearer Token Auth via FastMCP's TokenVerifier

**Decision:** Subclass `TokenVerifier` from `fastmcp.server.auth` with a pre-shared token compared using `hmac.compare_digest`. Auth is only enabled when `MCP_AUTH_TOKEN` is set.

**Rationale:**
- FastMCP's `TokenVerifier` base class integrates natively — setting `mcp.auth` automatically wires `BearerAuthBackend` + `RequireAuthMiddleware` onto the MCP endpoint with no custom middleware
- `hmac.compare_digest` prevents timing-based side-channel attacks on the token
- 32-character minimum length enforced at construction time to prevent weak tokens
- Conditional activation (only when `MCP_AUTH_TOKEN` is set) means local stdio usage needs no token

### 3. Unauthenticated Health Endpoint via custom_route

**Decision:** Register `/health` using `@mcp.custom_route()` rather than custom ASGI middleware.

**Rationale:**
- Custom routes registered via `custom_route()` are added to `_additional_http_routes` and are NOT wrapped by `RequireAuthMiddleware` — the health endpoint is inherently unauthenticated
- This is correct for Docker health checks and load balancer probes, which cannot provide bearer tokens
- No need for path-based middleware exclusion logic

### 4. Cloudflare Tunnel for TLS and Networking

**Decision:** Use `cloudflared` as a sidecar Docker container rather than self-managed TLS (e.g., Caddy, nginx + Let's Encrypt).

**Rationale:**
- Works behind CGNAT (common with residential ISPs) — no port forwarding needed
- Outbound-only connections from the home network (no inbound ports exposed)
- Free TLS termination at Cloudflare's edge with built-in DDoS protection
- Single `TUNNEL_TOKEN` env var — simpler than managing certificates
- Requires a Cloudflare account with a managed domain, but the free tier suffices

### 5. Non-root Docker User

**Decision:** Create a dedicated `mcpuser` in the Dockerfile and run the server as that user.

**Rationale:**
- Security best practice for internet-facing containers — limits blast radius if the process is compromised
- Playwright browsers and application data are owned by `mcpuser`
- The `data/` directory is bind-mounted, so file ownership maps correctly

### 6. Auth Token Generation in Setup Flow

**Decision:** Generate `MCP_AUTH_TOKEN` alongside `RESTAURANT_MCP_KEY` in `python -m src.setup`, using `secrets.token_urlsafe(48)`.

**Rationale:**
- 48 bytes of `token_urlsafe` produces a 64-character token (well above the 32-char minimum)
- Displaying both keys together in the setup output makes it easy to copy into `.env`
- The setup flow already generates the master key — adding the auth token is a natural extension

## Consequences

- 1193 tests pass with 100% branch coverage (up from 1191 in ADR-003)
- Backward compatible — `MCP_TRANSPORT=stdio` (the default) preserves existing local behavior
- New files: `src/auth.py`, `Dockerfile`, `docker-compose.yml`, `.env.example`
- Modified: `src/config.py` (4 new settings), `src/server.py` (auth + health), `src/__main__.py` (transport branching), `src/setup.py` (token generation)
- Docker deployment is fully self-contained: `docker compose up --build -d`
- No ports exposed to the host network — all external traffic flows through the Cloudflare Tunnel
