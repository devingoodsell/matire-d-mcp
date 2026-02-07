# EPIC-08: Resilience, Caching & Production Readiness

## Goal
Wrap all external API calls with retry logic, circuit breakers, and fallback layers. Implement cost-tracking dashboards and ensure the system degrades gracefully when any external service is down.

## Success Criteria
- Transient errors are retried with exponential backoff
- Circuit breakers prevent hammering failed services
- Three-tier caching (in-memory, SQLite, live API) is implemented
- API costs are tracked and visible
- System provides useful fallbacks when primary methods fail
- Calendar integration syncs confirmed reservations

---

## Story 8.1: Retry & Circuit Breaker Patterns

**As a** developer
**I want** automatic retry for transient errors and circuit breaking for sustained failures
**So that** the system handles flaky APIs gracefully

### Tasks

- [ ] **8.1.1** Create `src/clients/resilience.py` with retry decorator:
  ```python
  from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

  TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}

  def resilient_request(max_attempts: int = 3):
      """Decorator for API calls with exponential backoff retry."""
      return retry(
          stop=stop_after_attempt(max_attempts),
          wait=wait_exponential(multiplier=1, min=2, max=30),
          retry=retry_if_exception_type((httpx.TimeoutException, TransientAPIError)),
          before_sleep=log_retry_attempt,
      )
  ```

- [ ] **8.1.2** Create custom exception hierarchy:
  ```python
  class APIError(Exception):
      """Base API error."""
      def __init__(self, message: str, status_code: int | None = None):
          self.status_code = status_code
          super().__init__(message)

  class TransientAPIError(APIError):
      """Retryable error (429, 5xx)."""

  class PermanentAPIError(APIError):
      """Non-retryable error (400, 401, 403, 404)."""

  class AuthError(PermanentAPIError):
      """Authentication failed."""

  class SchemaChangeError(APIError):
      """API response structure changed unexpectedly."""

  class CAPTCHAError(APIError):
      """CAPTCHA or bot detection triggered."""
  ```

- [ ] **8.1.3** Implement circuit breaker for each external service:
  ```python
  from pybreaker import CircuitBreaker

  resy_breaker = CircuitBreaker(
      fail_max=5,             # Open after 5 consecutive failures
      reset_timeout=120,      # Try again after 2 minutes
      name="resy",
  )

  google_places_breaker = CircuitBreaker(
      fail_max=3,
      reset_timeout=60,
      name="google_places",
  )

  opentable_breaker = CircuitBreaker(
      fail_max=3,
      reset_timeout=180,      # 3 min — OpenTable is slower to recover
      name="opentable",
  )

  weather_breaker = CircuitBreaker(
      fail_max=5,
      reset_timeout=300,      # 5 min — weather is non-critical
      name="weather",
  )
  ```

- [ ] **8.1.4** Apply circuit breakers to all API client methods:
  - Wrap `ResyClient` methods with `resy_breaker`
  - Wrap `GooglePlacesClient` methods with `google_places_breaker`
  - Wrap `OpenTableClient` methods with `opentable_breaker`
  - Wrap `WeatherClient` methods with `weather_breaker`

- [ ] **8.1.5** Classify HTTP responses automatically:
  ```python
  def classify_response(response: httpx.Response) -> None:
      """Raise appropriate error based on status code."""
      if response.status_code in TRANSIENT_STATUS_CODES:
          raise TransientAPIError(f"Transient error: {response.status_code}", response.status_code)
      elif response.status_code == 401:
          raise AuthError("Authentication failed", 401)
      elif response.status_code >= 400:
          raise PermanentAPIError(f"API error: {response.status_code}", response.status_code)
  ```

---

## Story 8.2: Three-Tier Caching

**As a** developer
**I want** a layered caching strategy
**So that** the system is fast and cheap

### Tasks

- [ ] **8.2.1** Create `src/clients/cache.py` with in-memory LRU cache:
  ```python
  from functools import lru_cache
  from datetime import datetime, timedelta

  class InMemoryCache:
      """Hot cache for current session data."""

      def __init__(self, max_size: int = 100):
          self._cache: dict[str, tuple[Any, datetime]] = {}
          self._max_size = max_size

      def get(self, key: str, max_age_seconds: int = 300) -> Any | None:
          if key in self._cache:
              value, stored_at = self._cache[key]
              if datetime.now() - stored_at < timedelta(seconds=max_age_seconds):
                  return value
              del self._cache[key]
          return None

      def set(self, key: str, value: Any) -> None:
          if len(self._cache) >= self._max_size:
              # Evict oldest entry
              oldest_key = min(self._cache, key=lambda k: self._cache[k][1])
              del self._cache[oldest_key]
          self._cache[key] = (value, datetime.now())
  ```

- [ ] **8.2.2** Implement cache-aside pattern for restaurant searches:
  ```
  Cache Lookup Order:
  1. In-memory (hot) — TTL: 5 minutes
     → Fastest. Same search repeated in conversation.

  2. SQLite (warm) — TTL: 24 hours
     → Restaurant metadata. Name, address, rating, cuisine.

  3. Live API (cold) — source of truth
     → Only hit when cache is stale.
     → Result stored in both warm and hot cache.
  ```

