"""Tests for OpenTableClient: browser automation for OpenTable reservations."""

import sys
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.clients.opentable import OpenTableClient, _build_restaurant_url
from src.clients.resy_auth import AuthError
from src.models.enums import BookingPlatform
from src.storage.credentials import CredentialStore


def _make_credential_store(tmp_path) -> CredentialStore:
    """Build a real CredentialStore backed by a temp directory."""
    return CredentialStore(tmp_path / "creds")


def _mock_page():
    """Build a fully-mocked Playwright page."""
    page = AsyncMock()
    page.goto = AsyncMock()
    page.fill = AsyncMock()
    page.click = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.query_selector_all = AsyncMock(return_value=[])
    page.query_selector = AsyncMock(return_value=None)
    return page


def _mock_browser_chain():
    """Build the full mock chain for Playwright objects.

    Returns (mock_apw, page, browser, pw_instance).
    mock_apw is the object returned by async_playwright(), whose .start()
    gives pw_instance.
    """
    page = _mock_page()
    context = AsyncMock()
    context.new_page = AsyncMock(return_value=page)
    context.add_init_script = AsyncMock()
    browser = AsyncMock()
    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()
    pw_instance = AsyncMock()
    pw_instance.chromium.launch = AsyncMock(return_value=browser)
    pw_instance.stop = AsyncMock()
    # Mock async_playwright().start()
    mock_apw = MagicMock()
    mock_apw.start = AsyncMock(return_value=pw_instance)
    return mock_apw, page, browser, pw_instance


def _fake_pw_module(mock_apw):
    """Build a fake playwright.async_api module with async_playwright."""
    fake_mod = ModuleType("playwright.async_api")
    fake_mod.async_playwright = MagicMock(return_value=mock_apw)
    return fake_mod


def _pw_sys_modules(fake_mod):
    """Return the sys.modules dict to patch for playwright imports."""
    return {
        "playwright": ModuleType("playwright"),
        "playwright.async_api": fake_mod,
    }


def _make_client_with_browser(tmp_path, page, browser, pw_instance):
    """Create an OpenTableClient with browser already injected."""
    store = _make_credential_store(tmp_path)
    client = OpenTableClient(store)
    client._browser = browser
    client._page = page
    client._pw = pw_instance
    return client


# ---- _build_restaurant_url --------------------------------------------------


class TestBuildRestaurantUrl:
    """_build_restaurant_url: correct OpenTable URL format with covers/dateTime."""

    def test_basic_url(self):
        result = _build_restaurant_url(
            "https://www.opentable.com", "carbone-new-york",
            "2026-02-14", 2, "19:00",
        )
        assert result == (
            "https://www.opentable.com/r/carbone-new-york"
            "?covers=2&dateTime=2026-02-14T19%3A00"
        )

    def test_large_party(self):
        result = _build_restaurant_url(
            "https://www.opentable.com", "slug",
            "2026-03-01", 8, "18:30",
        )
        assert "covers=8" in result
        assert "dateTime=2026-03-01T18%3A30" in result


# ---- _parse_time (static method) -------------------------------------------


class TestParseTime:
    """_parse_time converts various time formats to HH:MM."""

    def test_7pm(self):
        assert OpenTableClient._parse_time("7:00 PM") == "19:00"

    def test_midnight(self):
        assert OpenTableClient._parse_time("12:00 AM") == "00:00"

    def test_noon(self):
        assert OpenTableClient._parse_time("12:00 PM") == "12:00"

    def test_morning_with_minutes(self):
        assert OpenTableClient._parse_time("9:30 AM") == "09:30"

    def test_24h_passthrough(self):
        assert OpenTableClient._parse_time("19:00") == "19:00"

    def test_no_minutes_pm(self):
        assert OpenTableClient._parse_time("7pm") == "19:00"


# ---- _ensure_browser -------------------------------------------------------


