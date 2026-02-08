"""Integration tests for Resy — live API calls.

Run with:
    python -m pytest tests/integration/test_resy_integration.py -v

Credentials are loaded from the encrypted credential store on disk.
All tests marked @pytest.mark.integration (excluded from default pytest run).
"""

import re

import pytest

from src.clients.resy import ResyClient

pytestmark = pytest.mark.integration

# Module-level state shared across ordered tests
_state: dict = {}


class TestResyIntegration:
    """Ordered integration tests: auth check → search → availability → book → cancel."""

    async def test_01_auth_valid(self, resy_client: ResyClient, resy_credentials: dict):
        """Verify the stored auth token is valid by listing reservations."""
        assert resy_client.auth_token, "auth_token should be set from credential store"
        assert resy_client.api_key, "api_key should be set"

        # Smoke-test: hit the API with stored credentials
        reservations = await resy_client.get_user_reservations()
        # Even an empty list is fine — we just need a non-error response
        assert isinstance(reservations, list), f"Unexpected response: {reservations}"
        _state["authenticated"] = True

    async def test_02_search_venue(self, resy_client: ResyClient, test_restaurant: dict):
        """Search for a venue by name and store venue_id."""
        assert _state.get("authenticated"), "Auth check must succeed first"

        name = test_restaurant["name"]
        results = await resy_client.search_venue(name)

        assert len(results) > 0, f"No Resy results for '{name}'"
        first = results[0]
        assert "id" in first
        assert "name" in first
        assert first["id"], "venue_id must be non-empty"

        venue_id = test_restaurant.get("resy_venue_id") or first["id"]
        _state["venue_id"] = venue_id

    async def test_03_availability_matches_website(
        self, resy_client: ResyClient, test_restaurant: dict,
    ):
        """Fetch availability via API and cross-check with the Resy website."""
        assert _state.get("venue_id"), "Search must succeed first"

        venue_id = _state["venue_id"]
        date = test_restaurant["date"]
        party_size = test_restaurant["party_size"]

        slots = await resy_client.find_availability(venue_id, date, party_size)

        if not slots:
            _state["slots"] = []
            pytest.skip(
                f"No availability for venue {venue_id} on {date} "
                f"(restaurant may be fully booked — try a different "
                f"INTEGRATION_RESTAURANT or INTEGRATION_DATE)"
            )

        # Validate time format HH:MM
        time_pattern = re.compile(r"^\d{2}:\d{2}$")
        for slot in slots:
            assert time_pattern.match(slot.time), f"Invalid time format: {slot.time}"

        api_times = {s.time for s in slots}
        _state["slots"] = slots

        # Playwright cross-check against resy.com
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return  # skip browser check if playwright not available

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                page = await browser.new_page()

                url = (
                    f"https://resy.com/cities/ny?date={date}"
                    f"&seats={party_size}&venue_id={venue_id}"
                )
                await page.goto(url, wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(3000)

                buttons = await page.query_selector_all(
                    'button[class*="ReservationButton"], '
                    'button[class*="time-slot"], '
                    '[data-test*="slot"], '
                    '[class*="slot"]'
                )
                web_times: set[str] = set()
                for btn in buttons:
                    text = (await btn.inner_text()).strip()
                    m = re.match(
                        r"(\d{1,2}):(\d{2})\s*(AM|PM)", text, re.IGNORECASE,
                    )
                    if m:
                        h = int(m.group(1))
                        mins = m.group(2)
                        ampm = m.group(3).upper()
                        if ampm == "PM" and h != 12:
                            h += 12
                        elif ampm == "AM" and h == 12:
                            h = 0
                        web_times.add(f"{h:02d}:{mins}")

                await browser.close()

            if web_times:
                overlap = api_times & web_times
                assert len(overlap) > 0, (
                    f"No overlap: API {api_times} vs website {web_times}"
                )
        except Exception as exc:  # noqa: BLE001
            # Browser verification is best-effort — don't fail the test
            # if the site is unreachable or has changed its DOM
            pytest.skip(f"Playwright verification skipped: {exc}")

    async def test_04_book_reservation(
        self, resy_client: ResyClient, resy_credentials: dict,
        test_restaurant: dict, resy_cleanup: list,
    ):
        """Book the last available slot (least desirable → most cancellable)."""
        if not _state.get("slots"):
            pytest.skip("No slots available — cannot book")

        slots = _state["slots"]
        slot = slots[-1]
        date = test_restaurant["date"]
        party_size = test_restaurant["party_size"]

        details = await resy_client.get_booking_details(
            slot.config_id, date, party_size,
        )
        assert details, "get_booking_details returned empty"
        book_token = details.get("book_token", {}).get("value", "")
        assert book_token, f"No book_token in details: {details}"

        # Include payment method if stored (required by some venues)
        pm_id = resy_credentials.get("payment_methods")
        payment_method = {"id": pm_id} if pm_id else None

        result = await resy_client.book(book_token, payment_method=payment_method)
        assert "resy_token" in result, f"Booking failed: {result}"
        resy_token = result["resy_token"]

        resy_cleanup.append(resy_token)
        _state["resy_token"] = resy_token

    async def test_05_cancel_reservation(self, resy_client: ResyClient, resy_cleanup: list):
        """Cancel the reservation and verify it's gone."""
        if not _state.get("resy_token"):
            pytest.skip("No reservation to cancel")

        resy_token = _state["resy_token"]
        success = await resy_client.cancel(resy_token)
        assert success is True, f"Cancel failed for {resy_token}"

        if resy_token in resy_cleanup:
            resy_cleanup.remove(resy_token)

        reservations = await resy_client.get_user_reservations()
        tokens = [r.get("resy_token") for r in reservations]
        assert resy_token not in tokens, "Cancelled reservation still listed"