- [ ] **8.2.3** Implement stale-fallback for availability data:
  - Availability data has 5-15 minute TTL (must be relatively fresh)
  - If API call fails, serve stale cached availability with disclaimer:
    ```
    "Note: These time slots are from 20 minutes ago and may have changed.
     I couldn't reach Resy to get fresh data."
    ```
  - Never serve stale data for booking operations (must be real-time)

- [ ] **8.2.4** Add cache metrics:
  - Track hit/miss ratio per cache tier
  - Log cache performance for debugging
  - Available via `get_api_costs` tool (Story 8.4)

---

## Story 8.3: Fallback Layer Strategy

**As a** developer
**I want** graceful degradation when primary methods fail
**So that** the user always has a path forward

### Tasks

- [ ] **8.3.1** Implement `ResilientBookingClient` wrapper:
  ```python
  class ResilientBookingClient:
      """Wraps Resy/OpenTable with fallback layers."""

      async def check_availability(self, restaurant: Restaurant, date: str, party_size: int) -> AvailabilityResult:
          errors = []

          # Layer 1: API call (Resy)
          if restaurant.resy_venue_id:
              try:
                  return await self.resy_client.find_availability(...)
              except Exception as e:
                  errors.append(f"Resy API: {e}")

          # Layer 2: Browser automation (OpenTable)
          if restaurant.opentable_id:
              try:
                  return await self.opentable_client.find_availability(...)
              except Exception as e:
                  errors.append(f"OpenTable: {e}")

          # Layer 3: Deep link
          return AvailabilityResult(
              slots=[],
              message=f"Couldn't check automatically. Direct links:\n" +
                      self._generate_deep_links(restaurant, date, party_size),
          )

      async def make_reservation(self, ...) -> BookingResult:
          # Similar layered approach
          # Layer 1: API → Layer 2: Playwright → Layer 3: Deep link with instructions
  ```

- [ ] **8.3.2** Generate helpful deep links for manual fallback:
  ```python
  def _generate_deep_links(self, restaurant, date, party_size):
      links = []
      if restaurant.resy_venue_id:
          links.append(f"Resy: https://resy.com/cities/ny/{restaurant.resy_venue_id}?date={date}&seats={party_size}")
      if restaurant.opentable_id:
          links.append(f"OpenTable: https://www.opentable.com/r/{restaurant.opentable_id}")
      if restaurant.website:
          links.append(f"Website: {restaurant.website}")
      return "\n".join(links)
  ```

- [ ] **8.3.3** Implement schema change detection:
  ```python
  def _validate_resy_response(self, response_json: dict) -> None:
      """Check that Resy's response matches expected schema."""
      required_keys = {"results", "venues"}
      if not required_keys.issubset(response_json.get("results", {}).keys()):
          raise SchemaChangeError(
              "Resy API response structure changed. "
              "Expected keys: results.venues"
          )
  ```
  - Log schema mismatches for debugging
  - Fall back to Playwright when schema changes detected

---

## Story 8.4: API Cost Tracking & Monitoring

**As a** user
**I want** to see how much my API usage costs
**So that** I can manage my budget

### Tasks

- [ ] **8.4.1** Create `api_costs` tool:
  ```python
  @mcp.tool()
  async def api_costs(days: int = 30) -> str:
      """
      Show API usage costs for the last N days.
      Breaks down costs by provider (Google Places, Resy, OpenTable, Weather).

      Args:
          days: Number of days to look back (default 30)

      Returns:
          Cost breakdown by provider with total.
      """
  ```
  - Query `api_calls` table grouped by provider
  - Sum `cost_cents` per provider
  - Show call counts and cache hit rates
  - Format as:
    ```
    API costs (last 30 days):
    Google Places: $3.20 (100 calls, 67% cache hit rate)
    OpenWeatherMap: $0.00 (free tier, 45 calls)
    Resy: $0.00 (unofficial API)
    OpenTable: $0.00 (browser automation)
    Total: $3.20
    ```

- [ ] **8.4.2** Ensure every API call logs to `api_calls` table:
  - Google Places: log cost based on endpoint and field mask
  - Other APIs: log with cost_cents=0 but track call counts
  - Log cache hits with cached=True

---

## Story 8.5: Google Calendar Integration

**As a** user
**I want** confirmed reservations automatically added to my Google Calendar
**So that** I don't forget my reservations

### Tasks

- [ ] **8.5.1** Create `src/clients/calendar.py` with `CalendarClient`:
  ```python
  class CalendarClient:
      """Google Calendar integration for reservation events."""

      async def add_reservation(self, reservation: Reservation) -> str | None:
          """
          Create a Google Calendar event for a confirmed reservation.
          Returns event URL or None if calendar is not configured.
          """
  ```

