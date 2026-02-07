"""Tests for src.tools.booking — credentials, availability, reservations."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import Client, FastMCP

from src.models.enums import BookingPlatform
from src.models.restaurant import TimeSlot
from src.storage.database import DatabaseManager
from src.tools.booking import (
    _format_time,
    _get_auth_manager,
    _get_credential_store,
    _normalise_time,
    _time_diff,
    register_booking_tools,
)
from tests.factories import make_reservation, make_restaurant

# ── Helpers ────────────────────────────────────────────────────────────────


@pytest.fixture
async def db():
    """In-memory SQLite database with schema applied."""
    manager = DatabaseManager(":memory:")
    await manager.initialize()
    yield manager
    await manager.close()


@pytest.fixture
def booking_mcp(db):
    """Return (mcp, db, mock_cred_store, mock_auth) with core patches active.

    Patches ``get_db``, ``_get_credential_store``, and ``_get_auth_manager``
    so that every tool registered on the test MCP server talks to the
    in-memory database and mock auth layer.
    """
    test_mcp = FastMCP("test")

    db_patch = patch("src.tools.booking.get_db", return_value=db)
    store_patch = patch("src.tools.booking._get_credential_store")
    auth_patch = patch("src.tools.booking._get_auth_manager")

    db_patch.start()
    mock_store_fn = store_patch.start()
    mock_auth_fn = auth_patch.start()

    # Default credential store
    mock_cred_store = MagicMock()
    mock_cred_store.get_credentials.return_value = {
        "api_key": "test-api-key",
        "auth_token": "test-token",
    }
    mock_store_fn.return_value = mock_cred_store

    # Default auth manager
    mock_auth = AsyncMock()
    mock_auth.ensure_valid_token.return_value = "valid-token"
    mock_auth.authenticate.return_value = {
        "auth_token": "tok",
        "api_key": "key",
        "payment_methods": [],
    }
    mock_auth_fn.return_value = mock_auth

    register_booking_tools(test_mcp)

    yield test_mcp, db, mock_cred_store, mock_auth

    db_patch.stop()
    store_patch.stop()
    auth_patch.stop()


def _make_slot(time: str = "19:00", slot_type: str | None = None, config_id: str = "cfg1"):
    """Build a TimeSlot for tests."""
    return TimeSlot(
        time=time,
        type=slot_type,
        platform=BookingPlatform.RESY,
        config_id=config_id,
    )


# ── _format_time ───────────────────────────────────────────────────────────


class TestFormatTime:
    def test_evening_time(self):
        assert _format_time("19:00") == "7:00 PM"

    def test_morning_time(self):
        assert _format_time("09:30") == "9:30 AM"

    def test_noon(self):
        assert _format_time("12:00") == "12:00 PM"

    def test_midnight(self):
        assert _format_time("00:00") == "12:00 AM"

    def test_1am(self):
        assert _format_time("01:15") == "1:15 AM"

    def test_hour_only_no_colon(self):
        """Edge case: no colon — uses default minute '00'."""
        assert _format_time("19") == "7:00 PM"

    def test_invalid_string_returns_original(self):
        assert _format_time("not-a-time") == "not-a-time"

    def test_empty_string_returns_original(self):
        assert _format_time("") == ""


# ── _normalise_time ────────────────────────────────────────────────────────


class TestNormaliseTime:
    def test_12h_pm(self):
        assert _normalise_time("7:00 PM") == "19:00"

    def test_24h_passthrough(self):
        assert _normalise_time("19:00") == "19:00"

    def test_midnight_12am(self):
        assert _normalise_time("12:00 AM") == "00:00"

    def test_noon_12pm(self):
        assert _normalise_time("12:00 PM") == "12:00"

    def test_am_time(self):
        assert _normalise_time("9:30 AM") == "09:30"

    def test_strips_whitespace(self):
        assert _normalise_time("  7:00 PM  ") == "19:00"

    def test_case_insensitive(self):
        assert _normalise_time("7:00 pm") == "19:00"

    def test_no_minutes_pm(self):
        """Input like '7 PM' without colon — still gets :00."""
        assert _normalise_time("7 PM") == "19:00"

    def test_no_minutes_am(self):
        assert _normalise_time("9 AM") == "09:00"


# ── _time_diff ─────────────────────────────────────────────────────────────


class TestTimeDiff:
    def test_normal_diff(self):
        assert _time_diff("19:00", "20:30") == 90

    def test_same_time(self):
        assert _time_diff("12:00", "12:00") == 0

    def test_reverse_order(self):
        assert _time_diff("20:30", "19:00") == 90

    def test_invalid_input_returns_9999(self):
        assert _time_diff("bad", "19:00") == 9999

    def test_empty_string_returns_9999(self):
        assert _time_diff("", "") == 9999

    def test_partial_time_returns_9999(self):
        assert _time_diff("19", "20:00") == 9999


# ── store_resy_credentials ─────────────────────────────────────────────────


class TestStoreResyCredentials:
    async def test_success_with_payment_method(self, booking_mcp):
        mcp, _db, mock_cred_store, mock_auth = booking_mcp
        mock_auth.authenticate.return_value = {
            "auth_token": "tok",
            "api_key": "key",
            "payment_methods": [{"id": 12345}],
        }
        async with Client(mcp) as client:
            result = await client.call_tool(
                "store_resy_credentials",
                {"email": "a@b.com", "password": "secret"},
            )
        text = str(result)
        assert "Credentials saved and verified" in text
        assert "Payment method detected" in text
        mock_cred_store.save_credentials.assert_called_once()
        saved = mock_cred_store.save_credentials.call_args[0][1]
        assert saved["email"] == "a@b.com"
        assert saved["payment_methods"] == [{"id": 12345}]

    async def test_success_no_payment_methods(self, booking_mcp):
        mcp, _db, mock_cred_store, mock_auth = booking_mcp
        mock_auth.authenticate.return_value = {
            "auth_token": "tok",
            "api_key": "key",
            "payment_methods": [],
        }
        async with Client(mcp) as client:
            result = await client.call_tool(
                "store_resy_credentials",
                {"email": "a@b.com", "password": "pw"},
            )
        text = str(result)
        assert "Credentials saved and verified." in text
        assert "Payment method" not in text

    async def test_success_no_payment_key(self, booking_mcp):
        """payment_methods key missing from response entirely."""
        mcp, _db, _store, mock_auth = booking_mcp
        mock_auth.authenticate.return_value = {
            "auth_token": "tok",
            "api_key": "key",
        }
        async with Client(mcp) as client:
            result = await client.call_tool(
                "store_resy_credentials",
                {"email": "a@b.com", "password": "pw"},
            )
        text = str(result)
        assert "Credentials saved and verified." in text
        assert "Payment method" not in text

    async def test_auth_failure(self, booking_mcp):
        from src.clients.resy_auth import AuthError

        mcp, _db, _store, mock_auth = booking_mcp
        mock_auth.authenticate.side_effect = AuthError("bad creds")
        async with Client(mcp) as client:
            result = await client.call_tool(
                "store_resy_credentials",
                {"email": "a@b.com", "password": "wrong"},
            )
        text = str(result)
        assert "Login failed" in text
        assert "bad creds" in text

    async def test_generic_exception(self, booking_mcp):
        mcp, _db, _store, mock_auth = booking_mcp
        mock_auth.authenticate.side_effect = RuntimeError("network down")
        async with Client(mcp) as client:
            result = await client.call_tool(
                "store_resy_credentials",
                {"email": "a@b.com", "password": "pw"},
            )
        text = str(result)
        assert "Login failed" in text
        assert "network down" in text


# ── check_availability ─────────────────────────────────────────────────────


class TestCheckAvailability:
    async def test_success_with_slots(self, booking_mcp):
        mcp, db, _store, _auth = booking_mcp
        restaurant = make_restaurant(name="Carbone", resy_venue_id="rv1")
        await db.cache_restaurant(restaurant)

        with patch("src.clients.resy.ResyClient") as mock_resy_cls:
            instance = AsyncMock()
            mock_resy_cls.return_value = instance
            instance.find_availability.return_value = [
                _make_slot("18:00", "Dining Room"),
                _make_slot("19:00", "Patio"),
            ]
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "check_availability",
                    {
                        "restaurant_name": "Carbone",
                        "date": "2026-02-14",
                        "party_size": 2,
                    },
                )
        text = str(result)
        assert "Carbone" in text
        assert "6:00 PM - Dining Room" in text
        assert "7:00 PM - Patio" in text

    async def test_success_with_preferred_time_sorting(self, booking_mcp):
        mcp, db, _store, _auth = booking_mcp
        restaurant = make_restaurant(name="Carbone", resy_venue_id="rv1")
        await db.cache_restaurant(restaurant)

        with patch("src.clients.resy.ResyClient") as mock_resy_cls:
            instance = AsyncMock()
            mock_resy_cls.return_value = instance
            instance.find_availability.return_value = [
                _make_slot("17:00"),
                _make_slot("20:00"),
                _make_slot("19:00"),
            ]
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "check_availability",
                    {
                        "restaurant_name": "Carbone",
                        "date": "2026-02-14",
                        "party_size": 2,
                        "preferred_time": "19:00",
                    },
                )
        text = str(result)
        lines = text.split("\\n")
        # First slot line should be 7:00 PM (closest to 19:00)
        slot_lines = [ln for ln in lines if "PM" in ln or "AM" in ln]
        assert "7:00 PM" in slot_lines[0]

    async def test_restaurant_not_in_cache(self, booking_mcp):
        mcp, _db, _store, _auth = booking_mcp
        async with Client(mcp) as client:
            result = await client.call_tool(
                "check_availability",
                {
                    "restaurant_name": "Unknown Place",
                    "date": "2026-02-14",
                },
            )
        text = str(result)
        assert "not found in cache" in text
        assert "search_restaurants" in text

    async def test_date_parse_fails(self, booking_mcp):
        mcp, db, _store, _auth = booking_mcp
        restaurant = make_restaurant(name="Carbone")
        await db.cache_restaurant(restaurant)

        with patch("src.tools.date_utils.parse_date", side_effect=ValueError("bad")):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "check_availability",
                    {
                        "restaurant_name": "Carbone",
                        "date": "gibberish-date",
                    },
                )
        text = str(result)
        assert "Could not parse date" in text

    async def test_auth_fails(self, booking_mcp):
        from src.clients.resy_auth import AuthError

        mcp, db, _store, mock_auth = booking_mcp
        restaurant = make_restaurant(name="Carbone")
        await db.cache_restaurant(restaurant)
        mock_auth.ensure_valid_token.side_effect = AuthError("no creds")

        async with Client(mcp) as client:
            result = await client.call_tool(
                "check_availability",
                {
                    "restaurant_name": "Carbone",
                    "date": "2026-02-14",
                },
            )
        text = str(result)
        assert "Resy auth error" in text

    async def test_venue_not_found_on_resy(self, booking_mcp):
        """Restaurant cached but no resy_venue_id and matcher returns None."""
        mcp, db, _store, _auth = booking_mcp
        restaurant = make_restaurant(name="Local Spot", resy_venue_id=None)
        await db.cache_restaurant(restaurant)

        with (
            patch("src.clients.resy.ResyClient") as mock_resy_cls,
            patch("src.matching.venue_matcher.VenueMatcher") as mock_matcher_cls,
        ):
            mock_resy_cls.return_value = AsyncMock()
            matcher_instance = AsyncMock()
            mock_matcher_cls.return_value = matcher_instance
            matcher_instance.find_resy_venue.return_value = None

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "check_availability",
                    {
                        "restaurant_name": "Local Spot",
                        "date": "2026-02-14",
                    },
                )
        text = str(result)
        assert "doesn't appear to be on Resy" in text

    async def test_no_slots_found(self, booking_mcp):
        mcp, db, _store, _auth = booking_mcp
        restaurant = make_restaurant(name="Carbone", resy_venue_id="rv1")
        await db.cache_restaurant(restaurant)

        with patch("src.clients.resy.ResyClient") as mock_resy_cls:
            instance = AsyncMock()
            mock_resy_cls.return_value = instance
            instance.find_availability.return_value = []

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "check_availability",
                    {
                        "restaurant_name": "Carbone",
                        "date": "2026-02-14",
                    },
                )
        text = str(result)
        assert "No availability" in text
        assert "Carbone" in text

    async def test_resy_venue_id_cached_skips_matcher(self, booking_mcp):
        """When resy_venue_id is already set, VenueMatcher should not be used."""
        mcp, db, _store, _auth = booking_mcp
        restaurant = make_restaurant(name="Carbone", resy_venue_id="rv1")
        await db.cache_restaurant(restaurant)

        with (
            patch("src.clients.resy.ResyClient") as mock_resy_cls,
            patch("src.matching.venue_matcher.VenueMatcher") as mock_matcher_cls,
        ):
            instance = AsyncMock()
            mock_resy_cls.return_value = instance
            instance.find_availability.return_value = [_make_slot("19:00")]

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "check_availability",
                    {
                        "restaurant_name": "Carbone",
                        "date": "2026-02-14",
                    },
                )

            mock_matcher_cls.assert_not_called()
        text = str(result)
        assert "7:00 PM" in text

    async def test_slot_without_type(self, booking_mcp):
        """Slot with type=None should not display a type label."""
        mcp, db, _store, _auth = booking_mcp
        restaurant = make_restaurant(name="Carbone", resy_venue_id="rv1")
        await db.cache_restaurant(restaurant)

        with patch("src.clients.resy.ResyClient") as mock_resy_cls:
            instance = AsyncMock()
            mock_resy_cls.return_value = instance
            instance.find_availability.return_value = [
                _make_slot("19:00", slot_type=None),
            ]
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "check_availability",
                    {
                        "restaurant_name": "Carbone",
                        "date": "2026-02-14",
                    },
                )
        text = str(result)
        assert "7:00 PM (Resy)" in text
        # No dash for type label
        assert "7:00 PM -" not in text


# ── make_reservation ───────────────────────────────────────────────────────


class TestMakeReservation:
    async def test_success_slot_found_and_booked(self, booking_mcp):
        mcp, db, mock_store, _auth = booking_mcp
        restaurant = make_restaurant(name="Carbone", resy_venue_id="rv1")
        await db.cache_restaurant(restaurant)

        with patch("src.clients.resy.ResyClient") as mock_resy_cls:
            instance = AsyncMock()
            mock_resy_cls.return_value = instance
            instance.find_availability.return_value = [
                _make_slot("19:00", config_id="cfg-abc"),
            ]
            instance.get_booking_details.return_value = {
                "book_token": {"value": "bt-xyz"},
            }
            instance.book.return_value = {
                "resy_token": "RES-12345",
            }

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "make_reservation",
                    {
                        "restaurant_name": "Carbone",
                        "date": "2026-02-14",
                        "time": "7:00 PM",
                        "party_size": 2,
                    },
                )
        text = str(result)
        assert "Booked!" in text
        assert "Carbone" in text
        assert "7:00 PM" in text
        assert "RES-12345" in text

        # Verify reservation saved in DB
        upcoming = await db.get_upcoming_reservations()
        assert len(upcoming) == 1
        assert upcoming[0].restaurant_name == "Carbone"
        assert upcoming[0].platform_confirmation_id == "RES-12345"

    async def test_restaurant_not_found(self, booking_mcp):
        mcp, _db, _store, _auth = booking_mcp
        async with Client(mcp) as client:
            result = await client.call_tool(
                "make_reservation",
                {
                    "restaurant_name": "Nonexistent",
                    "date": "2026-02-14",
                    "time": "19:00",
                },
            )
        text = str(result)
        assert "not found" in text
        assert "Search for it first" in text

    async def test_date_parse_fails(self, booking_mcp):
        mcp, db, _store, _auth = booking_mcp
        restaurant = make_restaurant(name="Carbone")
        await db.cache_restaurant(restaurant)

        with patch("src.tools.date_utils.parse_date", side_effect=ValueError("bad")):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "make_reservation",
                    {
                        "restaurant_name": "Carbone",
                        "date": "gibberish",
                        "time": "19:00",
                    },
                )
        text = str(result)
        assert "Could not parse date" in text

    async def test_auth_fails(self, booking_mcp):
        from src.clients.resy_auth import AuthError

        mcp, db, _store, mock_auth = booking_mcp
        restaurant = make_restaurant(name="Carbone")
        await db.cache_restaurant(restaurant)
        mock_auth.ensure_valid_token.side_effect = AuthError("expired")

        async with Client(mcp) as client:
            result = await client.call_tool(
                "make_reservation",
                {
                    "restaurant_name": "Carbone",
                    "date": "2026-02-14",
                    "time": "19:00",
                },
            )
        text = str(result)
        assert "Resy auth error" in text

    async def test_venue_not_found(self, booking_mcp):
        mcp, db, _store, _auth = booking_mcp
        restaurant = make_restaurant(name="Carbone", resy_venue_id=None)
        await db.cache_restaurant(restaurant)

        with (
            patch("src.clients.resy.ResyClient") as mock_resy_cls,
            patch("src.matching.venue_matcher.VenueMatcher") as mock_matcher_cls,
        ):
            mock_resy_cls.return_value = AsyncMock()
            matcher_instance = AsyncMock()
            mock_matcher_cls.return_value = matcher_instance
            matcher_instance.find_resy_venue.return_value = None

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "make_reservation",
                    {
                        "restaurant_name": "Carbone",
                        "date": "2026-02-14",
                        "time": "19:00",
                    },
                )
        text = str(result)
        assert "doesn't appear to be on Resy" in text

    async def test_no_matching_time_shows_alternatives(self, booking_mcp):
        mcp, db, _store, _auth = booking_mcp
        restaurant = make_restaurant(name="Carbone", resy_venue_id="rv1")
        await db.cache_restaurant(restaurant)

        with patch("src.clients.resy.ResyClient") as mock_resy_cls:
            instance = AsyncMock()
            mock_resy_cls.return_value = instance
            instance.find_availability.return_value = [
                _make_slot("18:00"),
                _make_slot("20:00"),
                _make_slot("21:00"),
            ]
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "make_reservation",
                    {
                        "restaurant_name": "Carbone",
                        "date": "2026-02-14",
                        "time": "19:00",
                        "party_size": 2,
                    },
                )
        text = str(result)
        assert "No slot at 7:00 PM" in text
        assert "Available:" in text
        assert "6:00 PM" in text
        assert "8:00 PM" in text

    async def test_no_matching_slot_no_available_slots(self, booking_mcp):
        mcp, db, _store, _auth = booking_mcp
        restaurant = make_restaurant(name="Carbone", resy_venue_id="rv1")
        await db.cache_restaurant(restaurant)

        with patch("src.clients.resy.ResyClient") as mock_resy_cls:
            instance = AsyncMock()
            mock_resy_cls.return_value = instance
            instance.find_availability.return_value = []

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "make_reservation",
                    {
                        "restaurant_name": "Carbone",
                        "date": "2026-02-14",
                        "time": "19:00",
                    },
                )
        text = str(result)
        assert "No availability" in text
        assert "Carbone" in text

    async def test_booking_fails_error_in_response(self, booking_mcp):
        mcp, db, _store, _auth = booking_mcp
        restaurant = make_restaurant(name="Carbone", resy_venue_id="rv1")
        await db.cache_restaurant(restaurant)

        with patch("src.clients.resy.ResyClient") as mock_resy_cls:
            instance = AsyncMock()
            mock_resy_cls.return_value = instance
            instance.find_availability.return_value = [_make_slot("19:00")]
            instance.get_booking_details.return_value = {
                "book_token": {"value": "bt-xyz"},
            }
            instance.book.return_value = {"error": "Card declined"}

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "make_reservation",
                    {
                        "restaurant_name": "Carbone",
                        "date": "2026-02-14",
                        "time": "19:00",
                    },
                )
        text = str(result)
        assert "Booking failed" in text
        assert "Card declined" in text

    async def test_could_not_get_book_token(self, booking_mcp):
        mcp, db, _store, _auth = booking_mcp
        restaurant = make_restaurant(name="Carbone", resy_venue_id="rv1")
        await db.cache_restaurant(restaurant)

        with patch("src.clients.resy.ResyClient") as mock_resy_cls:
            instance = AsyncMock()
            mock_resy_cls.return_value = instance
            instance.find_availability.return_value = [_make_slot("19:00")]
            instance.get_booking_details.return_value = {}

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "make_reservation",
                    {
                        "restaurant_name": "Carbone",
                        "date": "2026-02-14",
                        "time": "19:00",
                    },
                )
        text = str(result)
        assert "Could not get booking token" in text

    async def test_book_token_value_empty(self, booking_mcp):
        """book_token key exists but value is empty string."""
        mcp, db, _store, _auth = booking_mcp
        restaurant = make_restaurant(name="Carbone", resy_venue_id="rv1")
        await db.cache_restaurant(restaurant)

        with patch("src.clients.resy.ResyClient") as mock_resy_cls:
            instance = AsyncMock()
            mock_resy_cls.return_value = instance
            instance.find_availability.return_value = [_make_slot("19:00")]
            instance.get_booking_details.return_value = {
                "book_token": {"value": ""},
            }

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "make_reservation",
                    {
                        "restaurant_name": "Carbone",
                        "date": "2026-02-14",
                        "time": "19:00",
                    },
                )
        text = str(result)
        assert "Could not get booking token" in text

    async def test_with_special_requests(self, booking_mcp):
        mcp, db, _store, _auth = booking_mcp
        restaurant = make_restaurant(name="Carbone", resy_venue_id="rv1")
        await db.cache_restaurant(restaurant)

        with patch("src.clients.resy.ResyClient") as mock_resy_cls:
            instance = AsyncMock()
            mock_resy_cls.return_value = instance
            instance.find_availability.return_value = [_make_slot("19:00")]
            instance.get_booking_details.return_value = {
                "book_token": {"value": "bt-xyz"},
            }
            instance.book.return_value = {"resy_token": "RES-99"}

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "make_reservation",
                    {
                        "restaurant_name": "Carbone",
                        "date": "2026-02-14",
                        "time": "19:00",
                        "special_requests": "birthday dinner",
                    },
                )
        text = str(result)
        assert "Booked!" in text

        upcoming = await db.get_upcoming_reservations()
        assert len(upcoming) == 1
        assert upcoming[0].special_requests == "birthday dinner"

    async def test_payment_method_string_wraps_in_dict(self, booking_mcp):
        """When payment_methods is a string, it should be wrapped as {'id': ...}."""
        mcp, db, mock_store, _auth = booking_mcp
        mock_store.get_credentials.return_value = {
            "api_key": "key",
            "auth_token": "tok",
            "payment_methods": "pm-string-id",
        }
        restaurant = make_restaurant(name="Carbone", resy_venue_id="rv1")
        await db.cache_restaurant(restaurant)

        with patch("src.clients.resy.ResyClient") as mock_resy_cls:
            instance = AsyncMock()
            mock_resy_cls.return_value = instance
            instance.find_availability.return_value = [_make_slot("19:00")]
            instance.get_booking_details.return_value = {
                "book_token": {"value": "bt-xyz"},
            }
            instance.book.return_value = {"resy_token": "RES-1"}

            async with Client(mcp) as client:
                await client.call_tool(
                    "make_reservation",
                    {
                        "restaurant_name": "Carbone",
                        "date": "2026-02-14",
                        "time": "19:00",
                    },
                )
            instance.book.assert_called_once_with(
                book_token="bt-xyz",
                payment_method={"id": "pm-string-id"},
            )

    async def test_payment_method_int_wraps_in_dict(self, booking_mcp):
        """When payment_methods is an int, it should be wrapped as {'id': ...}."""
        mcp, db, mock_store, _auth = booking_mcp
        mock_store.get_credentials.return_value = {
            "api_key": "key",
            "auth_token": "tok",
            "payment_methods": 12345,
        }
        restaurant = make_restaurant(name="Carbone", resy_venue_id="rv1")
        await db.cache_restaurant(restaurant)

        with patch("src.clients.resy.ResyClient") as mock_resy_cls:
            instance = AsyncMock()
            mock_resy_cls.return_value = instance
            instance.find_availability.return_value = [_make_slot("19:00")]
            instance.get_booking_details.return_value = {
                "book_token": {"value": "bt-xyz"},
            }
            instance.book.return_value = {"resy_token": "RES-2"}

            async with Client(mcp) as client:
                await client.call_tool(
                    "make_reservation",
                    {
                        "restaurant_name": "Carbone",
                        "date": "2026-02-14",
                        "time": "19:00",
                    },
                )
            instance.book.assert_called_once_with(
                book_token="bt-xyz",
                payment_method={"id": 12345},
            )

    async def test_payment_method_none_no_dict(self, booking_mcp):
        """When payment_methods is None, payment_method should be None."""
        mcp, db, mock_store, _auth = booking_mcp
        mock_store.get_credentials.return_value = {
            "api_key": "key",
            "auth_token": "tok",
        }
        restaurant = make_restaurant(name="Carbone", resy_venue_id="rv1")
        await db.cache_restaurant(restaurant)

        with patch("src.clients.resy.ResyClient") as mock_resy_cls:
            instance = AsyncMock()
            mock_resy_cls.return_value = instance
            instance.find_availability.return_value = [_make_slot("19:00")]
            instance.get_booking_details.return_value = {
                "book_token": {"value": "bt-xyz"},
            }
            instance.book.return_value = {"resy_token": "RES-3"}

            async with Client(mcp) as client:
                await client.call_tool(
                    "make_reservation",
                    {
                        "restaurant_name": "Carbone",
                        "date": "2026-02-14",
                        "time": "19:00",
                    },
                )
            instance.book.assert_called_once_with(
                book_token="bt-xyz",
                payment_method=None,
            )

    async def test_payment_method_list_passes_none(self, booking_mcp):
        """When payment_methods is a list, isinstance check fails -> None."""
        mcp, db, mock_store, _auth = booking_mcp
        mock_store.get_credentials.return_value = {
            "api_key": "key",
            "auth_token": "tok",
            "payment_methods": [{"id": 1}],
        }
        restaurant = make_restaurant(name="Carbone", resy_venue_id="rv1")
        await db.cache_restaurant(restaurant)

        with patch("src.clients.resy.ResyClient") as mock_resy_cls:
            instance = AsyncMock()
            mock_resy_cls.return_value = instance
            instance.find_availability.return_value = [_make_slot("19:00")]
            instance.get_booking_details.return_value = {
                "book_token": {"value": "bt-xyz"},
            }
            instance.book.return_value = {"resy_token": "RES-4"}

            async with Client(mcp) as client:
                await client.call_tool(
                    "make_reservation",
                    {
                        "restaurant_name": "Carbone",
                        "date": "2026-02-14",
                        "time": "19:00",
                    },
                )
            instance.book.assert_called_once_with(
                book_token="bt-xyz",
                payment_method=None,
            )

    async def test_result_uses_reservation_id_fallback(self, booking_mcp):
        """When resy_token is absent, reservation_id is used."""
        mcp, db, _store, _auth = booking_mcp
        restaurant = make_restaurant(name="Carbone", resy_venue_id="rv1")
        await db.cache_restaurant(restaurant)

        with patch("src.clients.resy.ResyClient") as mock_resy_cls:
            instance = AsyncMock()
            mock_resy_cls.return_value = instance
            instance.find_availability.return_value = [_make_slot("19:00")]
            instance.get_booking_details.return_value = {
                "book_token": {"value": "bt-xyz"},
            }
            instance.book.return_value = {"reservation_id": "fallback-id"}

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "make_reservation",
                    {
                        "restaurant_name": "Carbone",
                        "date": "2026-02-14",
                        "time": "19:00",
                    },
                )
        text = str(result)
        assert "fallback-id" in text

    async def test_venue_matcher_used_when_no_resy_venue_id(self, booking_mcp):
        """When restaurant has no resy_venue_id, VenueMatcher is called."""
        mcp, db, _store, _auth = booking_mcp
        restaurant = make_restaurant(name="Carbone", resy_venue_id=None)
        await db.cache_restaurant(restaurant)

        with (
            patch("src.clients.resy.ResyClient") as mock_resy_cls,
            patch("src.matching.venue_matcher.VenueMatcher") as mock_matcher_cls,
        ):
            instance = AsyncMock()
            mock_resy_cls.return_value = instance
            matcher_instance = AsyncMock()
            mock_matcher_cls.return_value = matcher_instance
            matcher_instance.find_resy_venue.return_value = "found-venue-id"
            instance.find_availability.return_value = [_make_slot("19:00")]
            instance.get_booking_details.return_value = {
                "book_token": {"value": "bt-xyz"},
            }
            instance.book.return_value = {"resy_token": "RES-OK"}

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "make_reservation",
                    {
                        "restaurant_name": "Carbone",
                        "date": "2026-02-14",
                        "time": "19:00",
                    },
                )
            mock_matcher_cls.assert_called_once()
            matcher_instance.find_resy_venue.assert_called_once()
        text = str(result)
        assert "Booked!" in text

    async def test_config_id_none_uses_empty_string(self, booking_mcp):
        """When slot.config_id is None, empty string is passed."""
        mcp, db, _store, _auth = booking_mcp
        restaurant = make_restaurant(name="Carbone", resy_venue_id="rv1")
        await db.cache_restaurant(restaurant)

        slot = TimeSlot(
            time="19:00",
            platform=BookingPlatform.RESY,
            config_id=None,
        )
        with patch("src.clients.resy.ResyClient") as mock_resy_cls:
            instance = AsyncMock()
            mock_resy_cls.return_value = instance
            instance.find_availability.return_value = [slot]
            instance.get_booking_details.return_value = {
                "book_token": {"value": "bt-xyz"},
            }
            instance.book.return_value = {"resy_token": "RES-X"}

            async with Client(mcp) as client:
                await client.call_tool(
                    "make_reservation",
                    {
                        "restaurant_name": "Carbone",
                        "date": "2026-02-14",
                        "time": "19:00",
                    },
                )
            instance.get_booking_details.assert_called_once_with(
                config_id="",
                date="2026-02-14",
                party_size=2,
            )

    async def test_alternatives_limited_to_five(self, booking_mcp):
        """When no matching slot, only first 5 alternatives are shown."""
        mcp, db, _store, _auth = booking_mcp
        restaurant = make_restaurant(name="Carbone", resy_venue_id="rv1")
        await db.cache_restaurant(restaurant)

        many_slots = [_make_slot(f"{h}:00") for h in range(16, 23)]
        with patch("src.clients.resy.ResyClient") as mock_resy_cls:
            instance = AsyncMock()
            mock_resy_cls.return_value = instance
            instance.find_availability.return_value = many_slots

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "make_reservation",
                    {
                        "restaurant_name": "Carbone",
                        "date": "2026-02-14",
                        "time": "12:00",
                        "party_size": 2,
                    },
                )
        text = str(result)
        assert "Available:" in text
        # 7 slots available but only 5 shown
        assert "4:00 PM" in text
        assert "8:00 PM" in text
        # 10:00 PM (22:00) should not appear (6th and 7th slots)
        assert "10:00 PM" not in text


# ── cancel_reservation ─────────────────────────────────────────────────────


class TestCancelReservation:
    async def test_success_by_restaurant_name(self, booking_mcp):
        mcp, db, _store, _auth = booking_mcp
        reservation = make_reservation(
            restaurant_name="Carbone",
            date="2099-12-31",
            time="19:00",
            platform_confirmation_id="RES-123",
        )
        await db.save_reservation(reservation)

        with patch("src.clients.resy.ResyClient") as mock_resy_cls:
            instance = AsyncMock()
            mock_resy_cls.return_value = instance
            instance.cancel.return_value = True

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "cancel_reservation",
                    {"restaurant_name": "Carbone"},
                )
        text = str(result)
        assert "Cancelled" in text
        assert "Carbone" in text

    async def test_success_by_confirmation_id(self, booking_mcp):
        mcp, db, _store, _auth = booking_mcp
        reservation = make_reservation(
            id="res-id-1",
            restaurant_name="Carbone",
            date="2099-12-31",
            time="19:00",
            platform_confirmation_id="RES-456",
        )
        await db.save_reservation(reservation)

        with patch("src.clients.resy.ResyClient") as mock_resy_cls:
            instance = AsyncMock()
            mock_resy_cls.return_value = instance
            instance.cancel.return_value = True

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "cancel_reservation",
                    {"confirmation_id": "res-id-1"},
                )
        text = str(result)
        assert "Cancelled" in text
        assert "Carbone" in text

    async def test_neither_provided(self, booking_mcp):
        mcp, _db, _store, _auth = booking_mcp
        async with Client(mcp) as client:
            result = await client.call_tool(
                "cancel_reservation",
                {},
            )
        text = str(result)
        assert "Provide either restaurant_name or confirmation_id" in text

    async def test_no_matching_reservation(self, booking_mcp):
        mcp, _db, _store, _auth = booking_mcp
        async with Client(mcp) as client:
            result = await client.call_tool(
                "cancel_reservation",
                {"restaurant_name": "Nonexistent"},
            )
        text = str(result)
        assert "No matching reservation found" in text

    async def test_no_matching_by_confirmation_id(self, booking_mcp):
        mcp, _db, _store, _auth = booking_mcp
        async with Client(mcp) as client:
            result = await client.call_tool(
                "cancel_reservation",
                {"confirmation_id": "does-not-exist"},
            )
        text = str(result)
        assert "No matching reservation found" in text

    async def test_auth_fails(self, booking_mcp):
        from src.clients.resy_auth import AuthError

        mcp, db, _store, mock_auth = booking_mcp
        reservation = make_reservation(
            restaurant_name="Carbone",
            date="2099-12-31",
            platform_confirmation_id="RES-789",
        )
        await db.save_reservation(reservation)
        mock_auth.ensure_valid_token.side_effect = AuthError("no token")

        async with Client(mcp) as client:
            result = await client.call_tool(
                "cancel_reservation",
                {"restaurant_name": "Carbone"},
            )
        text = str(result)
        assert "Resy auth error" in text

    async def test_resy_cancel_fails(self, booking_mcp):
        mcp, db, _store, _auth = booking_mcp
        reservation = make_reservation(
            restaurant_name="Carbone",
            date="2099-12-31",
            platform_confirmation_id="RES-FAIL",
        )
        await db.save_reservation(reservation)

        with patch("src.clients.resy.ResyClient") as mock_resy_cls:
            instance = AsyncMock()
            mock_resy_cls.return_value = instance
            instance.cancel.return_value = False

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "cancel_reservation",
                    {"restaurant_name": "Carbone"},
                )
        text = str(result)
        assert "Failed to cancel" in text
        assert "Carbone" in text

    async def test_cancel_uses_platform_confirmation_id(self, booking_mcp):
        """The resy_token passed to cancel() should be platform_confirmation_id."""
        mcp, db, _store, _auth = booking_mcp
        reservation = make_reservation(
            id="local-id",
            restaurant_name="Carbone",
            date="2099-12-31",
            platform_confirmation_id="RES-TOKEN-ABC",
        )
        await db.save_reservation(reservation)

        with patch("src.clients.resy.ResyClient") as mock_resy_cls:
            instance = AsyncMock()
            mock_resy_cls.return_value = instance
            instance.cancel.return_value = True

            async with Client(mcp) as client:
                await client.call_tool(
                    "cancel_reservation",
                    {"restaurant_name": "Carbone"},
                )
            instance.cancel.assert_called_once_with("RES-TOKEN-ABC")

    async def test_cancel_falls_back_to_id_when_no_confirmation(self, booking_mcp):
        """When platform_confirmation_id is None, uses res.id."""
        mcp, db, _store, _auth = booking_mcp
        reservation = make_reservation(
            id="local-id-only",
            restaurant_name="Carbone",
            date="2099-12-31",
            platform_confirmation_id=None,
        )
        await db.save_reservation(reservation)

        with patch("src.clients.resy.ResyClient") as mock_resy_cls:
            instance = AsyncMock()
            mock_resy_cls.return_value = instance
            instance.cancel.return_value = True

            async with Client(mcp) as client:
                await client.call_tool(
                    "cancel_reservation",
                    {"restaurant_name": "Carbone"},
                )
            instance.cancel.assert_called_once_with("local-id-only")

    async def test_cancel_by_name_case_insensitive(self, booking_mcp):
        """Restaurant name matching should be case-insensitive."""
        mcp, db, _store, _auth = booking_mcp
        reservation = make_reservation(
            restaurant_name="Carbone",
            date="2099-12-31",
            platform_confirmation_id="RES-CI",
        )
        await db.save_reservation(reservation)

        with patch("src.clients.resy.ResyClient") as mock_resy_cls:
            instance = AsyncMock()
            mock_resy_cls.return_value = instance
            instance.cancel.return_value = True

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "cancel_reservation",
                    {"restaurant_name": "carbone"},
                )
        text = str(result)
        assert "Cancelled" in text


# ── my_reservations ────────────────────────────────────────────────────────


class TestMyReservations:
    async def test_no_reservations(self, booking_mcp):
        mcp, _db, _store, _auth = booking_mcp
        async with Client(mcp) as client:
            result = await client.call_tool("my_reservations", {})
        text = str(result)
        assert "No upcoming reservations" in text

    async def test_with_reservations(self, booking_mcp):
        mcp, db, _store, _auth = booking_mcp
        res = make_reservation(
            restaurant_name="Carbone",
            date="2099-12-31",
            time="19:00",
            party_size=4,
            platform_confirmation_id="RES-100",
        )
        await db.save_reservation(res)

        async with Client(mcp) as client:
            result = await client.call_tool("my_reservations", {})
        text = str(result)
        assert "Your upcoming reservations" in text
        assert "Carbone" in text
        assert "7:00 PM" in text
        assert "party of 4" in text
        assert "resy" in text
        assert "Confirmation: RES-100" in text

    async def test_reservation_with_confirmation_id(self, booking_mcp):
        mcp, db, _store, _auth = booking_mcp
        res = make_reservation(
            restaurant_name="Le Coucou",
            date="2099-06-15",
            time="20:00",
            party_size=2,
            platform_confirmation_id="RESY-XYZ",
        )
        await db.save_reservation(res)

        async with Client(mcp) as client:
            result = await client.call_tool("my_reservations", {})
        text = str(result)
        assert "Confirmation: RESY-XYZ" in text

    async def test_reservation_without_confirmation_id(self, booking_mcp):
        mcp, db, _store, _auth = booking_mcp
        res = make_reservation(
            restaurant_name="Little Owl",
            date="2099-03-01",
            time="18:30",
            party_size=2,
            platform_confirmation_id=None,
        )
        await db.save_reservation(res)

        async with Client(mcp) as client:
            result = await client.call_tool("my_reservations", {})
        text = str(result)
        assert "Little Owl" in text
        assert "6:30 PM" in text
        assert "Confirmation" not in text

    async def test_multiple_reservations(self, booking_mcp):
        mcp, db, _store, _auth = booking_mcp
        res1 = make_reservation(
            restaurant_name="Carbone",
            date="2099-06-01",
            time="19:00",
            party_size=2,
            platform_confirmation_id="R1",
        )
        res2 = make_reservation(
            restaurant_name="Le Coucou",
            date="2099-07-01",
            time="20:00",
            party_size=4,
            platform_confirmation_id="R2",
        )
        await db.save_reservation(res1)
        await db.save_reservation(res2)

        async with Client(mcp) as client:
            result = await client.call_tool("my_reservations", {})
        text = str(result)
        assert "Carbone" in text
        assert "Le Coucou" in text
        assert "R1" in text
        assert "R2" in text


# ── _get_credential_store / _get_auth_manager ──────────────────────────────


class TestHelperFactories:
    def test_get_credential_store_returns_store(self, tmp_path):
        """_get_credential_store builds a CredentialStore from settings."""
        mock_settings = MagicMock()
        mock_settings.credentials_path = tmp_path / ".credentials"
        with patch("src.config.get_settings", return_value=mock_settings):
            store = _get_credential_store()
        from src.storage.credentials import CredentialStore

        assert isinstance(store, CredentialStore)

    def test_get_auth_manager_returns_manager(self, tmp_path):
        """_get_auth_manager builds a ResyAuthManager backed by the store."""
        mock_settings = MagicMock()
        mock_settings.credentials_path = tmp_path / ".credentials"
        with patch("src.config.get_settings", return_value=mock_settings):
            manager = _get_auth_manager()
        from src.clients.resy_auth import ResyAuthManager

        assert isinstance(manager, ResyAuthManager)


# ── cancel_reservation: for-loop iteration branch ─────────────────────────


class TestCancelReservationLoopBranch:
    async def test_cancel_skips_non_matching_reservations(self, booking_mcp):
        """When multiple reservations exist, the loop skips non-matching ones."""
        mcp, db, _store, _auth = booking_mcp
        # First reservation: does NOT match the search name
        res_other = make_reservation(
            restaurant_name="Le Coucou",
            date="2099-12-31",
            time="18:00",
            platform_confirmation_id="RES-OTHER",
        )
        # Second reservation: matches
        res_target = make_reservation(
            restaurant_name="Carbone",
            date="2099-12-31",
            time="19:00",
            platform_confirmation_id="RES-TARGET",
        )
        await db.save_reservation(res_other)
        await db.save_reservation(res_target)

        with patch("src.clients.resy.ResyClient") as mock_resy_cls:
            instance = AsyncMock()
            mock_resy_cls.return_value = instance
            instance.cancel.return_value = True

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "cancel_reservation",
                    {"restaurant_name": "Carbone"},
                )
            # Should cancel Carbone, not Le Coucou
            instance.cancel.assert_called_once_with("RES-TARGET")
        text = str(result)
        assert "Cancelled" in text
        assert "Carbone" in text
