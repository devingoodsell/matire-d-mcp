# EPIC-05: Resy Booking Platform

## Goal
Integrate with Resy's unofficial API for availability checking and reservation booking. Include automated auth via API login with Playwright fallback, secure credential storage, and venue matching from Google Place IDs.

## Success Criteria
- User can store Resy credentials securely (encrypted at rest)
- Auth tokens are obtained via API login (`POST /3/auth/password`) with Playwright as fallback
- Availability is checked for any Resy restaurant by date/time/party size
- Reservations can be made and cancelled
- Google Place IDs are matched to Resy venue IDs
- Token refresh happens automatically when expired

---

## Story 5.1: Secure Credential Storage

**As a** user
**I want** my Resy login stored securely and encrypted
**So that** my credentials are protected at rest

### Tasks

- [ ] **5.1.1** Create `src/storage/credentials.py` with `CredentialStore`:
  ```python
  class CredentialStore:
      """Fernet-encrypted credential storage for booking platforms."""

      def __init__(self, credentials_dir: Path):
          # Key stored at credentials_dir / ".key"
          # Encrypted data at credentials_dir / "{platform}.enc"

      def save_credentials(self, platform: str, data: dict) -> None:
          """Encrypt and save credentials for a platform."""

      def get_credentials(self, platform: str) -> dict | None:
          """Decrypt and return credentials, or None if not stored."""

      def delete_credentials(self, platform: str) -> None:
          """Remove stored credentials for a platform."""

      def has_credentials(self, platform: str) -> bool:
          """Check if credentials exist for a platform."""
  ```
  - Use `cryptography.fernet.Fernet` for symmetric encryption
  - Generate key on first use, store at `data/.credentials/.key`
  - Store encrypted JSON at `data/.credentials/resy.enc`
  - Credential data includes: email, password, auth_token, api_key, payment_method_id, token_expires_at

- [ ] **5.1.2** Create `store_resy_credentials` MCP tool in `src/tools/booking.py`:
  ```python
  @mcp.tool()
  async def store_resy_credentials(
      email: str,
      password: str,
  ) -> str:
      """
      Save your Resy account credentials for automated booking.
      Credentials are encrypted and stored locally — never sent anywhere
      except to Resy's own servers for authentication.

      After saving, the system will attempt to log in and verify
      the credentials work. Your payment method on file will be
      detected automatically.

      Args:
          email: Your Resy account email
          password: Your Resy account password

      Returns:
          Confirmation that credentials were saved and verified,
          or an error if login failed.
      """
  ```
  - Save credentials
  - Attempt login via `ResyClient.authenticate()`
  - If successful, store the auth_token and api_key in credentials
  - Report back: "Credentials saved and verified. Payment method: Visa ending in 1234"

---

## Story 5.2: Resy API Client

**As a** developer
**I want** a typed Resy API client
**So that** all Resy operations go through a single, well-tested interface

### Tasks

- [ ] **5.2.1** Create `src/clients/resy.py` with `ResyClient`:
  ```python
  class ResyClient:
      BASE_URL = "https://api.resy.com"

      def __init__(self, api_key: str, auth_token: str):
          self.client = httpx.AsyncClient(
              headers={
                  "Authorization": f'ResyAPI api_key="{api_key}"',
                  "X-Resy-Auth-Token": auth_token,
                  "X-Resy-Universal-Auth": auth_token,
                  "User-Agent": "<realistic browser UA>",
                  "Accept": "application/json",
                  "Origin": "https://resy.com",
                  "Referer": "https://resy.com/",
              },
              timeout=30.0,
          )
  ```

- [ ] **5.2.2** Implement `authenticate` method (API-first):
  ```python
  async def authenticate(self, email: str, password: str) -> dict:
      """
      Authenticate via Resy's password endpoint.
      Returns: {"auth_token": str, "payment_methods": list, "api_key": str}
      """
      response = await self.client.post(
          f"{self.BASE_URL}/3/auth/password",
          json={"email": email, "password": password},
      )
      # Parse: token, payment_method_id from response
      # The api_key is application-level — use a known key or extract from resy.com
  ```
  - Primary auth: `POST /3/auth/password`
  - Extract `auth_token` (JWT) and `payment_methods` from response
  - Extract `struct_payment_method` for booking
  - The application-level `api_key` is a constant — extract from Resy's frontend or use known value

