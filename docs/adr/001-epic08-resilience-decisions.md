# ADR-001: EPIC-08 Resilience & Production Decisions

**Date:** 2026-02-07
**Status:** Accepted
**EPIC:** EPIC-08 — Resilience, Caching & Production Readiness

## Context

EPIC-08 is the final layer of the NYC Restaurant Reservation MCP server. The spec outlined retry logic, circuit breakers, caching, calendar integration, cost tracking, and error messages. Several implementation choices were made during development that differ from or refine the original spec.

## Decisions

### 1. Lightweight CircuitBreaker vs pybreaker

**Decision:** Implemented a custom `CircuitBreaker` class in `src/clients/resilience.py` instead of using the `pybreaker` library.

**Rationale:**
- Avoids adding a new dependency for a single-user personal tool
- The custom implementation is ~60 lines covering CLOSED/OPEN/HALF_OPEN states
- Uses `time.monotonic()` for timing (immune to system clock changes)
- Provides exactly the API surface we need: `call_async()` for async coroutines
- Keeps 100% branch coverage straightforward (no third-party internals to mock)

### 2. Calendar: Option C Only (URL Generation)

**Decision:** Implemented only Option C from the spec — `generate_gcal_link()` as a pure function in `src/clients/calendar.py`.

**Rationale:**
- Zero configuration required (no OAuth2 setup, no ICS file handling)
- Returns a clickable Google Calendar URL that pre-fills event details
- Assumes 2-hour dinner duration (reasonable default)
- Pure function with no side effects — trivially testable
- Option A (Google Calendar API with OAuth2) can be added later if automatic sync is desired

### 3. Skip ResilientBookingClient Wrapper

**Decision:** Did not create a separate `ResilientBookingClient` class as outlined in Story 8.3.

**Rationale:**
- `src/tools/booking.py` already implements the 3-layer fallback pattern (Resy API -> OpenTable Playwright -> deep links)
- Adding a wrapper would duplicate existing logic without benefit
- Instead, enhanced the existing fallback with `restaurant.website` in deep-link messages and calendar links after successful bookings

### 4. Skip Stale-Fallback for Availability

**Decision:** Did not implement stale-fallback for availability data (Story 8.2.3).

**Rationale:**
- The deep-link fallback already covers the "API is down" scenario
- Serving stale availability data is risky — slots may be taken, leading to failed bookings
- The spec itself noted "Never serve stale data for booking operations"

### 5. AuthError Re-export Pattern

**Decision:** Moved `AuthError` from `src/clients/resy_auth.py` to `src/clients/resilience.py` and re-exported via `__all__` in `resy_auth.py`.

**Rationale:**
- `AuthError` belongs in the exception hierarchy with other API errors
- Re-exporting maintains backward compatibility for any code importing from `resy_auth`
- `__all__ = ["AuthError", "ResyAuthManager"]` makes the re-export explicit

### 6. Separate Module-Level Caches

**Decision:** Created separate `InMemoryCache` instances for search (`_search_cache` in `search.py`) and recommendations (`_recommendation_cache` in `recommendations.py`).

**Rationale:**
- Different tools may have different access patterns and eviction needs
- Prevents recommendation queries from evicting search results and vice versa
- Each cache has `max_size=100` (200 entries total) — negligible memory for a personal tool
- Cache is passed to `GooglePlacesClient` as an optional parameter (dependency injection)

### 7. Cache-Aside Applied to search_nearby Only

**Decision:** Applied the cache-aside pattern only to `GooglePlacesClient.search_nearby()`, not to `get_place_details()`.

**Rationale:**
- `search_nearby` is the high-cost, high-frequency operation (Places API text search)
- `get_place_details` is already called less frequently and returns more dynamic data
- Cache key is `f"search:{query}:{lat:.4f}:{lng:.4f}:{radius_meters}:{max_results}"`
- Cache hits are logged as API calls with `cost=0.0, cached=True` for accurate cost tracking

### 8. InMemoryCache Uses OrderedDict + monotonic Clock

**Decision:** Implemented `InMemoryCache` using `collections.OrderedDict` with `time.monotonic()` timestamps.

**Rationale:**
- `OrderedDict` provides O(1) LRU eviction via `move_to_end()` and `popitem(last=False)`
- `time.monotonic()` is immune to system clock adjustments (NTP, DST, etc.)
- TTL is checked on `get()` — expired entries are lazily removed
- `CacheMetrics` tracks hits/misses with a `hit_rate` property for monitoring

### 9. Credential Security: Env Vars, Keyring, No Stored Password

**Decision:** Three changes to credential handling:

1. **Environment variable input** — `store_resy_credentials` and `store_opentable_credentials` parameters are now optional. When omitted, credentials are read from `RESY_EMAIL`/`RESY_PASSWORD`/`OPENTABLE_EMAIL`/`OPENTABLE_PASSWORD` env vars (or `.env` file). This prevents passwords from appearing in chat history.

2. **OS keyring for Fernet key** — `CredentialStore` now tries `keyring` (macOS Keychain / Linux Secret Service) before falling back to the `.key` file. If a `.key` file exists when keyring becomes available, the key is migrated. File-based fallback retains chmod 0o600/0o700 permissions.

3. **Resy password not persisted** — The Resy credential blob no longer stores `password`. Token refresh reads the password from env var `RESY_PASSWORD`. OpenTable still stores the password (required for every Playwright session) but it's protected by encryption + keyring.

**Rationale:**
- Chat messages sync to Anthropic's servers — passwords in chat are a security risk
- The `.key` file next to `.enc` files offered no real protection against filesystem access
- Storing Resy's password was unnecessary since the auth token is what's used for API calls
- `keyring` is an optional dependency (`pip install -e ".[security]"`) to avoid forcing native deps

## Consequences

- 945+ tests pass with 100% branch coverage
- `keyring` added as optional dependency under `[security]` extra
- All resilience primitives are in a single module (`resilience.py`) for easy discovery
- Cache and calendar are lightweight, stateless modules that can be extended later
