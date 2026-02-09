# ADR-002: OpenTable Client Rewrite — Cloudflare Bypass & Mobile API Cancel

**Date:** 2026-02-08
**Status:** Accepted

## Context

The original OpenTable client used `httpx` for all HTTP calls (page fetches, GraphQL availability, booking, cancellation). OpenTable deploys Cloudflare and Akamai Bot Manager, which block Python HTTP libraries via TLS fingerprinting. This caused restaurant page fetches (for slug→rid resolution) and POST-based operations (booking, cancel) to fail consistently in production.

Additionally, the DAPI `cancel-reservation` endpoint returned 404 — the endpoint no longer exists. A working cancel mechanism needed to be discovered and implemented.

## Decisions

### 1. System Curl for Page Fetches (`_curl_fetch`)

**Decision:** Restaurant page fetches use the system `curl` binary via `subprocess.run()` instead of httpx.

**Rationale:**
- System curl uses the OS-native TLS stack (BoringSSL on macOS), which produces a natural TLS fingerprint that passes Cloudflare bot detection
- Python HTTP libraries (httpx, aiohttp, curl_cffi) all fail with `ERR_HTTP2_PROTOCOL_ERROR` or timeouts against OpenTable's `/r/` pages
- `asyncio.to_thread()` wraps the blocking subprocess call for async compatibility
- Errors are handled via returncode checking + `TimeoutExpired`/`FileNotFoundError` exceptions

### 2. Playwright Fallback for Availability

**Decision:** If the direct DAPI GraphQL call fails (Cloudflare blocks it), a headful Playwright browser loads the restaurant page and intercepts the `RestaurantsAvailability` GraphQL response.

**Rationale:**
- Headless Playwright is also blocked by Cloudflare; only `headless=False` bypasses detection
- The `page.on("response", callback)` pattern captures the GraphQL JSON transparently
- This fallback adds ~10s latency but provides reliable availability data

### 3. Playwright POST for Booking (`_playwright_post`)

**Decision:** When httpx booking calls fail (Cloudflare blocks POST to DAPI), the client falls back to making the POST from within a Playwright browser context using `page.evaluate(fetch(...))`.

**Rationale:**
- Akamai bot cookies (`_abck`, `bm_*`) are only valid within the browser session that generated them
- By loading the OpenTable homepage first, the browser acquires valid bot cookies
- `page.evaluate()` runs `fetch()` from the page's JS context where those cookies are automatically included
- This is more reliable than trying to extract and replay bot cookies in httpx

### 4. Mobile API for Cancel (`_curl_delete`)

**Decision:** Cancellation uses `DELETE https://mobile-api.opentable.com/api/v3/reservation/{rid}/{confirmation_number}` with a Bearer token, executed via system curl.

**Rationale:**
- The DAPI `cancel-reservation` endpoint returns 404 — it no longer exists
- The mobile API DELETE endpoint was discovered via reverse-engineering research and confirmed working
- The Bearer token is extracted from the `authCke` session cookie (`atk=<uuid>`)
- System curl is used instead of httpx because the mobile API also blocks Python HTTP libraries (httpx gets 403)
- The `cancel()` method accepts an optional `rid` parameter; when not provided, it falls back to any cached rid from prior `_resolve_restaurant_id()` calls

### 5. `timeOffsetMinutes` Response Format

**Decision:** `_parse_availability_response()` handles both legacy `timeString` ("7:00 PM") and current `timeOffsetMinutes` (integer offset from requested time) formats.

**Rationale:**
- OpenTable's GraphQL API transitioned from `timeString` to `timeOffsetMinutes`
- The offset is relative to the requested `preferred_time`, e.g. offset=-30 with preferred_time="18:00" → "17:30"
- Supporting both formats provides backward compatibility if the API changes again

### 6. Updated Booking Payload Fields

**Decision:** The DAPI booking payload uses `partySize` (not `covers`), `reservationDateTime` (not `dateTime`), and includes required fields: `reservationType`, `reservationAttribute`, `pointsType`, `country`, `phoneNumberCountryId`.

**Rationale:**
- Discovered iteratively via API error messages during integration testing
- The field names and required fields differ from what the GraphQL availability endpoint uses
- `reservationType: "Standard"`, `reservationAttribute: "default"`, `pointsType: "Standard"` are constants required by the API

### 7. Setup CLI `@file` Syntax

**Decision:** The `_prompt()` function in `src/setup.py` supports `@path/to/file` syntax — when a value starts with `@`, the file contents are read and used as the value.

**Rationale:**
- OpenTable cookie headers can exceed 5000 characters, which overflows most terminal input buffers
- Users save the cookie header to a temp file and enter `@/tmp/cookies.txt` during setup
- The file is read with `Path.read_text().strip()`

## Consequences

- 1150 tests pass with 100% branch coverage
- All 5 OpenTable integration tests pass end-to-end: resolve → search → availability → book → cancel
- The client has a 3-tier transport strategy: httpx (fast) → system curl (Cloudflare bypass) → Playwright (full browser)
- Cancel requires both the `rid` and a valid Bearer token from the `authCke` cookie
- Session cookies expire every few days; users must re-run setup to refresh them
