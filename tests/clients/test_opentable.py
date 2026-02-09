"""Tests for OpenTableClient: DAPI HTTP API for OpenTable reservations."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from src.clients.opentable import (
    OpenTableClient,
    _build_restaurant_url,
    _extract_bearer_token,
    _extract_rid,
    _parse_availability_response,
    _parse_time,
)
from src.models.enums import BookingPlatform
from src.storage.credentials import CredentialStore


def _make_credential_store(tmp_path) -> CredentialStore:
    """Build a real CredentialStore backed by a temp directory."""
    return CredentialStore(tmp_path / "creds")


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


# ---- _parse_time (module function) ------------------------------------------


class TestParseTime:
    """_parse_time converts various time formats to HH:MM."""

    def test_7pm(self):
        assert _parse_time("7:00 PM") == "19:00"

    def test_midnight(self):
        assert _parse_time("12:00 AM") == "00:00"

    def test_noon(self):
        assert _parse_time("12:00 PM") == "12:00"

    def test_morning_with_minutes(self):
        assert _parse_time("9:30 AM") == "09:30"

    def test_24h_passthrough(self):
        assert _parse_time("19:00") == "19:00"

    def test_no_minutes_pm(self):
        assert _parse_time("7pm") == "19:00"


# ---- _extract_rid ------------------------------------------------------------


class TestExtractRid:
    """_extract_rid: extract numeric restaurant ID from HTML."""

    def test_data_rid_attribute(self):
        html = '<div data-rid="8033" class="restaurant">'
        assert _extract_rid(html) == 8033

    def test_rid_in_json(self):
        html = '{"restaurant":{"rid":12345,"name":"Test"}}'
        assert _extract_rid(html) == 12345

    def test_restaurant_id_in_json(self):
        html = '{"restaurantId":99999,"name":"Test"}'
        assert _extract_rid(html) == 99999

    def test_no_rid_returns_none(self):
        html = "<html><body>No restaurant data here</body></html>"
        assert _extract_rid(html) is None

    def test_data_rid_priority_over_json(self):
        """data-rid attribute is checked first."""
        html = '<div data-rid="111">{"rid":222}</div>'
        assert _extract_rid(html) == 111


# ---- _parse_availability_response -------------------------------------------


class TestParseAvailabilityResponse:
    """Parse GraphQL availability response into TimeSlot objects."""

    def test_normal_response(self):
        data = {
            "data": {
                "availability": [
                    {
                        "restaurantId": 8033,
                        "availabilityDays": [
                            {
                                "date": "2026-02-14",
                                "slots": [
                                    {
                                        "dateTime": "2026-02-14T19:00",
                                        "timeString": "7:00 PM",
                                        "slotAvailabilityToken": "tok1",
                                        "slotHash": "hash1",
                                    },
                                    {
                                        "dateTime": "2026-02-14T20:30",
                                        "timeString": "8:30 PM",
                                        "slotAvailabilityToken": "tok2",
                                        "slotHash": "hash2",
                                    },
                                ],
                            }
                        ],
                    }
                ],
            }
        }
        slots = _parse_availability_response(data)
        assert len(slots) == 2
        assert slots[0].time == "19:00"
        assert slots[0].platform == BookingPlatform.OPENTABLE
        assert slots[0].config_id == "tok1|hash1"
        assert slots[1].time == "20:30"

    def test_empty_availability(self):
        data = {"data": {"availability": []}}
        assert _parse_availability_response(data) == []

    def test_missing_data_key(self):
        assert _parse_availability_response({}) == []

    def test_empty_slots(self):
        data = {
            "data": {
                "availability": [
                    {"restaurantId": 1, "availabilityDays": [{"date": "2026-02-14", "slots": []}]},
                ],
            }
        }
        assert _parse_availability_response(data) == []

    def test_empty_time_string_skipped(self):
        data = {
            "data": {
                "availability": [
                    {
                        "restaurantId": 1,
                        "availabilityDays": [
                            {
                                "date": "2026-02-14",
                                "slots": [
                                    {
                                        "dateTime": "",
                                        "timeString": "",
                                        "slotAvailabilityToken": "t",
                                        "slotHash": "h",
                                    },
                                    {
                                        "dateTime": "2026-02-14T19:00",
                                        "timeString": "7:00 PM",
                                        "slotAvailabilityToken": "t2",
                                        "slotHash": "h2",
                                    },
                                ],
                            }
                        ],
                    }
                ],
            }
        }
        slots = _parse_availability_response(data)
        assert len(slots) == 1
        assert slots[0].time == "19:00"

    def test_time_offset_minutes_format(self):
        """New format: slots use timeOffsetMinutes from preferred_time."""
        data = {
            "data": {
                "availability": [
                    {
                        "restaurantId": 100,
                        "availabilityDays": [
                            {
                                "slots": [
                                    {
                                        "timeOffsetMinutes": -30,
                                        "slotAvailabilityToken": "t1",
                                        "slotHash": "h1",
                                    },
                                    {
                                        "timeOffsetMinutes": 0,
                                        "slotAvailabilityToken": "t2",
                                        "slotHash": "h2",
                                    },
                                    {
                                        "timeOffsetMinutes": 60,
                                        "slotAvailabilityToken": "t3",
                                        "slotHash": "h3",
                                    },
                                ],
                            }
                        ],
                    }
                ],
            }
        }
        slots = _parse_availability_response(data, "18:00")
        assert len(slots) == 3
        assert slots[0].time == "17:30"
        assert slots[1].time == "18:00"
        assert slots[2].time == "19:00"
        assert slots[0].config_id == "t1|h1"

    def test_slot_without_time_info_skipped(self):
        """Slot with no timeString and no timeOffsetMinutes is skipped."""
        data = {
            "data": {
                "availability": [
                    {
                        "restaurantId": 1,
                        "availabilityDays": [
                            {
                                "slots": [
                                    {
                                        "slotAvailabilityToken": "t",
                                        "slotHash": "h",
                                    },
                                ],
                            }
                        ],
                    }
                ],
            }
        }
        assert _parse_availability_response(data) == []


# ---- OpenTableClient._get_http / close --------------------------------------


class TestHttpLifecycle:
    """_get_http: lazy creation, close: cleanup."""

    def test_get_http_creates_client(self, tmp_path):
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)

        http = client._get_http()
        assert isinstance(http, httpx.AsyncClient)

    def test_get_http_reuses_client(self, tmp_path):
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)

        http1 = client._get_http()
        http2 = client._get_http()
        assert http1 is http2

    def test_get_http_includes_cookies_when_stored(self, tmp_path):
        store = _make_credential_store(tmp_path)
        store.save_credentials("opentable", {
            "email": "u@t.com",
            "cookies": "otSessionId=abc123; otOther=xyz",
        })
        client = OpenTableClient(store)

        http = client._get_http()
        assert http.headers["cookie"] == "otSessionId=abc123; otOther=xyz"

    def test_get_http_no_cookie_header_without_cookies(self, tmp_path):
        store = _make_credential_store(tmp_path)
        store.save_credentials("opentable", {"email": "u@t.com"})
        client = OpenTableClient(store)

        http = client._get_http()
        assert "cookie" not in http.headers

    async def test_close_cleans_up(self, tmp_path):
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)
        _ = client._get_http()

        await client.close()
        assert client._http is None

    async def test_close_without_http_is_noop(self, tmp_path):
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)

        await client.close()
        assert client._http is None


# ---- _resolve_restaurant_id -------------------------------------------------


class TestCurlFetch:
    """_curl_fetch: system curl for page fetching."""

    def test_success_returns_html(self):
        result = MagicMock()
        result.returncode = 0
        result.stdout = '<div data-rid="8033">page</div>'
        with patch("src.clients.opentable.subprocess.run", return_value=result):
            html = OpenTableClient._curl_fetch("https://example.com")
        assert html == '<div data-rid="8033">page</div>'

    def test_nonzero_exit_returns_none(self):
        result = MagicMock()
        result.returncode = 28  # timeout
        result.stdout = ""
        with patch("src.clients.opentable.subprocess.run", return_value=result):
            html = OpenTableClient._curl_fetch("https://example.com")
        assert html is None

    def test_timeout_returns_none(self):
        import subprocess as _sp

        with patch(
            "src.clients.opentable.subprocess.run",
            side_effect=_sp.TimeoutExpired("curl", 15),
        ):
            html = OpenTableClient._curl_fetch("https://example.com")
        assert html is None

    def test_curl_not_found_returns_none(self):
        with patch("src.clients.opentable.subprocess.run", side_effect=FileNotFoundError):
            html = OpenTableClient._curl_fetch("https://example.com")
        assert html is None


class TestResolveRestaurantId:
    """_resolve_restaurant_id: slug → numeric rid via curl page HTML."""

    async def test_success_extracts_rid(self, tmp_path):
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)

        html = '<div data-rid="8033">Ci Siamo</div>'
        with patch.object(client, "_curl_fetch", return_value=html):
            rid = await client._resolve_restaurant_id("ci-siamo-new-york")
        assert rid == 8033

    async def test_caches_result(self, tmp_path):
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)

        with patch.object(client, "_curl_fetch", return_value='{"rid":8033}') as mock_fetch:
            rid1 = await client._resolve_restaurant_id("ci-siamo")
            rid2 = await client._resolve_restaurant_id("ci-siamo")
        assert rid1 == rid2 == 8033
        # Only one curl call — second used cache
        assert mock_fetch.call_count == 1

    async def test_curl_returns_none(self, tmp_path):
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)

        with patch.object(client, "_curl_fetch", return_value=None):
            rid = await client._resolve_restaurant_id("nonexistent")
        assert rid is None

    async def test_no_rid_in_page_returns_none(self, tmp_path):
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)

        with patch.object(client, "_curl_fetch", return_value="<html>No rid here</html>"):
            rid = await client._resolve_restaurant_id("no-rid")
        assert rid is None

    async def test_exception_returns_none(self, tmp_path):
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)

        with patch.object(client, "_curl_fetch", side_effect=OSError("fail")):
            rid = await client._resolve_restaurant_id("error-slug")
        assert rid is None


# ---- find_availability -------------------------------------------------------


class TestFindAvailability:
    """find_availability: DAPI GraphQL query for time slots."""

    async def test_success_with_slots(self, tmp_path):
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)

        # Mock _resolve_restaurant_id
        client._rid_cache["carbone-new-york"] = 8033

        gql_response = {
            "data": {
                "availability": [
                    {
                        "restaurantId": 8033,
                        "availabilityDays": [
                            {
                                "date": "2026-03-15",
                                "slots": [
                                    {
                                        "dateTime": "2026-03-15T19:00",
                                        "timeString": "7:00 PM",
                                        "slotAvailabilityToken": "t1",
                                        "slotHash": "h1",
                                    },
                                    {
                                        "dateTime": "2026-03-15T20:30",
                                        "timeString": "8:30 PM",
                                        "slotAvailabilityToken": "t2",
                                        "slotHash": "h2",
                                    },
                                ],
                            }
                        ],
                    }
                ],
            }
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = gql_response

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        client._http = mock_http

        slots = await client.find_availability(
            "carbone-new-york", "2026-03-15", 2, "19:00"
        )

        assert len(slots) == 2
        assert slots[0].time == "19:00"
        assert slots[0].platform == BookingPlatform.OPENTABLE
        assert slots[1].time == "20:30"

    async def test_rid_resolution_fails_returns_empty(self, tmp_path):
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)

        with patch.object(client, "_curl_fetch", return_value=None):
            slots = await client.find_availability(
                "nonexistent", "2026-03-15", 2
            )
        assert slots == []

    async def test_non_200_gql_falls_through_to_playwright(self, tmp_path):
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)
        client._rid_cache["slug"] = 100

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Server error"

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        client._http = mock_http

        pw_mock = AsyncMock(return_value=[])
        with patch.object(client, "_playwright_availability", pw_mock):
            slots = await client.find_availability("slug", "2026-03-15", 2)
        assert slots == []

    async def test_http_error_falls_through_to_playwright(self, tmp_path):
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)
        client._rid_cache["slug"] = 100

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(side_effect=httpx.ConnectError("network down"))
        client._http = mock_http

        pw_mock = AsyncMock(return_value=[])
        with patch.object(client, "_playwright_availability", pw_mock):
            slots = await client.find_availability("slug", "2026-03-15", 2)
        assert slots == []

    async def test_json_decode_error_falls_through(self, tmp_path):
        import json as _json

        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)
        client._rid_cache["slug"] = 100

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = _json.JSONDecodeError("bad", "", 0)

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        client._http = mock_http

        pw_mock = AsyncMock(return_value=[])
        with patch.object(client, "_playwright_availability", pw_mock):
            slots = await client.find_availability("slug", "2026-03-15", 2)
        assert slots == []

    async def test_default_preferred_time(self, tmp_path):
        """When no preferred_time, defaults to 19:00."""
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)
        client._rid_cache["slug"] = 100

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"availability": []}}

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        client._http = mock_http

        pw_mock = AsyncMock(return_value=[])
        with patch.object(client, "_playwright_availability", pw_mock):
            await client.find_availability("slug", "2026-03-15", 2)
        call_args = mock_http.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["variables"]["requestedTime"] == "19:00"

    async def test_playwright_fallback_no_playwright(self, tmp_path):
        """When Playwright is not importable, returns empty."""
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)

        with patch.dict("sys.modules", {"playwright.async_api": None}):
            slots = await client._playwright_availability(
                "slug", "2026-02-14", 2, "19:00",
            )
        assert slots == []

    async def test_playwright_fallback_with_exception(self, tmp_path):
        """When Playwright raises, returns empty."""
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)

        mock_pw = AsyncMock()
        mock_pw.__aenter__ = AsyncMock(
            side_effect=RuntimeError("browser fail"),
        )
        mock_pw.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "playwright.async_api.async_playwright",
            return_value=mock_pw,
        ):
            slots = await client._playwright_availability(
                "slug", "2026-02-14", 2, "19:00",
            )
        assert slots == []

    async def test_playwright_success_captures_slots(self, tmp_path):
        """Playwright intercepts GQL response and parses slots."""
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)

        gql_data = {
            "data": {
                "availability": [{
                    "restaurantId": 100,
                    "availabilityDays": [{
                        "date": "2026-02-14",
                        "slots": [{
                            "dateTime": "2026-02-14T19:00",
                            "timeString": "7:00 PM",
                            "slotAvailabilityToken": "t1",
                            "slotHash": "h1",
                        }],
                    }],
                }],
            },
        }

        # Build a mock response for the on_response callback
        mock_response = AsyncMock()
        mock_response.url = (
            "https://www.opentable.com/dapi/fe/gql"
            "?opname=RestaurantsAvailability"
        )
        mock_response.json = AsyncMock(return_value=gql_data)

        # Track the registered callback
        registered_callbacks: list = []

        mock_page = AsyncMock()

        def _capture_on(event, cb):
            registered_callbacks.append(cb)

        mock_page.on = _capture_on
        mock_page.goto = AsyncMock()
        mock_page.wait_for_timeout = AsyncMock()

        mock_browser = AsyncMock()
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        mock_browser.close = AsyncMock()

        mock_pw_ctx = AsyncMock()
        mock_pw_ctx.chromium.launch = AsyncMock(
            return_value=mock_browser,
        )

        mock_pw = AsyncMock()
        mock_pw.__aenter__ = AsyncMock(return_value=mock_pw_ctx)
        mock_pw.__aexit__ = AsyncMock(return_value=False)

        # Trigger callback during goto
        async def _goto_with_response(*_a, **_kw):
            for cb in registered_callbacks:
                await cb(mock_response)

        mock_page.goto = _goto_with_response

        with patch(
            "playwright.async_api.async_playwright",
            return_value=mock_pw,
        ):
            slots = await client._playwright_availability(
                "slug", "2026-02-14", 2, "19:00",
            )
        assert len(slots) == 1
        assert slots[0].time == "19:00"
        assert slots[0].config_id == "t1|h1"

    async def test_playwright_callback_exception_ignored(self, tmp_path):
        """When response.json() fails, callback swallows error."""
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)

        mock_response = AsyncMock()
        mock_response.url = (
            "https://www.opentable.com/dapi/fe/gql"
            "?opname=RestaurantsAvailability"
        )
        mock_response.json = AsyncMock(
            side_effect=RuntimeError("bad json"),
        )

        registered_callbacks: list = []
        mock_page = AsyncMock()

        def _capture_on(event, cb):
            registered_callbacks.append(cb)

        mock_page.on = _capture_on
        mock_page.goto = AsyncMock()
        mock_page.wait_for_timeout = AsyncMock()

        mock_browser = AsyncMock()
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        mock_browser.close = AsyncMock()

        mock_pw_ctx = AsyncMock()
        mock_pw_ctx.chromium.launch = AsyncMock(
            return_value=mock_browser,
        )

        mock_pw = AsyncMock()
        mock_pw.__aenter__ = AsyncMock(return_value=mock_pw_ctx)
        mock_pw.__aexit__ = AsyncMock(return_value=False)

        async def _goto_with_response(*_a, **_kw):
            for cb in registered_callbacks:
                await cb(mock_response)

        mock_page.goto = _goto_with_response

        with patch(
            "playwright.async_api.async_playwright",
            return_value=mock_pw,
        ):
            slots = await client._playwright_availability(
                "slug", "2026-02-14", 2, "19:00",
            )
        assert slots == []

    async def test_playwright_no_matching_responses(self, tmp_path):
        """When no response URL matches, captured stays empty."""
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)

        mock_response = AsyncMock()
        mock_response.url = "https://other-url.com/something"

        registered_callbacks: list = []
        mock_page = AsyncMock()

        def _capture_on(event, cb):
            registered_callbacks.append(cb)

        mock_page.on = _capture_on
        mock_page.goto = AsyncMock()
        mock_page.wait_for_timeout = AsyncMock()

        mock_browser = AsyncMock()
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        mock_browser.close = AsyncMock()

        mock_pw_ctx = AsyncMock()
        mock_pw_ctx.chromium.launch = AsyncMock(
            return_value=mock_browser,
        )

        mock_pw = AsyncMock()
        mock_pw.__aenter__ = AsyncMock(return_value=mock_pw_ctx)
        mock_pw.__aexit__ = AsyncMock(return_value=False)

        async def _goto_with_response(*_a, **_kw):
            for cb in registered_callbacks:
                await cb(mock_response)

        mock_page.goto = _goto_with_response

        with patch(
            "playwright.async_api.async_playwright",
            return_value=mock_pw,
        ):
            slots = await client._playwright_availability(
                "slug", "2026-02-14", 2, "19:00",
            )
        assert slots == []

    async def test_playwright_empty_slots_in_response(self, tmp_path):
        """When captured response has no slots, returns empty."""
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)

        gql_data = {"data": {"availability": []}}

        mock_response = AsyncMock()
        mock_response.url = (
            "https://www.opentable.com/dapi/fe/gql"
            "?opname=RestaurantsAvailability"
        )
        mock_response.json = AsyncMock(return_value=gql_data)

        registered_callbacks: list = []
        mock_page = AsyncMock()

        def _capture_on(event, cb):
            registered_callbacks.append(cb)

        mock_page.on = _capture_on
        mock_page.goto = AsyncMock()
        mock_page.wait_for_timeout = AsyncMock()

        mock_browser = AsyncMock()
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        mock_browser.close = AsyncMock()

        mock_pw_ctx = AsyncMock()
        mock_pw_ctx.chromium.launch = AsyncMock(
            return_value=mock_browser,
        )

        mock_pw = AsyncMock()
        mock_pw.__aenter__ = AsyncMock(return_value=mock_pw_ctx)
        mock_pw.__aexit__ = AsyncMock(return_value=False)

        async def _goto_with_response(*_a, **_kw):
            for cb in registered_callbacks:
                await cb(mock_response)

        mock_page.goto = _goto_with_response

        with patch(
            "playwright.async_api.async_playwright",
            return_value=mock_pw,
        ):
            slots = await client._playwright_availability(
                "slug", "2026-02-14", 2, "19:00",
            )
        assert slots == []


# ---- book -------------------------------------------------------------------


class TestBook:
    """book: DAPI make-reservation endpoint."""

    async def test_success_with_confirmation(self, tmp_path):
        store = _make_credential_store(tmp_path)
        store.save_credentials("opentable", {
            "csrf_token": "csrf-abc",
            "email": "user@test.com",
            "first_name": "Test",
            "last_name": "User",
            "phone": "212-555-1234",
        })
        client = OpenTableClient(store)
        client._rid_cache["carbone-new-york"] = 8033

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"confirmationNumber": "OT-12345"}

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        client._http = mock_http

        result = await client.book(
            "carbone-new-york", "2026-03-15", "19:00", 2,
            slot_availability_token="tok1",
            slot_hash="hash1",
        )

        assert result == {"confirmation_number": "OT-12345"}
        call_args = mock_http.post.call_args
        headers = call_args.kwargs.get("headers") or call_args[1].get("headers")
        assert headers["x-csrf-token"] == "csrf-abc"

    async def test_no_csrf_token_returns_error(self, tmp_path):
        store = _make_credential_store(tmp_path)
        store.save_credentials("opentable", {"email": "user@test.com"})
        client = OpenTableClient(store)

        result = await client.book(
            "slug", "2026-03-15", "19:00", 2,
            slot_availability_token="t", slot_hash="h",
        )
        assert "error" in result
        assert "CSRF token" in result["error"]

    async def test_no_credentials_returns_error(self, tmp_path):
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)

        result = await client.book(
            "slug", "2026-03-15", "19:00", 2,
            slot_availability_token="t", slot_hash="h",
        )
        assert "error" in result
        assert "CSRF token" in result["error"]

    async def test_rid_resolution_fails_returns_error(self, tmp_path):
        store = _make_credential_store(tmp_path)
        store.save_credentials("opentable", {"csrf_token": "tok", "email": "u@t.com"})
        client = OpenTableClient(store)

        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "Not found"

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)
        client._http = mock_http

        result = await client.book(
            "nonexistent", "2026-03-15", "19:00", 2,
            slot_availability_token="t", slot_hash="h",
        )
        assert "error" in result
        assert "Could not resolve" in result["error"]

    async def test_non_200_booking_response(self, tmp_path):
        store = _make_credential_store(tmp_path)
        store.save_credentials("opentable", {"csrf_token": "tok", "email": "u@t.com"})
        client = OpenTableClient(store)
        client._rid_cache["slug"] = 100

        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "Bad request"

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        client._http = mock_http

        result = await client.book(
            "slug", "2026-03-15", "19:00", 2,
            slot_availability_token="t", slot_hash="h",
        )
        assert "error" in result
        assert "status 400" in result["error"]

    async def test_http_error_falls_through_to_playwright(self, tmp_path):
        store = _make_credential_store(tmp_path)
        store.save_credentials("opentable", {"csrf_token": "tok", "email": "u@t.com"})
        client = OpenTableClient(store)
        client._rid_cache["slug"] = 100

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(side_effect=httpx.ConnectError("timeout"))
        client._http = mock_http

        pw_result = {"confirmation_number": "PW-123"}
        pw_mock = AsyncMock(return_value=pw_result)
        with patch.object(client, "_playwright_post", pw_mock):
            result = await client.book(
                "slug", "2026-03-15", "19:00", 2,
                slot_availability_token="t", slot_hash="h",
            )
        assert result == {"confirmation_number": "PW-123"}

    async def test_json_decode_error_falls_through(self, tmp_path):
        import json as _json

        store = _make_credential_store(tmp_path)
        store.save_credentials("opentable", {"csrf_token": "tok", "email": "u@t.com"})
        client = OpenTableClient(store)
        client._rid_cache["slug"] = 100

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = _json.JSONDecodeError("bad", "", 0)

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        client._http = mock_http

        pw_mock = AsyncMock(return_value={"error": "pw-fail"})
        with patch.object(client, "_playwright_post", pw_mock):
            result = await client.book(
                "slug", "2026-03-15", "19:00", 2,
                slot_availability_token="t", slot_hash="h",
            )
        assert "error" in result

    async def test_special_requests_included(self, tmp_path):
        store = _make_credential_store(tmp_path)
        store.save_credentials("opentable", {"csrf_token": "tok", "email": "u@t.com"})
        client = OpenTableClient(store)
        client._rid_cache["slug"] = 100

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"confirmationNumber": "OT-SR"}

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        client._http = mock_http

        result = await client.book(
            "slug", "2026-03-15", "19:00", 2,
            slot_availability_token="t", slot_hash="h",
            special_requests="Window seat please",
        )
        assert result == {"confirmation_number": "OT-SR"}
        call_args = mock_http.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["specialRequests"] == "Window seat please"

    async def test_special_requests_not_included_when_none(self, tmp_path):
        store = _make_credential_store(tmp_path)
        store.save_credentials("opentable", {"csrf_token": "tok", "email": "u@t.com"})
        client = OpenTableClient(store)
        client._rid_cache["slug"] = 100

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"confirmationNumber": "OT-NS"}

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        client._http = mock_http

        await client.book(
            "slug", "2026-03-15", "19:00", 2,
            slot_availability_token="t", slot_hash="h",
        )
        call_args = mock_http.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert "specialRequests" not in payload

    async def test_success_with_security_token(self, tmp_path):
        """When response includes securityToken, it is returned."""
        store = _make_credential_store(tmp_path)
        store.save_credentials("opentable", {
            "csrf_token": "csrf-abc",
            "email": "user@test.com",
        })
        client = OpenTableClient(store)
        client._rid_cache["slug"] = 100

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "confirmationNumber": "OT-SEC",
            "securityToken": "sec-xyz",
        }

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        client._http = mock_http

        result = await client.book(
            "slug", "2026-03-15", "19:00", 2,
            slot_availability_token="t", slot_hash="h",
        )
        assert result == {
            "confirmation_number": "OT-SEC",
            "security_token": "sec-xyz",
        }

    async def test_reservation_id_fallback(self, tmp_path):
        """When confirmationNumber absent, reservationId is used."""
        store = _make_credential_store(tmp_path)
        store.save_credentials("opentable", {"csrf_token": "tok", "email": "u@t.com"})
        client = OpenTableClient(store)
        client._rid_cache["slug"] = 100

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"reservationId": "res-id-123"}

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        client._http = mock_http

        result = await client.book(
            "slug", "2026-03-15", "19:00", 2,
            slot_availability_token="t", slot_hash="h",
        )
        assert result == {"confirmation_number": "res-id-123"}


# ---- cancel -----------------------------------------------------------------


class TestExtractBearerToken:
    """_extract_bearer_token: parse atk from authCke cookie."""

    def test_extracts_atk(self):
        cookies = (
            "otSessionId=abc; "
            "authCke=atk%3D1234-uuid%26rtk%3Drefresh%26tkt%3Dbearer; "
            "other=val"
        )
        assert _extract_bearer_token(cookies) == "1234-uuid"

    def test_no_auth_cookie_returns_none(self):
        assert _extract_bearer_token("otSessionId=abc; other=val") is None

    def test_no_atk_in_auth_cookie_returns_none(self):
        assert _extract_bearer_token("authCke=rtk%3Drefresh") is None

    def test_empty_string(self):
        assert _extract_bearer_token("") is None


class TestCurlDelete:
    """_curl_delete: system curl for mobile API DELETE."""

    def test_success_returns_body(self):
        result = MagicMock()
        result.returncode = 0
        result.stdout = '{"similarRestaurants":[]}'
        with patch("src.clients.opentable.subprocess.run", return_value=result):
            body = OpenTableClient._curl_delete("https://example.com", "tok")
        assert body == '{"similarRestaurants":[]}'

    def test_nonzero_exit_returns_none(self):
        result = MagicMock()
        result.returncode = 28
        result.stdout = ""
        with patch("src.clients.opentable.subprocess.run", return_value=result):
            body = OpenTableClient._curl_delete("https://example.com", "tok")
        assert body is None

    def test_timeout_returns_none(self):
        import subprocess as _sp

        with patch(
            "src.clients.opentable.subprocess.run",
            side_effect=_sp.TimeoutExpired("curl", 15),
        ):
            body = OpenTableClient._curl_delete("https://example.com", "tok")
        assert body is None

    def test_curl_not_found_returns_none(self):
        with patch(
            "src.clients.opentable.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            body = OpenTableClient._curl_delete("https://example.com", "tok")
        assert body is None


class TestCancel:
    """cancel: mobile API DELETE for cancellation."""

    _COOKIES = (
        "otSessionId=abc; "
        "authCke=atk%3Dbearer-tok%26rtk%3Drefresh%26tkt%3Dbearer"
    )

    async def test_success_with_rid(self, tmp_path):
        store = _make_credential_store(tmp_path)
        store.save_credentials("opentable", {
            "csrf_token": "tok", "email": "u@t.com",
            "cookies": self._COOKIES,
        })
        client = OpenTableClient(store)

        with patch.object(
            client, "_curl_delete", return_value='{"ok":true}',
        ) as mock_curl:
            result = await client.cancel("6874", rid=1397323)
        assert result is True
        url = mock_curl.call_args.args[0]
        assert "1397323" in url
        assert "6874" in url
        assert mock_curl.call_args.args[1] == "bearer-tok"

    async def test_success_with_cached_rid(self, tmp_path):
        """When rid not passed, uses cached value."""
        store = _make_credential_store(tmp_path)
        store.save_credentials("opentable", {
            "csrf_token": "tok", "email": "u@t.com",
            "cookies": self._COOKIES,
        })
        client = OpenTableClient(store)
        client._rid_cache["some-slug"] = 99999

        with patch.object(
            client, "_curl_delete", return_value='{"ok":true}',
        ) as mock_curl:
            result = await client.cancel("CONF-1")
        assert result is True
        assert "99999" in mock_curl.call_args.args[0]

    async def test_no_credentials_returns_false(self, tmp_path):
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)

        result = await client.cancel("OT-12345", rid=100)
        assert result is False

    async def test_no_bearer_token_returns_false(self, tmp_path):
        store = _make_credential_store(tmp_path)
        store.save_credentials("opentable", {
            "csrf_token": "tok", "email": "u@t.com",
            "cookies": "no-auth-cookie=val",
        })
        client = OpenTableClient(store)

        result = await client.cancel("OT-12345", rid=100)
        assert result is False

    async def test_no_rid_and_empty_cache_returns_false(self, tmp_path):
        store = _make_credential_store(tmp_path)
        store.save_credentials("opentable", {
            "csrf_token": "tok", "email": "u@t.com",
            "cookies": self._COOKIES,
        })
        client = OpenTableClient(store)

        result = await client.cancel("OT-12345")
        assert result is False

    async def test_curl_failure_returns_false(self, tmp_path):
        store = _make_credential_store(tmp_path)
        store.save_credentials("opentable", {
            "csrf_token": "tok", "email": "u@t.com",
            "cookies": self._COOKIES,
        })
        client = OpenTableClient(store)

        with patch.object(client, "_curl_delete", return_value=None):
            result = await client.cancel("OT-12345", rid=100)
        assert result is False


# ---- _playwright_post -------------------------------------------------------


class TestPlaywrightPost:
    """_playwright_post: DAPI POST via Playwright browser context."""

    async def test_no_playwright_returns_error(self, tmp_path):
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)

        with patch.dict("sys.modules", {"playwright.async_api": None}):
            result = await client._playwright_post(
                "/dapi/booking/make-reservation", {}, "csrf", "test",
            )
        assert "error" in result
        assert "Playwright" in result["error"]

    async def test_success_with_confirmation(self, tmp_path):
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.wait_for_timeout = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value={
            "status": 200,
            "body": '{"confirmationNumber":"OT-PW","securityToken":"sec-tok"}',
        })

        mock_browser = AsyncMock()
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        mock_browser.close = AsyncMock()

        mock_pw_ctx = AsyncMock()
        mock_pw_ctx.chromium.launch = AsyncMock(
            return_value=mock_browser,
        )

        mock_pw = AsyncMock()
        mock_pw.__aenter__ = AsyncMock(return_value=mock_pw_ctx)
        mock_pw.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "playwright.async_api.async_playwright",
            return_value=mock_pw,
        ):
            result = await client._playwright_post(
                "/dapi/booking/make-reservation",
                {"restaurantId": 100},
                "csrf-tok",
                "test-book",
            )
        assert result == {
            "confirmation_number": "OT-PW",
            "security_token": "sec-tok",
        }

    async def test_non_200_returns_error(self, tmp_path):
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.wait_for_timeout = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value={
            "status": 403,
            "body": "Forbidden",
        })

        mock_browser = AsyncMock()
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        mock_browser.close = AsyncMock()

        mock_pw_ctx = AsyncMock()
        mock_pw_ctx.chromium.launch = AsyncMock(
            return_value=mock_browser,
        )

        mock_pw = AsyncMock()
        mock_pw.__aenter__ = AsyncMock(return_value=mock_pw_ctx)
        mock_pw.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "playwright.async_api.async_playwright",
            return_value=mock_pw,
        ):
            result = await client._playwright_post(
                "/dapi/booking/cancel-reservation",
                {"confirmationNumber": "X"},
                "csrf",
                "cancel",
            )
        assert "error" in result
        assert "403" in result["error"]

    async def test_invalid_json_returns_error(self, tmp_path):
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.wait_for_timeout = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value={
            "status": 200,
            "body": "not json",
        })

        mock_browser = AsyncMock()
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        mock_browser.close = AsyncMock()

        mock_pw_ctx = AsyncMock()
        mock_pw_ctx.chromium.launch = AsyncMock(
            return_value=mock_browser,
        )

        mock_pw = AsyncMock()
        mock_pw.__aenter__ = AsyncMock(return_value=mock_pw_ctx)
        mock_pw.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "playwright.async_api.async_playwright",
            return_value=mock_pw,
        ):
            result = await client._playwright_post(
                "/dapi/path", {}, "csrf", "test",
            )
        assert "error" in result
        assert "Invalid JSON" in result["error"]

    async def test_exception_returns_error(self, tmp_path):
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)

        mock_pw = AsyncMock()
        mock_pw.__aenter__ = AsyncMock(
            side_effect=RuntimeError("browser crashed"),
        )
        mock_pw.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "playwright.async_api.async_playwright",
            return_value=mock_pw,
        ):
            result = await client._playwright_post(
                "/dapi/path", {}, "csrf", "test",
            )
        assert "error" in result
        assert "browser crashed" in result["error"]

    async def test_confirmation_without_security_token(self, tmp_path):
        """When response has confirmationNumber but no securityToken."""
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.wait_for_timeout = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value={
            "status": 200,
            "body": '{"confirmationNumber":"OT-NOSEC"}',
        })

        mock_browser = AsyncMock()
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        mock_browser.close = AsyncMock()

        mock_pw_ctx = AsyncMock()
        mock_pw_ctx.chromium.launch = AsyncMock(
            return_value=mock_browser,
        )

        mock_pw = AsyncMock()
        mock_pw.__aenter__ = AsyncMock(return_value=mock_pw_ctx)
        mock_pw.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "playwright.async_api.async_playwright",
            return_value=mock_pw,
        ):
            result = await client._playwright_post(
                "/dapi/booking/make-reservation",
                {"restaurantId": 100},
                "csrf",
                "test",
            )
        assert result == {"confirmation_number": "OT-NOSEC"}
        assert "security_token" not in result

    async def test_response_without_confirmation(self, tmp_path):
        """When response has no confirmationNumber, returns data."""
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.wait_for_timeout = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value={
            "status": 200,
            "body": '{"status": "cancelled"}',
        })

        mock_browser = AsyncMock()
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        mock_browser.close = AsyncMock()

        mock_pw_ctx = AsyncMock()
        mock_pw_ctx.chromium.launch = AsyncMock(
            return_value=mock_browser,
        )

        mock_pw = AsyncMock()
        mock_pw.__aenter__ = AsyncMock(return_value=mock_pw_ctx)
        mock_pw.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "playwright.async_api.async_playwright",
            return_value=mock_pw,
        ):
            result = await client._playwright_post(
                "/dapi/booking/cancel-reservation",
                {"confirmationNumber": "X"},
                "csrf",
                "cancel",
            )
        assert result == {"status": "cancelled"}
