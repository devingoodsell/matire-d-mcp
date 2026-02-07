"""Tests for the Resy API client."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.clients.resy import _USER_AGENT, ResyClient
from src.models.enums import BookingPlatform
from src.models.restaurant import TimeSlot

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(status_code=200, json_data=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


def _mock_client(response):
    client = AsyncMock()
    client.post.return_value = response
    client.get.return_value = response
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


# ---------------------------------------------------------------------------
# ResyClient._headers
# ---------------------------------------------------------------------------

class TestHeaders:
    def test_returns_correct_header_dict(self):
        rc = ResyClient(api_key="my_key", auth_token="my_token")
        headers = rc._headers()

        assert headers["Authorization"] == 'ResyAPI api_key="my_key"'
        assert headers["X-Resy-Auth-Token"] == "my_token"
        assert headers["X-Resy-Universal-Auth"] == "my_token"
        assert headers["User-Agent"] == _USER_AGENT
        assert headers["Accept"] == "application/json"
        assert headers["Origin"] == "https://resy.com"
        assert headers["Referer"] == "https://resy.com/"


# ---------------------------------------------------------------------------
# ResyClient.authenticate
# ---------------------------------------------------------------------------

class TestAuthenticate:
    @patch("src.clients.resy.httpx.AsyncClient")
    async def test_success(self, mock_async_client):
        resp = _mock_response(json_data={
            "token": "jwt_tok",
            "payment_method_id": "pm_123",
        })
        client = _mock_client(resp)
        mock_async_client.return_value = client

        rc = ResyClient(api_key="key1")
        result = await rc.authenticate("user@test.com", "pass")

        assert result["auth_token"] == "jwt_tok"
        assert result["payment_methods"] == "pm_123"
        assert result["api_key"] == "key1"
        resp.raise_for_status.assert_called_once()

    @patch("src.clients.resy.httpx.AsyncClient")
    async def test_payment_method_id_field(self, mock_async_client):
        resp = _mock_response(json_data={
            "token": "tok",
            "payment_method_id": "pm_456",
        })
        mock_async_client.return_value = _mock_client(resp)

        result = await ResyClient().authenticate("a@b.com", "p")
        assert result["payment_methods"] == "pm_456"

    @patch("src.clients.resy.httpx.AsyncClient")
    async def test_payment_methods_list(self, mock_async_client):
        resp = _mock_response(json_data={
            "token": "tok",
            "payment_methods": [{"id": 1}, {"id": 2}],
        })
        mock_async_client.return_value = _mock_client(resp)

        result = await ResyClient().authenticate("a@b.com", "p")
        assert result["payment_methods"] == [{"id": 1}, {"id": 2}]

    @patch("src.clients.resy.httpx.AsyncClient")
    async def test_neither_payment_field(self, mock_async_client):
        resp = _mock_response(json_data={"token": "tok"})
        mock_async_client.return_value = _mock_client(resp)

        result = await ResyClient().authenticate("a@b.com", "p")
        assert result["payment_methods"] == []

    @patch("src.clients.resy.httpx.AsyncClient")
    async def test_http_error_raises(self, mock_async_client):
        resp = _mock_response(status_code=401, text="Unauthorized")
        mock_async_client.return_value = _mock_client(resp)

        with pytest.raises(httpx.HTTPStatusError):
            await ResyClient().authenticate("a@b.com", "p")


# ---------------------------------------------------------------------------
# ResyClient.find_availability
# ---------------------------------------------------------------------------

class TestFindAvailability:
    @patch("src.clients.resy.httpx.AsyncClient")
    async def test_success_with_slots(self, mock_async_client):
        json_data = {
            "results": {
                "venues": [
                    {
                        "slots": [
                            {
                                "config": {"type": "Dining Room", "token": "cfg_1"},
                                "date": {"start": "2025-03-15 19:30"},
                            },
                            {
                                "config": {"type": "Bar", "token": "cfg_2"},
                                "date": {"start": "2025-03-15 20:00"},
                            },
                        ]
                    }
                ]
            }
        }
        resp = _mock_response(json_data=json_data)
        mock_async_client.return_value = _mock_client(resp)

        rc = ResyClient(auth_token="tok")
        slots = await rc.find_availability("123", "2025-03-15", 2)

        assert len(slots) == 2
        assert isinstance(slots[0], TimeSlot)
        assert slots[0].time == "19:30"
        assert slots[0].type == "Dining Room"
        assert slots[0].platform == BookingPlatform.RESY
        assert slots[0].config_id == "cfg_1"
        assert slots[1].time == "20:00"

    @patch("src.clients.resy.httpx.AsyncClient")
    async def test_empty_venues(self, mock_async_client):
        resp = _mock_response(json_data={"results": {"venues": []}})
        mock_async_client.return_value = _mock_client(resp)

        slots = await ResyClient().find_availability("1", "2025-01-01", 2)
        assert slots == []

    @patch("src.clients.resy.httpx.AsyncClient")
    async def test_non_200_returns_empty(self, mock_async_client):
        resp = _mock_response(status_code=500, text="Server Error")
        mock_async_client.return_value = _mock_client(resp)

        slots = await ResyClient().find_availability("1", "2025-01-01", 2)
        assert slots == []

    @patch("src.clients.resy.httpx.AsyncClient")
    async def test_parses_time_from_datetime_string(self, mock_async_client):
        json_data = {
            "results": {
                "venues": [
                    {
                        "slots": [
                            {
                                "config": {"type": "Table", "token": "t1"},
                                "date": {"start": "2025-06-01 18:45"},
                            }
                        ]
                    }
                ]
            }
        }
        resp = _mock_response(json_data=json_data)
        mock_async_client.return_value = _mock_client(resp)

        slots = await ResyClient().find_availability("1", "2025-06-01", 4)
        assert slots[0].time == "18:45"

    @patch("src.clients.resy.httpx.AsyncClient")
    async def test_time_without_space_passes_through(self, mock_async_client):
        json_data = {
            "results": {
                "venues": [
                    {
                        "slots": [
                            {
                                "config": {"type": "T", "token": "t"},
                                "date": {"start": "18:00"},
                            }
                        ]
                    }
                ]
            }
        }
        resp = _mock_response(json_data=json_data)
        mock_async_client.return_value = _mock_client(resp)

        slots = await ResyClient().find_availability("1", "2025-01-01", 2)
        assert slots[0].time == "18:00"


# ---------------------------------------------------------------------------
# ResyClient._parse_slots
# ---------------------------------------------------------------------------

class TestParseSlots:
    def test_no_venues_returns_empty(self):
        rc = ResyClient()
        assert rc._parse_slots({"results": {"venues": []}}) == []

    def test_no_results_key_returns_empty(self):
        rc = ResyClient()
        assert rc._parse_slots({}) == []

    def test_venues_with_slots(self):
        data = {
            "results": {
                "venues": [
                    {
                        "slots": [
                            {
                                "config": {"type": "Indoor", "token": "abc"},
                                "date": {"start": "2025-01-01 20:00"},
                            }
                        ]
                    }
                ]
            }
        }
        rc = ResyClient()
        slots = rc._parse_slots(data)

        assert len(slots) == 1
        assert slots[0].time == "20:00"
        assert slots[0].type == "Indoor"
        assert slots[0].config_id == "abc"
        assert slots[0].platform == BookingPlatform.RESY

    def test_slot_with_empty_config_and_date(self):
        data = {
            "results": {
                "venues": [
                    {
                        "slots": [
                            {"config": {}, "date": {}},
                        ]
                    }
                ]
            }
        }
        rc = ResyClient()
        slots = rc._parse_slots(data)

        assert len(slots) == 1
        assert slots[0].time == ""
        assert slots[0].type == ""
        assert slots[0].config_id == ""


# ---------------------------------------------------------------------------
# ResyClient.get_booking_details
# ---------------------------------------------------------------------------

class TestGetBookingDetails:
    @patch("src.clients.resy.httpx.AsyncClient")
    async def test_success(self, mock_async_client):
        resp = _mock_response(json_data={"book_token": {"value": "bt_1"}})
        mock_async_client.return_value = _mock_client(resp)

        result = await ResyClient(auth_token="t").get_booking_details("cfg", "2025-01-01", 2)
        assert result == {"book_token": {"value": "bt_1"}}

    @patch("src.clients.resy.httpx.AsyncClient")
    async def test_non_200_returns_empty_dict(self, mock_async_client):
        resp = _mock_response(status_code=404, text="Not Found")
        mock_async_client.return_value = _mock_client(resp)

        result = await ResyClient().get_booking_details("cfg", "2025-01-01", 2)
        assert result == {}


# ---------------------------------------------------------------------------
# ResyClient.book
# ---------------------------------------------------------------------------

class TestBook:
    @patch("src.clients.resy.httpx.AsyncClient")
    async def test_success_without_payment(self, mock_async_client):
        resp = _mock_response(json_data={"resy_token": "res_abc"})
        mock_async_client.return_value = _mock_client(resp)

        rc = ResyClient(auth_token="t")
        result = await rc.book("bt_1")

        assert result == {"resy_token": "res_abc"}
        call_kwargs = mock_async_client.return_value.post.call_args
        payload = call_kwargs.kwargs["json"]
        assert payload["book_token"] == "bt_1"
        assert payload["source_id"] == "resy.com-venue-details"
        assert "struct_payment_method" not in payload

    @patch("src.clients.resy.httpx.AsyncClient")
    async def test_success_with_payment(self, mock_async_client):
        resp = _mock_response(json_data={"resy_token": "res_def"})
        mock_async_client.return_value = _mock_client(resp)

        pm = {"id": 123, "type": "visa"}
        rc = ResyClient(auth_token="t")
        result = await rc.book("bt_2", payment_method=pm)

        assert result == {"resy_token": "res_def"}
        call_kwargs = mock_async_client.return_value.post.call_args
        payload = call_kwargs.kwargs["json"]
        assert payload["struct_payment_method"] == pm

    @patch("src.clients.resy.httpx.AsyncClient")
    async def test_non_200_returns_error(self, mock_async_client):
        resp = _mock_response(status_code=422, text="Unprocessable Entity")
        mock_async_client.return_value = _mock_client(resp)

        result = await ResyClient(auth_token="t").book("bt_bad")
        assert result == {"error": "Unprocessable Entity"}


# ---------------------------------------------------------------------------
# ResyClient.cancel
# ---------------------------------------------------------------------------

class TestCancel:
    @patch("src.clients.resy.httpx.AsyncClient")
    async def test_success(self, mock_async_client):
        resp = _mock_response(status_code=200)
        mock_async_client.return_value = _mock_client(resp)

        result = await ResyClient(auth_token="t").cancel("res_tok")
        assert result is True

    @patch("src.clients.resy.httpx.AsyncClient")
    async def test_failure(self, mock_async_client):
        resp = _mock_response(status_code=400, text="Bad Request")
        mock_async_client.return_value = _mock_client(resp)

        result = await ResyClient(auth_token="t").cancel("res_tok")
        assert result is False


# ---------------------------------------------------------------------------
# ResyClient.get_user_reservations
# ---------------------------------------------------------------------------

class TestGetUserReservations:
    @patch("src.clients.resy.httpx.AsyncClient")
    async def test_success_list_response(self, mock_async_client):
        data = [{"id": "r1"}, {"id": "r2"}]
        resp = _mock_response(json_data=data)
        # Override json to return a list (default helper wraps in dict)
        resp.json.return_value = data
        mock_async_client.return_value = _mock_client(resp)

        result = await ResyClient(auth_token="t").get_user_reservations()
        assert result == [{"id": "r1"}, {"id": "r2"}]

    @patch("src.clients.resy.httpx.AsyncClient")
    async def test_success_dict_with_reservations_key(self, mock_async_client):
        data = {"reservations": [{"id": "r3"}]}
        resp = _mock_response(json_data=data)
        mock_async_client.return_value = _mock_client(resp)

        result = await ResyClient(auth_token="t").get_user_reservations()
        assert result == [{"id": "r3"}]

    @patch("src.clients.resy.httpx.AsyncClient")
    async def test_non_200_returns_empty(self, mock_async_client):
        resp = _mock_response(status_code=503, text="Service Unavailable")
        mock_async_client.return_value = _mock_client(resp)

        result = await ResyClient(auth_token="t").get_user_reservations()
        assert result == []


# ---------------------------------------------------------------------------
# ResyClient.search_venue
# ---------------------------------------------------------------------------

class TestSearchVenue:
    @patch("src.clients.resy.httpx.AsyncClient")
    async def test_success_with_hits(self, mock_async_client):
        json_data = {
            "search": {
                "hits": [
                    {
                        "id": {"resy": 42},
                        "name": "Le Bernardin",
                        "location": {"city": "New York"},
                    },
                    {
                        "id": {"resy": 99},
                        "name": "Peter Luger",
                        "location": {"city": "Brooklyn"},
                    },
                ]
            }
        }
        resp = _mock_response(json_data=json_data)
        mock_async_client.return_value = _mock_client(resp)

        result = await ResyClient(auth_token="t").search_venue("steak", 40.7, -74.0)

        assert len(result) == 2
        assert result[0] == {
            "id": "42",
            "name": "Le Bernardin",
            "location": {"city": "New York"},
        }
        assert result[1]["id"] == "99"

    @patch("src.clients.resy.httpx.AsyncClient")
    async def test_empty_hits(self, mock_async_client):
        resp = _mock_response(json_data={"search": {"hits": []}})
        mock_async_client.return_value = _mock_client(resp)

        result = await ResyClient().search_venue("nonexistent", 0.0, 0.0)
        assert result == []

    @patch("src.clients.resy.httpx.AsyncClient")
    async def test_non_200_returns_empty(self, mock_async_client):
        resp = _mock_response(status_code=500, text="Internal Server Error")
        mock_async_client.return_value = _mock_client(resp)

        result = await ResyClient().search_venue("test", 0.0, 0.0)
        assert result == []