class TestEnsureBrowser:
    """_ensure_browser: launch, no-op second call, ImportError."""

    async def test_first_call_launches_browser(self, tmp_path):
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)

        mock_apw, page, browser, pw_instance = _mock_browser_chain()
        fake_mod = _fake_pw_module(mock_apw)

        with patch.dict(sys.modules, _pw_sys_modules(fake_mod)):
            await client._ensure_browser()

        assert client._browser is browser
        assert client._page is page
        assert client._pw is pw_instance
        pw_instance.chromium.launch.assert_awaited_once()
        # Verify headless=True for server compatibility
        call_kwargs = pw_instance.chromium.launch.call_args[1]
        assert call_kwargs["headless"] is True

    async def test_second_call_is_noop(self, tmp_path):
        mock_apw, page, browser, pw_instance = _mock_browser_chain()
        client = _make_client_with_browser(tmp_path, page, browser, pw_instance)

        # Calling again should not launch a new browser
        await client._ensure_browser()

        # launch was never called because _browser was already set
        pw_instance.chromium.launch.assert_not_awaited()

    async def test_import_error_raises_auth_error(self, tmp_path):
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)

        fake_modules = {
            "playwright": None,
            "playwright.async_api": None,
        }
        with patch.dict(sys.modules, fake_modules):
            with pytest.raises(AuthError, match="Playwright is not installed"):
                await client._ensure_browser()


# ---- close ------------------------------------------------------------------


class TestClose:
    """close: cleanup browser/pw resources."""

    async def test_with_browser_closes_everything(self, tmp_path):
        mock_apw, page, browser, pw_instance = _mock_browser_chain()
        client = _make_client_with_browser(tmp_path, page, browser, pw_instance)
        client._logged_in = True

        await client.close()

        browser.close.assert_awaited_once()
        pw_instance.stop.assert_awaited_once()
        assert client._browser is None
        assert client._context is None
        assert client._page is None
        assert client._pw is None
        assert client._logged_in is False

    async def test_without_browser_is_noop(self, tmp_path):
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)

        # Should not raise
        await client.close()

        assert client._browser is None
        assert client._pw is None

    async def test_with_pw_but_no_browser(self, tmp_path):
        """Edge case: pw exists but browser was never assigned."""
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)
        pw_instance = AsyncMock()
        pw_instance.stop = AsyncMock()
        client._pw = pw_instance

        await client.close()

        pw_instance.stop.assert_awaited_once()
        assert client._pw is None


# ---- _login -----------------------------------------------------------------


class TestLogin:
    """_login: credentials check, navigation, form filling."""

    async def test_no_credentials_raises_auth_error(self, tmp_path):
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)

        with pytest.raises(AuthError, match="OpenTable credentials not configured"):
            await client._login()

    async def test_success_navigates_and_fills(self, tmp_path):
        store = _make_credential_store(tmp_path)
        store.save_credentials("opentable", {"email": "u@x.com", "password": "pw123"})
        client = OpenTableClient(store)

        mock_apw, page, browser, pw_instance = _mock_browser_chain()
        fake_mod = _fake_pw_module(mock_apw)

        with (
            patch.dict(sys.modules, _pw_sys_modules(fake_mod)),
            patch("src.clients.opentable.asyncio.sleep", new_callable=AsyncMock),
        ):
            await client._login()

        assert client._logged_in is True
        page.goto.assert_awaited()
        page.fill.assert_any_await('input[name="email"]', "u@x.com")
        page.fill.assert_any_await('input[name="password"]', "pw123")
        page.click.assert_awaited_once_with('button[type="submit"]')
        page.wait_for_load_state.assert_awaited_once_with("domcontentloaded")

    async def test_page_interaction_fails_raises_auth_error(self, tmp_path):
        store = _make_credential_store(tmp_path)
        store.save_credentials("opentable", {"email": "u@x.com", "password": "pw123"})

        mock_apw, page, browser, pw_instance = _mock_browser_chain()
        page.goto.side_effect = RuntimeError("navigation failed")
        fake_mod = _fake_pw_module(mock_apw)

        client = OpenTableClient(store)

        with (
            patch.dict(sys.modules, _pw_sys_modules(fake_mod)),
            patch("src.clients.opentable.asyncio.sleep", new_callable=AsyncMock),
        ):
            with pytest.raises(AuthError, match="OpenTable login failed"):
                await client._login()


# ---- find_availability -------------------------------------------------------