- [ ] **5.2.3** Implement `find_availability` method:
  ```python
  async def find_availability(
      self,
      venue_id: str,
      date: str,          # "2026-02-14"
      party_size: int,
  ) -> list[TimeSlot]:
      """GET /4/find — returns available time slots."""
      response = await self.client.get(
          f"{self.BASE_URL}/4/find",
          params={
              "venue_id": venue_id,
              "day": date,
              "party_size": party_size,
              "lat": 0,
              "long": 0,
          },
      )
      return self._parse_slots(response.json())
  ```
  - Parse the `results.venues[0].slots` array
  - Each slot has: `date.start` (time), `config.type` (e.g., "Dining Room"), `config.token` (config_id)
  - Return as `list[TimeSlot]`

- [ ] **5.2.4** Implement `get_booking_details` method:
  ```python
  async def get_booking_details(
      self,
      config_id: str,
      date: str,
      party_size: int,
  ) -> dict:
      """GET /3/details — returns book_token for a specific slot."""
      response = await self.client.get(
          f"{self.BASE_URL}/3/details",
          params={
              "config_id": config_id,
              "day": date,
              "party_size": party_size,
          },
      )
      return response.json()  # Contains book_token
  ```

- [ ] **5.2.5** Implement `book` method:
  ```python
  async def book(
      self,
      book_token: str,
      payment_method: dict | None = None,
  ) -> dict:
      """POST /3/book — complete the reservation."""
      payload = {
          "book_token": book_token,
          "source_id": "resy.com-venue-details",
      }
      if payment_method:
          payload["struct_payment_method"] = payment_method
      response = await self.client.post(
          f"{self.BASE_URL}/3/book",
          json=payload,
      )
      return response.json()  # Contains confirmation
  ```

- [ ] **5.2.6** Implement `cancel` method:
  ```python
  async def cancel(self, reservation_id: str) -> bool:
      """Cancel a Resy reservation."""
      # Use the appropriate cancellation endpoint
      # POST /3/cancel with resy_token
  ```

- [ ] **5.2.7** Implement `get_user_reservations` method:
  ```python
  async def get_user_reservations(self) -> list[dict]:
      """GET /3/user/reservations — list your upcoming reservations."""
  ```

- [ ] **5.2.8** Implement `search_venue` method (for venue matching):
  ```python
  async def search_venue(self, query: str, lat: float, lng: float) -> list[dict]:
      """Search for a Resy venue by name/location."""
      # GET /4/find with query parameters
      # Used to match Google Place → Resy venue_id
  ```

---

## Story 5.3: Resy Auth with Playwright Fallback

**As a** developer
**I want** Playwright-based auth as a fallback when API auth fails
**So that** the system remains functional even if API login is blocked

### Tasks

- [ ] **5.3.1** Create `src/clients/resy_auth.py` with `ResyAuthManager`:
  ```python
  class ResyAuthManager:
      """Manages Resy authentication with API-first, Playwright-fallback strategy."""

      async def authenticate(self, email: str, password: str) -> dict:
          """
          Attempt API login first. Fall back to Playwright browser login.
          Returns: {"auth_token": str, "api_key": str, "payment_methods": list}
          """
          try:
              return await self._auth_via_api(email, password)
          except (AuthError, httpx.HTTPError):
              return await self._auth_via_playwright(email, password)
  ```

- [ ] **5.3.2** Implement `_auth_via_playwright`:
  - Launch headless Chromium via Playwright
  - Navigate to `https://resy.com`
  - Intercept network requests to capture `x-resy-auth-token` and `api_key`
  - Login via email/password form
  - Wait for authenticated API request to capture token
  - Close browser
  - Return extracted credentials

- [ ] **5.3.3** Implement token refresh logic:
  ```python
  async def ensure_valid_token(self) -> str:
      """Check token validity, refresh if expired."""
      creds = self.credential_store.get_credentials("resy")
      if not creds or self._is_token_expired(creds):
          new_creds = await self.authenticate(creds["email"], creds["password"])
          self.credential_store.save_credentials("resy", {**creds, **new_creds})
          return new_creds["auth_token"]
      return creds["auth_token"]
  ```
  - Check if token is expired (try a lightweight API call like user profile)
  - If expired, re-authenticate and save new token
  - Called before every Resy API operation

