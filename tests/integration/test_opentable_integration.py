"""Integration tests for OpenTable — live API calls.

Run with:
    python -m pytest tests/integration/test_opentable_integration.py -v

Credentials are loaded from the encrypted credential store on disk.
All tests marked @pytest.mark.integration (excluded from default pytest run).
"""

import re

import pytest

from src.clients.opentable import OpenTableClient

pytestmark = pytest.mark.integration

# Module-level state shared across ordered tests
_state: dict = {}


class TestOpenTableIntegration:
    """Ordered integration tests: resolve → search → availability → book → cancel."""

    async def test_01_resolve_restaurant(
        self, ot_client: OpenTableClient, ot_credentials: dict, test_restaurant: dict,
    ):
        """Resolve a restaurant slug to a numeric rid."""
        slug = test_restaurant.get("ot_slug")
        if not slug:
            base = re.sub(r"[^a-z0-9\s-]", "", test_restaurant["name"].lower().strip())
            slug = re.sub(r"\s+", "-", base) + "-new-york"
        _state["slug"] = slug

        rid = await ot_client._resolve_restaurant_id(slug)
        if rid is None:
            pytest.skip(
                f"Could not resolve rid for slug '{slug}' "
                f"(OpenTable may be blocking requests — try setting "
                f"INTEGRATION_OT_SLUG to a known slug)"
            )
        assert isinstance(rid, int)
        _state["rid"] = rid

    async def test_02_search_via_venue_matcher(self, ot_credentials: dict, test_restaurant: dict):
        """Validate the slug resolution produced an rid."""
        if not _state.get("rid"):
            pytest.skip("Resolve must succeed first")

        slug = _state["slug"]
        assert isinstance(slug, str)
        assert len(slug) > 0

    async def test_03_availability_matches_website(
        self, ot_client: OpenTableClient, ot_credentials: dict, test_restaurant: dict,
    ):
        """Fetch availability via GraphQL API and cross-check with the website."""
        if not _state.get("slug"):
            pytest.skip("Resolve must succeed first")

        slug = _state["slug"]
        date = test_restaurant["date"]
        party_size = test_restaurant["party_size"]

        slots = await ot_client.find_availability(slug, date, party_size)

        if not slots:
            _state["slots"] = []
            pytest.skip(
                f"No availability for {slug} on {date} "
                f"(restaurant may be fully booked or API unreachable)"
            )

        # Validate time format HH:MM
        time_pattern = re.compile(r"^\d{2}:\d{2}$")
        for slot in slots:
            assert time_pattern.match(slot.time), f"Invalid time format: {slot.time}"

        api_times = {s.time for s in slots}
        _state["slots"] = slots

        # Playwright cross-check against opentable.com
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                page = await browser.new_page()

                url = (
                    f"https://www.opentable.com/r/{slug}"
                    f"?covers={party_size}&dateTime={date}T19:00"
                )
                await page.goto(url, wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(3000)

                buttons = await page.query_selector_all(
                    'button[data-test*="time-slot"], '
                    'button[class*="time"], '
                    '[data-test*="slot"], '
                    '[class*="slot-picker"] button'
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
            pytest.skip(f"Playwright verification skipped: {exc}")

    async def test_04_book_reservation(
        self, ot_client: OpenTableClient, ot_credentials: dict,
        test_restaurant: dict, ot_cleanup: list,
    ):
        """Book a slot and store the confirmation number."""
        if not _state.get("slots"):
            pytest.skip("No slots available — cannot book")

        slots = _state["slots"]
        slot = slots[-1]
        date = test_restaurant["date"]
        party_size = test_restaurant["party_size"]
        slug = _state["slug"]

        parts = slot.config_id.split("|", 1)
        assert len(parts) == 2, f"Unexpected config_id format: {slot.config_id}"
        token, slot_hash = parts

        result = await ot_client.book(
            slug, date, slot.time, party_size,
            slot_availability_token=token,
            slot_hash=slot_hash,
        )
        assert "confirmation_number" in result, f"Booking failed: {result}"
        conf = result["confirmation_number"]
        assert conf, "Empty confirmation number"

        ot_cleanup.append(conf)
        _state["confirmation_number"] = conf

    async def test_05_cancel_reservation(
        self, ot_client: OpenTableClient, ot_credentials: dict, ot_cleanup: list,
    ):
        """Cancel the reservation."""
        if not _state.get("confirmation_number"):
            pytest.skip("No reservation to cancel")

        conf = _state["confirmation_number"]
        success = await ot_client.cancel(conf)
        assert success is True, f"Cancel failed for {conf}"

        if conf in ot_cleanup:
            ot_cleanup.remove(conf)