- [ ] **8.5.2** Implement two approaches (user chooses during setup):

  **Option A: Google Calendar API** (requires OAuth2 setup):
  ```python
  async def _add_via_api(self, reservation: Reservation) -> str:
      event = {
          "summary": f"Dinner at {reservation.restaurant_name}",
          "location": reservation.address,
          "start": {"dateTime": start_dt.isoformat(), "timeZone": "America/New_York"},
          "end": {"dateTime": end_dt.isoformat(), "timeZone": "America/New_York"},
          "description": (
              f"Party of {reservation.party_size}\n"
              f"Confirmation: {reservation.platform_confirmation_id}\n"
              f"Booked via: {reservation.platform.value}"
          ),
          "reminders": {"useDefault": False, "overrides": [
              {"method": "popup", "minutes": 120},  # 2 hour reminder
          ]},
      }
      result = await service.events().insert(calendarId="primary", body=event).execute()
      return result.get("htmlLink")
  ```

  **Option B: ICS file generation** (no auth needed — simpler):
  ```python
  def generate_ics(self, reservation: Reservation) -> str:
      """Generate an .ics file content for manual calendar import."""
      return f"""BEGIN:VCALENDAR
  BEGIN:VEVENT
  DTSTART:{start_dt.strftime('%Y%m%dT%H%M%S')}
  DTEND:{end_dt.strftime('%Y%m%dT%H%M%S')}
  SUMMARY:Dinner at {reservation.restaurant_name}
  LOCATION:{reservation.address}
  DESCRIPTION:Party of {reservation.party_size}\\nConfirmation: {reservation.platform_confirmation_id}
  END:VEVENT
  END:VCALENDAR"""
  ```

  **Option C: Google Calendar URL** (zero setup, just generates link):
  ```python
  def generate_gcal_link(self, reservation: Reservation) -> str:
      """Generate a Google Calendar add-event URL."""
      params = urlencode({
          "action": "TEMPLATE",
          "text": f"Dinner at {reservation.restaurant_name}",
          "dates": f"{start_fmt}/{end_fmt}",
          "location": reservation.address,
          "details": f"Party of {reservation.party_size}\nConfirmation: {reservation.platform_confirmation_id}",
      })
      return f"https://calendar.google.com/calendar/render?{params}"
  ```

- [ ] **8.5.3** For MVP, implement **Option C** (Google Calendar URL):
  - Zero configuration required
  - Returns a clickable link that pre-fills a calendar event
  - After booking confirmation, include: "Add to calendar: [link]"
  - Option A can be added later if user wants automatic sync

- [ ] **8.5.4** Integrate calendar link into booking confirmation:
  - After successful `make_reservation`, append calendar link
  - Example:
    ```
    Booked! Carbone, Saturday Feb 14 at 7:00 PM, party of 2
    Confirmation: RESY-ABC123

    Add to Google Calendar: https://calendar.google.com/calendar/render?...
    ```

---

## Story 8.6: Error Messages for Users

**As a** developer
**I want** all errors translated to helpful, actionable user messages
**So that** Claude can communicate problems clearly

### Tasks

- [ ] **8.6.1** Create `src/tools/error_messages.py` with user-friendly error mapping:
  ```python
  ERROR_MESSAGES = {
      AuthError: "Your {platform} credentials may have expired. Try: store_{platform}_credentials to re-authenticate.",
      CAPTCHAError: "The booking platform is asking for CAPTCHA verification. Here's a direct link to book manually: {deep_link}",
      TransientAPIError: "The service is temporarily unavailable. I'll try again in a moment.",
      SchemaChangeError: "The booking platform may have updated their system. Falling back to browser automation...",
      CircuitBreakerError: "{platform} appears to be down. I'll check again in a few minutes. Meanwhile, here's a direct link: {deep_link}",
  }
  ```

- [ ] **8.6.2** Wrap all tool implementations with error handler:
  ```python
  async def safe_tool_wrapper(func, *args, **kwargs) -> str:
      try:
          return await func(*args, **kwargs)
      except APIError as e:
          template = ERROR_MESSAGES.get(type(e), "Something went wrong: {error}")
          return template.format(error=str(e), **context)
  ```

---

## Dependencies
- EPIC-01 (server)
- EPIC-02 (data layer — api_calls table)
- EPIC-05 (Resy client to wrap)
- EPIC-06 (OpenTable client to wrap)

## Blocked By
- EPIC-05, EPIC-06 (clients must exist to add resilience layer)

## Blocks
- Nothing — this is the final layer

## Cost Considerations
- This EPIC has **zero additional API costs** — it's infrastructure
- It **saves money** by improving cache hit rates and reducing redundant calls
- Calendar URL generation is free (no API needed)

## Technical Notes
- `tenacity` library handles retry with exponential backoff cleanly
- `pybreaker` provides circuit breaker pattern out of the box
- Circuit breaker states: CLOSED (normal) → OPEN (failing, don't call) → HALF-OPEN (try one)
- Error hierarchy allows specific handling: catch `AuthError` separately from `TransientAPIError`
- Schema change detection is a simple structural check — not a full schema validator
- Calendar: Start with Option C (URL generation) — it's zero-config and sufficient for MVP
- The `api_calls` table serves double duty: cost tracking + debugging failed requests