---

## Story 5.4: Venue Matching (Google Place → Resy)

**As a** developer
**I want** to match Google Place IDs to Resy venue IDs
**So that** search results can seamlessly link to availability checking

### Tasks

- [ ] **5.4.1** Create `src/matching/venue_matcher.py`:
  ```python
  class VenueMatcher:
      """Matches restaurants across platforms using name + address."""

      async def find_resy_venue(self, restaurant: Restaurant) -> str | None:
          """
          Given a restaurant from Google Places, find its Resy venue ID.
          Returns venue_id or None if not on Resy.
          """
  ```

- [ ] **5.4.2** Implement matching strategy:
  1. **Cache check**: Look in `restaurant_cache` for existing `resy_venue_id`
  2. **Resy search**: Search Resy by restaurant name + location
  3. **Fuzzy match**: Compare name and address to confirm match
     - Normalize names (lowercase, strip "The", common abbreviations)
     - Compare address street numbers
  4. **Cache result**: Store matched `resy_venue_id` in `restaurant_cache`

- [ ] **5.4.3** Handle common matching edge cases:
  - Restaurant has different name on Resy vs Google (e.g., "Don Angie" vs "Don Angie NYC")
  - Same name, different locations (chain restaurants)
  - Restaurant not on Resy → return None gracefully

---

## Story 5.5: Check Availability MCP Tool

**As a** user
**I want** to check available reservation times at a restaurant
**So that** I can pick a time that works

### Tasks

- [ ] **5.5.1** Implement `check_availability` tool in `src/tools/booking.py`:
  ```python
  @mcp.tool()
  async def check_availability(
      restaurant_name: str,
      date: str,
      party_size: int = 2,
      preferred_time: str | None = None,
      flexibility_minutes: int = 60,
  ) -> str:
      """
      Check reservation availability at a specific restaurant.

      Searches both Resy and OpenTable (when available) and returns
      all open time slots.

      Args:
          restaurant_name: Name of the restaurant to check
          date: Date to check, e.g. "2026-02-14" or "Saturday" or "tomorrow"
          party_size: Number of diners
          preferred_time: Preferred time like "19:00" or "7pm". If provided,
                         results are sorted by proximity to this time.
          flexibility_minutes: How far from preferred_time to search (default ±60 min)

      Returns:
          Available time slots with platform info (Resy/OpenTable),
          or a message if no availability found.

      Example:
          check_availability("Carbone", "Saturday", party_size=2, preferred_time="19:00")
          → "Carbone - Saturday Feb 14:
             6:30 PM - Dining Room (Resy)
             9:15 PM - Dining Room (Resy)"
      """
  ```

- [ ] **5.5.2** Implement the availability flow:
  1. Look up restaurant in cache by name
  2. If not cached, search Google Places to get restaurant details
  3. Find Resy venue ID (via VenueMatcher)
  4. Parse date string (support "today", "tomorrow", "Saturday", "2026-02-14")
  5. Call `ResyClient.find_availability(venue_id, date, party_size)`
  6. If `preferred_time` is set, sort slots by proximity
  7. Format and return results

- [ ] **5.5.3** Implement date parsing helper in `src/tools/date_utils.py`:
  - "today" → today's date
  - "tomorrow" → tomorrow's date
  - "Saturday" / "this Saturday" → next Saturday
  - "next Saturday" → Saturday of next week
  - "Feb 14" / "2/14" → 2026-02-14
  - ISO format passthrough: "2026-02-14"

---

## Story 5.6: Make Reservation MCP Tool

**As a** user
**I want** to book a reservation through Claude
**So that** I don't have to open the Resy app

### Tasks

- [ ] **5.6.1** Implement `make_reservation` tool:
  ```python
  @mcp.tool()
  async def make_reservation(
      restaurant_name: str,
      date: str,
      time: str,
      party_size: int = 2,
      special_requests: str | None = None,
  ) -> str:
      """
      Book a reservation at a restaurant. This will create a real reservation
      on your Resy or OpenTable account.

      IMPORTANT: Only call this after the user has confirmed they want to book.
      Always show the user the exact details before booking:
      restaurant name, date, time, party size.

      Args:
          restaurant_name: Name of the restaurant
          date: Reservation date, e.g. "2026-02-14" or "Saturday"
          time: Reservation time, e.g. "19:00" or "7:00 PM"
          party_size: Number of diners
          special_requests: Any special requests like "birthday", "quiet table",
                           "high chair needed"

      Returns:
          Confirmation with reservation details and confirmation number,
          or an error message if booking failed.

      Example:
          make_reservation("Carbone", "Saturday", "19:00", party_size=2)
          → "Booked! Carbone, Saturday Feb 14 at 7:00 PM, party of 2
             Confirmation: RESY-ABC123
             Resy will send a confirmation email to you@email.com"
      """
  ```