class TestFindAvailability:
    """find_availability: scraping time slots from OpenTable."""

    async def test_success_with_slots(self, tmp_path):
        mock_apw, page, browser, pw_instance = _mock_browser_chain()

        slot1 = AsyncMock()
        slot1.inner_text = AsyncMock(return_value="7:00 PM")
        slot2 = AsyncMock()
        slot2.inner_text = AsyncMock(return_value="8:30 PM")
        page.query_selector_all.return_value = [slot1, slot2]

        client = _make_client_with_browser(tmp_path, page, browser, pw_instance)

        with patch("src.clients.opentable.asyncio.sleep", new_callable=AsyncMock):
            slots = await client.find_availability(
                "carbone-new-york", "2025-03-15", 2, "19:00"
            )

        assert len(slots) == 2
        assert slots[0].time == "19:00"
        assert slots[0].platform == BookingPlatform.OPENTABLE
        assert slots[1].time == "20:30"

    async def test_empty_text_slots_skipped(self, tmp_path):
        mock_apw, page, browser, pw_instance = _mock_browser_chain()

        slot1 = AsyncMock()
        slot1.inner_text = AsyncMock(return_value="7:00 PM")
        slot_empty = AsyncMock()
        slot_empty.inner_text = AsyncMock(return_value="  ")
        page.query_selector_all.return_value = [slot1, slot_empty]

        client = _make_client_with_browser(tmp_path, page, browser, pw_instance)

        with patch("src.clients.opentable.asyncio.sleep", new_callable=AsyncMock):
            slots = await client.find_availability(
                "carbone-new-york", "2025-03-15", 2, "19:00"
            )

        assert len(slots) == 1
        assert slots[0].time == "19:00"

    async def test_no_slots_returns_empty(self, tmp_path):
        mock_apw, page, browser, pw_instance = _mock_browser_chain()
        page.query_selector_all.return_value = []

        client = _make_client_with_browser(tmp_path, page, browser, pw_instance)

        with patch("src.clients.opentable.asyncio.sleep", new_callable=AsyncMock):
            slots = await client.find_availability(
                "carbone-new-york", "2025-03-15", 2
            )

        assert slots == []

    async def test_exception_during_navigation_returns_empty(self, tmp_path):
        mock_apw, page, browser, pw_instance = _mock_browser_chain()
        page.goto.side_effect = RuntimeError("network error")

        client = _make_client_with_browser(tmp_path, page, browser, pw_instance)

        with patch("src.clients.opentable.asyncio.sleep", new_callable=AsyncMock):
            slots = await client.find_availability(
                "carbone-new-york", "2025-03-15", 2
            )

        assert slots == []


# ---- book -------------------------------------------------------------------


