# EPIC-06: OpenTable Booking Platform

## Goal
Integrate with OpenTable via Playwright browser automation for availability checking and reservation booking. OpenTable covers ~32% of NYC restaurants (vs Resy's ~13%), so this roughly doubles coverage.

## Success Criteria
- User can store OpenTable credentials securely
- Availability can be checked for OpenTable restaurants
- Reservations can be made and cancelled via browser automation
- Google Place IDs are matched to OpenTable restaurant slugs
- Realistic delays and browser behavior avoid bot detection

---

## Story 6.1: OpenTable Credential Storage

**As a** user
**I want** my OpenTable login stored securely
**So that** the system can book on my behalf

### Tasks

- [ ] **6.1.1** Create `store_opentable_credentials` MCP tool:
  ```python
  @mcp.tool()
  async def store_opentable_credentials(
      email: str,
      password: str,
  ) -> str:
      """
      Save your OpenTable account credentials for automated booking.
      Credentials are encrypted and stored locally.

      After saving, the system will verify the credentials work
      by attempting a test login.

      Args:
          email: Your OpenTable account email
          password: Your OpenTable account password

      Returns:
          Confirmation that credentials were saved and verified.
      """
  ```
  - Reuse `CredentialStore` from EPIC-05 with platform="opentable"
  - Attempt a Playwright login to verify credentials
  - Report success/failure

---

## Story 6.2: OpenTable Playwright Client

**As a** developer
**I want** a Playwright-based OpenTable client
**So that** we can automate availability checks and bookings through the browser

### Tasks

- [ ] **6.2.1** Create `src/clients/opentable.py` with `OpenTableClient`:
  ```python
  class OpenTableClient:
      """
      Playwright-based OpenTable automation.
      All interactions go through the real OpenTable website.
      """
      BASE_URL = "https://www.opentable.com"

      def __init__(self, credential_store: CredentialStore):
          self.credential_store = credential_store
          self._browser = None
          self._context = None
          self._page = None
          self._logged_in = False
  ```

- [ ] **6.2.2** Implement browser lifecycle management:
  ```python
  async def _ensure_browser(self):
      """Launch browser if not already running."""
      if not self._browser:
          pw = await async_playwright().start()
          self._browser = await pw.chromium.launch(headless=True)
          self._context = await self._browser.new_context(
              user_agent="<realistic UA>",
              viewport={"width": 1280, "height": 720},
              locale="en-US",
          )
          self._page = await self._context.new_page()

  async def close(self):
      """Close browser and clean up."""
      if self._browser:
          await self._browser.close()
          self._browser = None
  ```

- [ ] **6.2.3** Implement login method:
  ```python
  async def _login(self):
      """Login to OpenTable via the website."""
      creds = self.credential_store.get_credentials("opentable")
      if not creds:
          raise AuthError("OpenTable credentials not configured")

      await self._ensure_browser()
      await self._page.goto(f"{self.BASE_URL}/sign-in")
      await self._random_delay(1, 3)

      # Fill email
      await self._page.fill('input[name="email"]', creds["email"])
      await self._random_delay(0.5, 1.5)

      # Fill password
      await self._page.fill('input[name="password"]', creds["password"])
      await self._random_delay(0.5, 1)

      # Click sign in
      await self._page.click('button[type="submit"]')
      await self._page.wait_for_load_state("networkidle")

      self._logged_in = True
  ```

- [ ] **6.2.4** Implement realistic delay helper:
  ```python
  async def _random_delay(self, min_seconds: float = 1.0, max_seconds: float = 3.0):
      """Random delay to mimic human behavior. OpenTable blocks at <30s intervals."""
      delay = random.uniform(min_seconds, max_seconds)
      await asyncio.sleep(delay)
  ```

- [ ] **6.2.5** Implement `find_availability` method:
  ```python
  async def find_availability(
      self,
      restaurant_slug: str,     # e.g., "carbone-new-york"
      date: str,                 # "2026-02-14"
      party_size: int,
      preferred_time: str = "19:00",
  ) -> list[TimeSlot]:
      """
      Check availability by navigating to the restaurant's OpenTable page.
      """
      url = f"{self.BASE_URL}/r/{restaurant_slug}?date={date}&party_size={party_size}&time={preferred_time}"
      await self._ensure_browser()
      await self._page.goto(url)
      await self._random_delay(2, 4)

      # Wait for availability slots to load
      await self._page.wait_for_selector('[data-test="time-slot"]', timeout=10000)

      # Extract time slots
      slots = await self._page.query_selector_all('[data-test="time-slot"]')
      results = []
      for slot in slots:
          time_text = await slot.inner_text()
          results.append(TimeSlot(
              time=self._parse_time(time_text),
              platform=BookingPlatform.OPENTABLE,
              type=None,
          ))
      return results
  ```
  - **Note**: Selectors will need to be validated against actual OpenTable DOM
  - Use `data-test` attributes where available (most stable)
  - Fall back to aria labels or structural selectors

- [ ] **6.2.6** Implement `book` method:
  ```python
  async def book(
      self,
      restaurant_slug: str,
      date: str,
      time: str,
      party_size: int,
      special_requests: str | None = None,
  ) -> dict:
      """
      Book a reservation via OpenTable website automation.
      Must be logged in first.
      """
      if not self._logged_in:
          await self._login()

      # Navigate to booking page with parameters
      # Click the desired time slot
      # Fill in special requests if provided
      # Confirm the booking
      # Extract confirmation details
  ```
  - Navigate to restaurant page with date/party/time params
  - Click the time slot button
  - Fill special requests field if provided
  - Click "Complete reservation" button
  - Wait for confirmation page
  - Extract confirmation number and details
  - Add delays between every interaction (2-4 seconds)

- [ ] **6.2.7** Implement `cancel` method:
  ```python
  async def cancel(self, confirmation_number: str) -> bool:
      """Cancel an OpenTable reservation via the website."""
      if not self._logged_in:
          await self._login()

      # Navigate to "My Reservations"
      # Find the reservation by confirmation number
      # Click cancel
      # Confirm cancellation
  ```

---

## Story 6.3: OpenTable Venue Matching

**As a** developer
**I want** to match Google Place IDs to OpenTable restaurant slugs
**So that** discovery results link to OpenTable availability

### Tasks

- [ ] **6.3.1** Add OpenTable matching to `VenueMatcher`:
  ```python
  async def find_opentable_slug(self, restaurant: Restaurant) -> str | None:
      """
      Given a restaurant from Google Places, find its OpenTable slug.
      Returns slug (e.g., "carbone-new-york") or None.
      """
  ```

- [ ] **6.3.2** Implement matching strategy:
  1. **Cache check**: Look in `restaurant_cache` for existing `opentable_id`
  2. **URL construction**: Try common slug patterns:
     - `{name}-{city}` → "carbone-new-york"
     - `{name}-{neighborhood}-{city}` → "carbone-greenwich-village-new-york"
  3. **Google search**: Search `"{restaurant_name}" site:opentable.com {address}` to find the slug
  4. **Playwright verification**: Navigate to constructed URL, check if it resolves
  5. **Cache result**: Store matched slug in `restaurant_cache`

- [ ] **6.3.3** Implement lightweight slug verification:
  - HEAD request to `opentable.com/r/{slug}` — if 200, it exists
  - Don't launch full browser just for verification
  - Cache verified slugs permanently (restaurants don't change platforms often)

---

## Story 6.4: Unified Availability in Existing Tools

**As a** developer
**I want** the `check_availability` tool to check both Resy and OpenTable
**So that** users get comprehensive availability without specifying the platform

### Tasks

- [ ] **6.4.1** Update `check_availability` (from EPIC-05) to check both platforms:
  ```python
  # Inside check_availability tool:
  slots = []

  # Check Resy (if venue has resy_venue_id)
  if restaurant.resy_venue_id:
      resy_slots = await resy_client.find_availability(...)
      slots.extend(resy_slots)

  # Check OpenTable (if venue has opentable_id)
  if restaurant.opentable_id:
      ot_slots = await opentable_client.find_availability(...)
      slots.extend(ot_slots)

  # Sort by time, label by platform
  ```

- [ ] **6.4.2** Update `make_reservation` to route to correct platform:
  - If slot is from Resy → use ResyClient
  - If slot is from OpenTable → use OpenTableClient
  - Platform is embedded in the `TimeSlot.platform` field

- [ ] **6.4.3** Update `cancel_reservation` to route to correct platform:
  - Look up platform from `reservations` table
  - Route to appropriate client

---

## Story 6.5: Deep Link Fallback

**As a** developer
**I want** deep links generated when automation fails
**So that** the user can complete booking manually in their browser

### Tasks

- [ ] **6.5.1** Implement `generate_deep_link` for both platforms:
  ```python
  def generate_resy_deep_link(venue_id: str, date: str, party_size: int) -> str:
      return f"https://resy.com/cities/ny/{venue_id}?date={date}&seats={party_size}"

  def generate_opentable_deep_link(slug: str, date: str, time: str, party_size: int) -> str:
      return f"https://www.opentable.com/r/{slug}?date={date}&time={time}&party_size={party_size}"
  ```

- [ ] **6.5.2** When booking fails, return the deep link in the error message:
  ```
  "I couldn't complete the booking automatically.
   Here's a direct link to book: https://www.opentable.com/r/carbone-new-york?..."
  ```

---

## Dependencies
- EPIC-01 (server)
- EPIC-02 (data layer)
- EPIC-04 (restaurant discovery)
- EPIC-05 (credential store, booking tools to extend)

## Blocked By
- EPIC-05 (shares credential store, booking tool infrastructure)

## Blocks
- EPIC-08 (resilience wraps around OpenTable client)

## Cost Considerations
- OpenTable API: **Free** (browser automation, no API billing)
- Playwright: Free (open source)
- **Primary cost**: Time per operation. Browser automation is slower than API calls:
  - Availability check: ~5-8 seconds (page load + render)
  - Booking: ~10-15 seconds (multi-step form)
  - Login: ~5-8 seconds (one-time per session)

## Technical Notes
- **OpenTable is more aggressive about bot detection than Resy**:
  - Use realistic User-Agent
  - Add random delays between ALL interactions (2-4 seconds minimum)
  - Don't poll faster than 30-second intervals
  - Use realistic viewport size
  - Consider `stealth` plugin for Playwright if needed
- **Selectors will break**: OpenTable redesigns frequently
  - Prefer `data-test` attributes (most stable)
  - Fall back to `aria-label` attributes
  - Avoid CSS class selectors (change with every build)
  - Build selectors as constants at top of file for easy updates
- **Browser reuse**: Keep the browser context alive across multiple operations in a session
  to avoid repeated login. Close on server shutdown.
- **No parallel requests**: OpenTable will block if multiple pages hit the site simultaneously
  from the same session
- **Session cookies**: After login, cookies persist in the browser context — no need to
  re-login for each operation within a session