- [ ] **5.6.2** Implement the booking flow:
  1. Ensure valid Resy auth token (auto-refresh if needed)
  2. Look up restaurant → get Resy venue ID
  3. Call `find_availability` to get slots for the date
  4. Find the slot matching the requested time
  5. Call `get_booking_details` with the slot's `config_id`
  6. Call `book` with the `book_token` and payment method
  7. Save reservation to local `reservations` table
  8. Log the visit to `visits` table
  9. Return confirmation details

- [ ] **5.6.3** Handle booking errors gracefully:
  - Slot no longer available → suggest alternatives
  - Auth expired → auto-refresh and retry once
  - CAPTCHA triggered → fall back to deep link
  - Payment method required → use stored payment method

---

## Story 5.7: Cancel Reservation Tool

**As a** user
**I want** to cancel a reservation through Claude
**So that** I don't have to open the app

### Tasks

- [ ] **5.7.1** Implement `cancel_reservation` tool:
  ```python
  @mcp.tool()
  async def cancel_reservation(
      restaurant_name: str | None = None,
      confirmation_id: str | None = None,
  ) -> str:
      """
      Cancel an existing reservation.

      Provide either the restaurant name (will find the most recent upcoming
      reservation) or a specific confirmation ID.

      Args:
          restaurant_name: Name of the restaurant to cancel
          confirmation_id: Specific confirmation ID to cancel

      Returns:
          Confirmation that the reservation was cancelled,
          or an error if not found/cancellation failed.
      """
  ```

- [ ] **5.7.2** Implement cancellation flow:
  1. Find reservation in local DB (by name or confirmation ID)
  2. Call `ResyClient.cancel(reservation_id)`
  3. Update local DB status to "cancelled"
  4. Return confirmation

---

## Story 5.8: View Upcoming Reservations

**As a** user
**I want** to see my upcoming reservations
**So that** I can manage my dining schedule

### Tasks

- [ ] **5.8.1** Implement `my_reservations` tool:
  ```python
  @mcp.tool()
  async def my_reservations() -> str:
      """
      Show all your upcoming reservations across Resy and OpenTable.

      Returns:
          Formatted list of upcoming reservations with dates, times,
          party sizes, and confirmation numbers.
      """
  ```
  - Query local `reservations` table for status="confirmed" and date >= today
  - Optionally sync with Resy API (`get_user_reservations`) to catch external bookings
  - Format and return

---

## Dependencies
- EPIC-01 (server)
- EPIC-02 (data layer)
- EPIC-04 (restaurant discovery for venue matching)

## Blocked By
- EPIC-02 (models and DB)
- EPIC-04 (need restaurant search to find venues)

## Blocks
- EPIC-08 (resilience wraps around Resy client)

## Cost Considerations
- Resy API: **Free** (unofficial, no billing)
- Playwright: Free (open source), but uses ~200MB disk for Chromium
- The main cost risk is **account deactivation** — mitigate by:
  - Keeping request rates low (personal use only)
  - Using realistic User-Agent headers
  - Adding random delays between requests (1-3 seconds)

## Technical Notes
- **Three-step booking flow**: find → details → book
  1. `GET /4/find` → available slots with `config_id`
  2. `GET /3/details` → `book_token` for a specific slot
  3. `POST /3/book` → reservation confirmation
- Resy API key is application-level (same for all users) — extract from resy.com frontend JS
- Auth token (JWT) is user-specific — obtained via login
- `struct_payment_method` is required for restaurants with booking fees — obtained from auth response
- AmEx cardholders may see additional inventory (AmEx owns Resy)
- Token expiration: tokens last ~24 hours typically. Implement `ensure_valid_token()` before every operation.
- Add 1-3 second random delay between API calls to avoid triggering rate limits
- All Resy API errors should be caught and converted to user-friendly messages