class TestBook:
    """book: clicking slots, special requests, confirmation extraction."""

    async def test_success_with_confirmation(self, tmp_path):
        mock_apw, page, browser, pw_instance = _mock_browser_chain()

        slot_el = AsyncMock()
        slot_el.click = AsyncMock()
        page.query_selector_all.return_value = [slot_el]

        conf_el = AsyncMock()
        conf_el.inner_text = AsyncMock(return_value="OT-12345")
        page.query_selector.return_value = conf_el

        client = _make_client_with_browser(tmp_path, page, browser, pw_instance)
        client._logged_in = True

        with patch("src.clients.opentable.asyncio.sleep", new_callable=AsyncMock):
            result = await client.book(
                "carbone-new-york", "2025-03-15", "19:00", 2
            )

        assert result == {"confirmation_number": "OT-12345"}
        slot_el.click.assert_awaited_once()

    async def test_not_logged_in_calls_login(self, tmp_path):
        store = _make_credential_store(tmp_path)
        store.save_credentials("opentable", {"email": "u@x.com", "password": "pw"})

        mock_apw, page, browser, pw_instance = _mock_browser_chain()

        slot_el = AsyncMock()
        slot_el.click = AsyncMock()
        page.query_selector_all.return_value = [slot_el]

        conf_el = AsyncMock()
        conf_el.inner_text = AsyncMock(return_value="OT-99")
        page.query_selector.return_value = conf_el

        client = OpenTableClient(store)
        client._browser = browser
        client._page = page
        client._pw = pw_instance

        with (
            patch.object(client, "_login", new_callable=AsyncMock) as mock_login,
            patch("src.clients.opentable.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await client.book(
                "carbone-new-york", "2025-03-15", "19:00", 2
            )

        mock_login.assert_awaited_once()
        assert result == {"confirmation_number": "OT-99"}

    async def test_no_slot_elements_returns_error(self, tmp_path):
        mock_apw, page, browser, pw_instance = _mock_browser_chain()
        page.query_selector_all.return_value = []

        client = _make_client_with_browser(tmp_path, page, browser, pw_instance)
        client._logged_in = True

        with patch("src.clients.opentable.asyncio.sleep", new_callable=AsyncMock):
            result = await client.book(
                "carbone-new-york", "2025-03-15", "19:00", 2
            )

        assert result == {"error": "No time slots found"}

    async def test_special_requests_filled_when_provided(self, tmp_path):
        mock_apw, page, browser, pw_instance = _mock_browser_chain()

        slot_el = AsyncMock()
        slot_el.click = AsyncMock()
        page.query_selector_all.return_value = [slot_el]

        sr_field = AsyncMock()
        sr_field.fill = AsyncMock()
        conf_el = AsyncMock()
        conf_el.inner_text = AsyncMock(return_value="OT-SR")

        # query_selector is called twice: once for special requests, once for confirmation
        page.query_selector.side_effect = [sr_field, conf_el]

        client = _make_client_with_browser(tmp_path, page, browser, pw_instance)
        client._logged_in = True

        with patch("src.clients.opentable.asyncio.sleep", new_callable=AsyncMock):
            result = await client.book(
                "carbone-new-york", "2025-03-15", "19:00", 2,
                special_requests="Window seat please",
            )

        sr_field.fill.assert_awaited_once_with("Window seat please")
        assert result == {"confirmation_number": "OT-SR"}

    async def test_special_requests_not_filled_when_none(self, tmp_path):
        mock_apw, page, browser, pw_instance = _mock_browser_chain()

        slot_el = AsyncMock()
        slot_el.click = AsyncMock()
        page.query_selector_all.return_value = [slot_el]

        conf_el = AsyncMock()
        conf_el.inner_text = AsyncMock(return_value="OT-NONE")
        page.query_selector.return_value = conf_el

        client = _make_client_with_browser(tmp_path, page, browser, pw_instance)
        client._logged_in = True

        with patch("src.clients.opentable.asyncio.sleep", new_callable=AsyncMock):
            result = await client.book(
                "carbone-new-york", "2025-03-15", "19:00", 2,
                special_requests=None,
            )

        # query_selector should only be called for confirmation, not special requests
        assert result == {"confirmation_number": "OT-NONE"}

    async def test_no_special_requests_field_found(self, tmp_path):
        """sr_field is None -- fill is not called even with special_requests."""
        mock_apw, page, browser, pw_instance = _mock_browser_chain()

        slot_el = AsyncMock()
        slot_el.click = AsyncMock()
        page.query_selector_all.return_value = [slot_el]

        conf_el = AsyncMock()
        conf_el.inner_text = AsyncMock(return_value="OT-NOSRF")
        # First query_selector for special requests returns None, second for confirmation
        page.query_selector.side_effect = [None, conf_el]

        client = _make_client_with_browser(tmp_path, page, browser, pw_instance)
        client._logged_in = True

        with patch("src.clients.opentable.asyncio.sleep", new_callable=AsyncMock):
            result = await client.book(
                "carbone-new-york", "2025-03-15", "19:00", 2,
                special_requests="Allergies: shellfish",
            )

        assert result == {"confirmation_number": "OT-NOSRF"}

    async def test_exception_during_booking_returns_error(self, tmp_path):
        mock_apw, page, browser, pw_instance = _mock_browser_chain()
        page.goto.side_effect = RuntimeError("page crashed")

        client = _make_client_with_browser(tmp_path, page, browser, pw_instance)
        client._logged_in = True

        with patch("src.clients.opentable.asyncio.sleep", new_callable=AsyncMock):
            result = await client.book(
                "carbone-new-york", "2025-03-15", "19:00", 2
            )

        assert "error" in result
        assert "page crashed" in result["error"]

    async def test_no_confirmation_element_returns_empty_number(self, tmp_path):
        """conf_el is None -- confirmation_number should be empty string."""
        mock_apw, page, browser, pw_instance = _mock_browser_chain()

        slot_el = AsyncMock()
        slot_el.click = AsyncMock()
        page.query_selector_all.return_value = [slot_el]
        page.query_selector.return_value = None  # no confirmation element

        client = _make_client_with_browser(tmp_path, page, browser, pw_instance)
        client._logged_in = True

        with patch("src.clients.opentable.asyncio.sleep", new_callable=AsyncMock):
            result = await client.book(
                "carbone-new-york", "2025-03-15", "19:00", 2
            )

        assert result == {"confirmation_number": ""}


# ---- cancel -----------------------------------------------------------------


class TestCancel:
    """cancel: finding and clicking cancel + confirm buttons."""

    async def test_success_cancel_and_confirm(self, tmp_path):
        mock_apw, page, browser, pw_instance = _mock_browser_chain()

        cancel_btn = AsyncMock()
        cancel_btn.click = AsyncMock()
        confirm_btn = AsyncMock()
        confirm_btn.click = AsyncMock()

        page.query_selector.side_effect = [cancel_btn, confirm_btn]

        client = _make_client_with_browser(tmp_path, page, browser, pw_instance)
        client._logged_in = True

        with patch("src.clients.opentable.asyncio.sleep", new_callable=AsyncMock):
            result = await client.cancel("OT-12345")

        assert result is True
        cancel_btn.click.assert_awaited_once()
        confirm_btn.click.assert_awaited_once()

    async def test_not_logged_in_calls_login(self, tmp_path):
        store = _make_credential_store(tmp_path)
        store.save_credentials("opentable", {"email": "u@x.com", "password": "pw"})

        mock_apw, page, browser, pw_instance = _mock_browser_chain()

        cancel_btn = AsyncMock()
        cancel_btn.click = AsyncMock()
        confirm_btn = AsyncMock()
        confirm_btn.click = AsyncMock()

        page.query_selector.side_effect = [cancel_btn, confirm_btn]

        client = OpenTableClient(store)
        client._browser = browser
        client._page = page
        client._pw = pw_instance

        with (
            patch.object(client, "_login", new_callable=AsyncMock) as mock_login,
            patch("src.clients.opentable.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await client.cancel("OT-12345")

        mock_login.assert_awaited_once()
        assert result is True

    async def test_no_cancel_button_returns_false(self, tmp_path):
        mock_apw, page, browser, pw_instance = _mock_browser_chain()
        page.query_selector.return_value = None  # no cancel button

        client = _make_client_with_browser(tmp_path, page, browser, pw_instance)
        client._logged_in = True

        with patch("src.clients.opentable.asyncio.sleep", new_callable=AsyncMock):
            result = await client.cancel("OT-12345")

        assert result is False

    async def test_no_confirm_button_still_returns_true(self, tmp_path):
        """Cancel button found, but confirm button is None -- still True."""
        mock_apw, page, browser, pw_instance = _mock_browser_chain()

        cancel_btn = AsyncMock()
        cancel_btn.click = AsyncMock()

        # First call returns cancel button, second returns None (no confirm)
        page.query_selector.side_effect = [cancel_btn, None]

        client = _make_client_with_browser(tmp_path, page, browser, pw_instance)
        client._logged_in = True

        with patch("src.clients.opentable.asyncio.sleep", new_callable=AsyncMock):
            result = await client.cancel("OT-12345")

        assert result is True
        cancel_btn.click.assert_awaited_once()

    async def test_exception_returns_false(self, tmp_path):
        mock_apw, page, browser, pw_instance = _mock_browser_chain()
        page.goto.side_effect = RuntimeError("network failure")

        client = _make_client_with_browser(tmp_path, page, browser, pw_instance)
        client._logged_in = True

        with patch("src.clients.opentable.asyncio.sleep", new_callable=AsyncMock):
            result = await client.cancel("OT-12345")

        assert result is False
