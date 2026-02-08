"""Tests for OpenTableClient: DAPI HTTP API for OpenTable reservations."""

from unittest.mock import AsyncMock, MagicMock

import httpx

from src.clients.opentable import (
    OpenTableClient,
    _build_restaurant_url,
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


class TestResolveRestaurantId:
    """_resolve_restaurant_id: slug → numeric rid via page HTML."""

    async def test_success_extracts_rid(self, tmp_path):
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '<div data-rid="8033">Ci Siamo</div>'

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)
        client._http = mock_http

        rid = await client._resolve_restaurant_id("ci-siamo-new-york")
        assert rid == 8033
        mock_http.get.assert_awaited_once()

    async def test_caches_result(self, tmp_path):
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"rid":8033}'

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)
        client._http = mock_http

        rid1 = await client._resolve_restaurant_id("ci-siamo")
        rid2 = await client._resolve_restaurant_id("ci-siamo")
        assert rid1 == rid2 == 8033
        # Only one HTTP call — second used cache
        assert mock_http.get.await_count == 1

    async def test_non_200_returns_none(self, tmp_path):
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)

        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "Not found"

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)
        client._http = mock_http

        rid = await client._resolve_restaurant_id("nonexistent")
        assert rid is None

    async def test_no_rid_in_page_returns_none(self, tmp_path):
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html>No rid here</html>"

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)
        client._http = mock_http

        rid = await client._resolve_restaurant_id("no-rid")
        assert rid is None

    async def test_http_error_returns_none(self, tmp_path):
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(side_effect=httpx.ConnectError("timeout"))
        client._http = mock_http

        rid = await client._resolve_restaurant_id("timeout-slug")
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

        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "Not found"

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)
        client._http = mock_http

        slots = await client.find_availability(
            "nonexistent", "2026-03-15", 2
        )
        assert slots == []

    async def test_non_200_gql_returns_empty(self, tmp_path):
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)
        client._rid_cache["slug"] = 100

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Server error"

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        client._http = mock_http

        slots = await client.find_availability("slug", "2026-03-15", 2)
        assert slots == []

    async def test_http_error_returns_empty(self, tmp_path):
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)
        client._rid_cache["slug"] = 100

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(side_effect=httpx.ConnectError("network down"))
        client._http = mock_http

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

        await client.find_availability("slug", "2026-03-15", 2)
        call_args = mock_http.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["variables"]["requestedTime"] == "19:00"


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

    async def test_http_error_during_booking(self, tmp_path):
        store = _make_credential_store(tmp_path)
        store.save_credentials("opentable", {"csrf_token": "tok", "email": "u@t.com"})
        client = OpenTableClient(store)
        client._rid_cache["slug"] = 100

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(side_effect=httpx.ConnectError("timeout"))
        client._http = mock_http

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


class TestCancel:
    """cancel: DAPI cancel-reservation endpoint."""

    async def test_success_returns_true(self, tmp_path):
        store = _make_credential_store(tmp_path)
        store.save_credentials("opentable", {"csrf_token": "csrf-abc", "email": "u@t.com"})
        client = OpenTableClient(store)

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        client._http = mock_http

        result = await client.cancel("OT-12345")
        assert result is True
        call_args = mock_http.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["confirmationNumber"] == "OT-12345"
        headers = call_args.kwargs.get("headers") or call_args[1].get("headers")
        assert headers["x-csrf-token"] == "csrf-abc"

    async def test_no_csrf_token_returns_false(self, tmp_path):
        store = _make_credential_store(tmp_path)
        store.save_credentials("opentable", {"email": "u@t.com"})
        client = OpenTableClient(store)

        result = await client.cancel("OT-12345")
        assert result is False

    async def test_no_credentials_returns_false(self, tmp_path):
        store = _make_credential_store(tmp_path)
        client = OpenTableClient(store)

        result = await client.cancel("OT-12345")
        assert result is False

    async def test_non_200_returns_false(self, tmp_path):
        store = _make_credential_store(tmp_path)
        store.save_credentials("opentable", {"csrf_token": "tok", "email": "u@t.com"})
        client = OpenTableClient(store)

        mock_resp = MagicMock()
        mock_resp.status_code = 400

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        client._http = mock_http

        result = await client.cancel("OT-12345")
        assert result is False

    async def test_http_error_returns_false(self, tmp_path):
        store = _make_credential_store(tmp_path)
        store.save_credentials("opentable", {"csrf_token": "tok", "email": "u@t.com"})
        client = OpenTableClient(store)

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(side_effect=httpx.ConnectError("timeout"))
        client._http = mock_http

        result = await client.cancel("OT-12345")
        assert result is False
