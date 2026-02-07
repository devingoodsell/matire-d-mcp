"""Tests for src.tools.booking — credentials, availability, reservations (Resy + OpenTable)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import Client, FastMCP

from src.models.enums import BookingPlatform
from src.models.restaurant import TimeSlot
from src.storage.database import DatabaseManager
from src.tools.booking import (
    _book_via_resy,
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

    # Default credential store — Resy creds present
    mock_cred_store = MagicMock()
    mock_cred_store.get_credentials.return_value = {
        "api_key": "test-api-key",
        "auth_token": "test-token",
        "email": "test@test.com",
        "password": "pass",
    }
    mock_cred_store.save_credentials = MagicMock()
    mock_store_fn.return_value = mock_cred_store

    # Default auth manager
    mock_auth = AsyncMock()
    mock_auth.ensure_valid_token = AsyncMock(return_value="valid-token")
    mock_auth.authenticate = AsyncMock(return_value={
        "auth_token": "tok",
        "api_key": "key",
        "payment_methods": [],
    })
    mock_auth_fn.return_value = mock_auth

    register_booking_tools(test_mcp)

    yield test_mcp, db, mock_cred_store, mock_auth

    db_patch.stop()
    store_patch.stop()
    auth_patch.stop()


def _make_slot(
    time: str = "19:00",
    slot_type: str | None = None,
    config_id: str = "cfg1",
    platform: BookingPlatform = BookingPlatform.RESY,
):
    """Build a TimeSlot for tests."""
    return TimeSlot(
        time=time,
        type=slot_type,
        platform=platform,
        config_id=config_id,
    )


def _make_ot_slot(
    time: str = "19:00",
    slot_type: str | None = None,
    config_id: str = "ot-cfg",
):
    """Build an OpenTable TimeSlot for tests."""
    return _make_slot(time=time, slot_type=slot_type, config_id=config_id,
                      platform=BookingPlatform.OPENTABLE)


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


# ── store_opentable_credentials ────────────────────────────────────────────


class TestStoreOpenTableCredentials:
    async def test_success_login_works(self, booking_mcp):
        mcp, _db, mock_cred_store, _auth = booking_mcp

        mock_ot_client = AsyncMock()
        mock_ot_client._login = AsyncMock()
        mock_ot_client.close = AsyncMock()

        with patch(
            "src.clients.opentable.OpenTableClient",
            return_value=mock_ot_client,
        ):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "store_opentable_credentials",
                    {"email": "user@ot.com", "password": "secret"},
                )
        text = str(result)
        assert "OpenTable credentials saved and verified" in text
        mock_cred_store.save_credentials.assert_called_once_with(
            "opentable", {"email": "user@ot.com", "password": "secret"},
        )
        mock_ot_client.close.assert_awaited_once()

    async def test_login_fails_auth_error(self, booking_mcp):
        from src.clients.resy_auth import AuthError

        mcp, _db, mock_cred_store, _auth = booking_mcp

        mock_ot_client = AsyncMock()
        mock_ot_client._login = AsyncMock(side_effect=AuthError("bad ot creds"))
        mock_ot_client.close = AsyncMock()

        with patch(
            "src.clients.opentable.OpenTableClient",
            return_value=mock_ot_client,
        ):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "store_opentable_credentials",
                    {"email": "user@ot.com", "password": "wrong"},
                )
        text = str(result)
        assert "Credentials saved but login verification failed" in text
        assert "bad ot creds" in text
        # Credentials still saved before the login attempt
        mock_cred_store.save_credentials.assert_called_once()
        # close() always called via finally
        mock_ot_client.close.assert_awaited_once()

    async def test_close_always_called_on_success(self, booking_mcp):
        """Verify close() is called in the finally block even on success."""
        mcp, _db, _store, _auth = booking_mcp

        mock_ot_client = AsyncMock()
        mock_ot_client._login = AsyncMock()
        mock_ot_client.close = AsyncMock()

        with patch(
            "src.clients.opentable.OpenTableClient",
            return_value=mock_ot_client,
        ):
            async with Client(mcp) as client:
                await client.call_tool(
                    "store_opentable_credentials",
                    {"email": "u@ot.com", "password": "p"},
                )
        mock_ot_client.close.assert_awaited_once()


# ── check_availability ─────────────────────────────────────────────────────


class TestCheckAvailability:
    async def test_date_parse_error(self, booking_mcp):
        mcp, db, _store, _auth = booking_mcp
        restaurant = make_restaurant(name="Carbone")
        await db.cache_restaurant(restaurant)

        with patch("src.tools.date_utils.parse_date", side_effect=ValueError("bad")):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "check_availability",
                    {"restaurant_name": "Carbone", "date": "gibberish-date"},
                )
        text = str(result)
        assert "Could not parse date" in text

    async def test_restaurant_not_in_cache(self, booking_mcp):
        mcp, _db, _store, _auth = booking_mcp
        async with Client(mcp) as client:
            result = await client.call_tool(
                "check_availability",
                {"restaurant_name": "Unknown Place", "date": "2026-02-14"},
            )
        text = str(result)
        assert "not found in cache" in text
        assert "search_restaurants" in text

    async def test_resy_only_slots_no_opentable(self, booking_mcp):
        """Resy returns slots, OpenTable matcher returns no slug."""
        mcp, db, _store, _auth = booking_mcp
        restaurant = make_restaurant(
            name="Carbone", resy_venue_id="rv1", opentable_id=None,
        )
        await db.cache_restaurant(restaurant)

        with (
            patch("src.clients.resy.ResyClient") as mock_resy_cls,
            patch("src.matching.venue_matcher.VenueMatcher") as mock_matcher_cls,
        ):
            resy_inst = AsyncMock()
            mock_resy_cls.return_value = resy_inst
            resy_inst.find_availability.return_value = [
                _make_slot("18:00", "Dining Room"),
                _make_slot("19:00", "Patio"),
            ]
            matcher_inst = AsyncMock()
            mock_matcher_cls.return_value = matcher_inst
            matcher_inst.find_opentable_slug.return_value = None

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "check_availability",
                    {"restaurant_name": "Carbone", "date": "2026-02-14", "party_size": 2},
                )
        text = str(result)
        assert "Carbone" in text
        assert "6:00 PM - Dining Room" in text
        assert "7:00 PM - Patio" in text
        assert "Resy" in text

    async def test_opentable_only_slots_no_resy_creds(self, booking_mcp):
        """No Resy creds at all — skip Resy, OpenTable returns slots."""
        mcp, db, mock_cred_store, _auth = booking_mcp
        # No resy creds
        mock_cred_store.get_credentials.return_value = None
        restaurant = make_restaurant(
            name="Carbone", resy_venue_id=None, opentable_id="carbone-nyc",
        )
        await db.cache_restaurant(restaurant)

        mock_ot_client = AsyncMock()
        mock_ot_client.find_availability.return_value = [
            _make_ot_slot("20:00", "Main Room"),
        ]
        mock_ot_client.close = AsyncMock()

        with patch(
            "src.clients.opentable.OpenTableClient",
            return_value=mock_ot_client,
        ):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "check_availability",
                    {"restaurant_name": "Carbone", "date": "2026-02-14", "party_size": 2},
                )
        text = str(result)
        assert "8:00 PM - Main Room" in text
        assert "Opentable" in text
        mock_ot_client.close.assert_awaited_once()

    async def test_both_resy_and_opentable_slots_combined(self, booking_mcp):
        """Both platforms return slots — all are combined."""
        mcp, db, _store, _auth = booking_mcp
        restaurant = make_restaurant(
            name="Carbone", resy_venue_id="rv1", opentable_id="carbone-nyc",
        )
        await db.cache_restaurant(restaurant)

        mock_ot_client = AsyncMock()
        mock_ot_client.find_availability.return_value = [
            _make_ot_slot("20:30"),
        ]
        mock_ot_client.close = AsyncMock()

        with (
            patch("src.clients.resy.ResyClient") as mock_resy_cls,
            patch(
                "src.clients.opentable.OpenTableClient",
                return_value=mock_ot_client,
            ),
        ):
            resy_inst = AsyncMock()
            mock_resy_cls.return_value = resy_inst
            resy_inst.find_availability.return_value = [
                _make_slot("19:00"),
            ]

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "check_availability",
                    {"restaurant_name": "Carbone", "date": "2026-02-14", "party_size": 2},
                )
        text = str(result)
        assert "7:00 PM" in text
        assert "8:30 PM" in text
        assert "Resy" in text
        assert "Opentable" in text

    async def test_preferred_time_sorting(self, booking_mcp):
        mcp, db, _store, _auth = booking_mcp
        restaurant = make_restaurant(name="Carbone", resy_venue_id="rv1")
        await db.cache_restaurant(restaurant)

        with (
            patch("src.clients.resy.ResyClient") as mock_resy_cls,
            patch("src.matching.venue_matcher.VenueMatcher") as mock_matcher_cls,
        ):
            resy_inst = AsyncMock()
            mock_resy_cls.return_value = resy_inst
            resy_inst.find_availability.return_value = [
                _make_slot("17:00"),
                _make_slot("20:00"),
                _make_slot("19:00"),
            ]
            matcher_inst = AsyncMock()
            mock_matcher_cls.return_value = matcher_inst
            matcher_inst.find_opentable_slug.return_value = None

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
        slot_lines = [ln for ln in lines if "PM" in ln or "AM" in ln]
        assert "7:00 PM" in slot_lines[0]

    async def test_no_slots_from_either_platform(self, booking_mcp):
        """Both Resy and OpenTable return empty — 'No availability' message."""
        mcp, db, _store, _auth = booking_mcp
        restaurant = make_restaurant(
            name="Carbone", resy_venue_id="rv1", opentable_id="carbone-nyc",
        )
        await db.cache_restaurant(restaurant)

        mock_ot_client = AsyncMock()
        mock_ot_client.find_availability.return_value = []
        mock_ot_client.close = AsyncMock()

        with (
            patch("src.clients.resy.ResyClient") as mock_resy_cls,
            patch(
                "src.clients.opentable.OpenTableClient",
                return_value=mock_ot_client,
            ),
        ):
            resy_inst = AsyncMock()
            mock_resy_cls.return_value = resy_inst
            resy_inst.find_availability.return_value = []

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "check_availability",
                    {"restaurant_name": "Carbone", "date": "2026-02-14"},
                )
        text = str(result)
        assert "No availability" in text
        assert "Carbone" in text

    async def test_resy_auth_fails_still_checks_opentable(self, booking_mcp):
        """When Resy auth fails, OpenTable slots are still returned."""
        from src.clients.resy_auth import AuthError

        mcp, db, _store, mock_auth = booking_mcp
        mock_auth.ensure_valid_token.side_effect = AuthError("expired")
        restaurant = make_restaurant(
            name="Carbone", resy_venue_id="rv1", opentable_id="carbone-nyc",
        )
        await db.cache_restaurant(restaurant)

        mock_ot_client = AsyncMock()
        mock_ot_client.find_availability.return_value = [
            _make_ot_slot("20:00"),
        ]
        mock_ot_client.close = AsyncMock()

        with patch(
            "src.clients.opentable.OpenTableClient",
            return_value=mock_ot_client,
        ):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "check_availability",
                    {"restaurant_name": "Carbone", "date": "2026-02-14"},
                )
        text = str(result)
        assert "8:00 PM" in text
        assert "Opentable" in text

    async def test_restaurant_has_cached_resy_venue_id_skips_matcher(self, booking_mcp):
        """When resy_venue_id is already set, VenueMatcher is not used for Resy."""
        mcp, db, _store, _auth = booking_mcp
        restaurant = make_restaurant(name="Carbone", resy_venue_id="rv1")
        await db.cache_restaurant(restaurant)

        with (
            patch("src.clients.resy.ResyClient") as mock_resy_cls,
            patch("src.matching.venue_matcher.VenueMatcher") as mock_matcher_cls,
        ):
            resy_inst = AsyncMock()
            mock_resy_cls.return_value = resy_inst
            resy_inst.find_availability.return_value = [_make_slot("19:00")]
            matcher_inst = AsyncMock()
            mock_matcher_cls.return_value = matcher_inst
            matcher_inst.find_opentable_slug.return_value = None

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "check_availability",
                    {"restaurant_name": "Carbone", "date": "2026-02-14"},
                )
            # VenueMatcher is constructed for OpenTable but find_resy_venue not called
            matcher_inst.find_resy_venue.assert_not_called()
        text = str(result)
        assert "7:00 PM" in text

    async def test_restaurant_has_cached_opentable_id_skips_matcher(self, booking_mcp):
        """When opentable_id is set, VenueMatcher.find_opentable_slug is not called."""
        mcp, db, _store, _auth = booking_mcp
        restaurant = make_restaurant(
            name="Carbone", resy_venue_id="rv1", opentable_id="carbone-nyc",
        )
        await db.cache_restaurant(restaurant)

        mock_ot_client = AsyncMock()
        mock_ot_client.find_availability.return_value = [_make_ot_slot("20:00")]
        mock_ot_client.close = AsyncMock()

        with (
            patch("src.clients.resy.ResyClient") as mock_resy_cls,
            patch("src.matching.venue_matcher.VenueMatcher") as mock_matcher_cls,
            patch(
                "src.clients.opentable.OpenTableClient",
                return_value=mock_ot_client,
            ),
        ):
            resy_inst = AsyncMock()
            mock_resy_cls.return_value = resy_inst
            resy_inst.find_availability.return_value = [_make_slot("19:00")]
            matcher_inst = AsyncMock()
            mock_matcher_cls.return_value = matcher_inst

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "check_availability",
                    {"restaurant_name": "Carbone", "date": "2026-02-14"},
                )
            # Matcher should not be called for OpenTable since slug is cached
            matcher_inst.find_opentable_slug.assert_not_called()
        text = str(result)
        assert "7:00 PM" in text
        assert "8:00 PM" in text

    async def test_no_cached_opentable_id_uses_matcher(self, booking_mcp):
        """When opentable_id is None, VenueMatcher.find_opentable_slug is called."""
        mcp, db, _store, _auth = booking_mcp
        restaurant = make_restaurant(
            name="Carbone", resy_venue_id="rv1", opentable_id=None,
        )
        await db.cache_restaurant(restaurant)

        mock_ot_client = AsyncMock()
        mock_ot_client.find_availability.return_value = [_make_ot_slot("20:00")]
        mock_ot_client.close = AsyncMock()

        with (
            patch("src.clients.resy.ResyClient") as mock_resy_cls,
            patch("src.matching.venue_matcher.VenueMatcher") as mock_matcher_cls,
            patch(
                "src.clients.opentable.OpenTableClient",
                return_value=mock_ot_client,
            ),
        ):
            resy_inst = AsyncMock()
            mock_resy_cls.return_value = resy_inst
            resy_inst.find_availability.return_value = [_make_slot("19:00")]
            matcher_inst = AsyncMock()
            mock_matcher_cls.return_value = matcher_inst
            matcher_inst.find_opentable_slug.return_value = "carbone-nyc"

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "check_availability",
                    {"restaurant_name": "Carbone", "date": "2026-02-14"},
                )
            matcher_inst.find_opentable_slug.assert_called_once()
        text = str(result)
        assert "8:00 PM" in text

    async def test_no_resy_creds_skips_resy_entirely(self, booking_mcp):
        """When no Resy creds, Resy is skipped entirely — no ResyClient created."""
        mcp, db, mock_cred_store, _auth = booking_mcp
        mock_cred_store.get_credentials.return_value = None
        restaurant = make_restaurant(
            name="Carbone", resy_venue_id="rv1", opentable_id=None,
        )
        await db.cache_restaurant(restaurant)

        with (
            patch("src.clients.resy.ResyClient") as mock_resy_cls,
            patch("src.matching.venue_matcher.VenueMatcher") as mock_matcher_cls,
        ):
            matcher_inst = AsyncMock()
            mock_matcher_cls.return_value = matcher_inst
            matcher_inst.find_opentable_slug.return_value = None

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "check_availability",
                    {"restaurant_name": "Carbone", "date": "2026-02-14"},
                )
            mock_resy_cls.assert_not_called()
        text = str(result)
        assert "No availability" in text

    async def test_no_venue_id_found_by_resy_matcher_skips_resy_slots(self, booking_mcp):
        """When matcher returns None for resy venue, resy slots are skipped."""
        mcp, db, _store, _auth = booking_mcp
        restaurant = make_restaurant(
            name="Carbone", resy_venue_id=None, opentable_id=None,
        )
        await db.cache_restaurant(restaurant)

        with (
            patch("src.clients.resy.ResyClient") as mock_resy_cls,
            patch("src.matching.venue_matcher.VenueMatcher") as mock_matcher_cls,
        ):
            resy_inst = AsyncMock()
            mock_resy_cls.return_value = resy_inst
            matcher_inst = AsyncMock()
            mock_matcher_cls.return_value = matcher_inst
            matcher_inst.find_resy_venue.return_value = None
            matcher_inst.find_opentable_slug.return_value = None

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "check_availability",
                    {"restaurant_name": "Carbone", "date": "2026-02-14"},
                )
            resy_inst.find_availability.assert_not_called()
        text = str(result)
        assert "No availability" in text

    async def test_slot_without_type_no_dash_label(self, booking_mcp):
        """Slot with type=None should not display a type label."""
        mcp, db, _store, _auth = booking_mcp
        restaurant = make_restaurant(name="Carbone", resy_venue_id="rv1")
        await db.cache_restaurant(restaurant)

        with (
            patch("src.clients.resy.ResyClient") as mock_resy_cls,
            patch("src.matching.venue_matcher.VenueMatcher") as mock_matcher_cls,
        ):
            resy_inst = AsyncMock()
            mock_resy_cls.return_value = resy_inst
            resy_inst.find_availability.return_value = [
                _make_slot("19:00", slot_type=None),
            ]
            matcher_inst = AsyncMock()
            mock_matcher_cls.return_value = matcher_inst
            matcher_inst.find_opentable_slug.return_value = None

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "check_availability",
                    {"restaurant_name": "Carbone", "date": "2026-02-14"},
                )
        text = str(result)
        assert "7:00 PM (Resy)" in text
        assert "7:00 PM -" not in text


# ── make_reservation ───────────────────────────────────────────────────────


class TestMakeReservation:
    async def test_date_parse_error(self, booking_mcp):
        mcp, db, _store, _auth = booking_mcp
        restaurant = make_restaurant(name="Carbone")
        await db.cache_restaurant(restaurant)

        with patch("src.tools.date_utils.parse_date", side_effect=ValueError("bad")):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "make_reservation",
                    {"restaurant_name": "Carbone", "date": "gibberish", "time": "19:00"},
                )
        text = str(result)
        assert "Could not parse date" in text

    async def test_restaurant_not_found(self, booking_mcp):
        mcp, _db, _store, _auth = booking_mcp
        async with Client(mcp) as client:
            result = await client.call_tool(
                "make_reservation",
                {"restaurant_name": "Nonexistent", "date": "2026-02-14", "time": "19:00"},
            )
        text = str(result)
        assert "not found" in text
        assert "Search for it first" in text

    async def test_resy_booking_succeeds(self, booking_mcp):
        mcp, db, _store, _auth = booking_mcp
        restaurant = make_restaurant(name="Carbone", resy_venue_id="rv1")
        await db.cache_restaurant(restaurant)

        with (
            patch("src.clients.resy.ResyClient") as mock_resy_cls,
            patch("src.matching.venue_matcher.VenueMatcher") as mock_matcher_cls,
        ):
            resy_inst = AsyncMock()
            mock_resy_cls.return_value = resy_inst
            resy_inst.find_availability.return_value = [
                _make_slot("19:00", config_id="cfg-abc"),
            ]
            resy_inst.get_booking_details.return_value = {
                "book_token": {"value": "bt-xyz"},
            }
            resy_inst.book.return_value = {"resy_token": "RES-12345"}
            matcher_inst = AsyncMock()
            mock_matcher_cls.return_value = matcher_inst
            matcher_inst.find_opentable_slug.return_value = None

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

        upcoming = await db.get_upcoming_reservations()
        assert len(upcoming) == 1
        assert upcoming[0].restaurant_name == "Carbone"
        assert upcoming[0].platform_confirmation_id == "RES-12345"

    async def test_resy_booking_fails_falls_through_to_opentable(self, booking_mcp):
        """Resy _book_via_resy returns None — falls through to OpenTable."""
        mcp, db, _store, _auth = booking_mcp
        restaurant = make_restaurant(
            name="Carbone", resy_venue_id="rv1", opentable_id="carbone-nyc",
        )
        await db.cache_restaurant(restaurant)

        mock_ot_client = AsyncMock()
        mock_ot_client.book.return_value = {
            "confirmation_number": "OT-999",
        }
        mock_ot_client.close = AsyncMock()

        with (
            patch("src.clients.resy.ResyClient") as mock_resy_cls,
            patch(
                "src.clients.opentable.OpenTableClient",
                return_value=mock_ot_client,
            ),
        ):
            resy_inst = AsyncMock()
            mock_resy_cls.return_value = resy_inst
            # No matching slot for Resy -> _book_via_resy returns None
            resy_inst.find_availability.return_value = [
                _make_slot("18:00"),  # different time than requested
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
        assert "Booked!" in text
        assert "OT-999" in text
        assert "OpenTable" in text
        mock_ot_client.close.assert_awaited_once()

    async def test_opentable_booking_succeeds(self, booking_mcp):
        """When no Resy creds, OpenTable booking succeeds directly."""
        mcp, db, mock_cred_store, _auth = booking_mcp
        mock_cred_store.get_credentials.return_value = None
        restaurant = make_restaurant(
            name="Carbone", resy_venue_id=None, opentable_id="carbone-nyc",
        )
        await db.cache_restaurant(restaurant)

        mock_ot_client = AsyncMock()
        mock_ot_client.book.return_value = {
            "confirmation_number": "OT-555",
        }
        mock_ot_client.close = AsyncMock()

        with patch(
            "src.clients.opentable.OpenTableClient",
            return_value=mock_ot_client,
        ):
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
        assert "Booked!" in text
        assert "OT-555" in text
        assert "OpenTable" in text

        upcoming = await db.get_upcoming_reservations()
        assert len(upcoming) == 1
        assert upcoming[0].platform == BookingPlatform.OPENTABLE

    async def test_opentable_booking_error_falls_through_to_deep_links(self, booking_mcp):
        """OpenTable book returns error — falls through to deep link fallback."""
        mcp, db, mock_cred_store, _auth = booking_mcp
        mock_cred_store.get_credentials.return_value = None
        restaurant = make_restaurant(
            name="Carbone", resy_venue_id=None, opentable_id="carbone-nyc",
        )
        await db.cache_restaurant(restaurant)

        mock_ot_client = AsyncMock()
        mock_ot_client.book.return_value = {"error": "slot taken"}
        mock_ot_client.close = AsyncMock()

        with patch(
            "src.clients.opentable.OpenTableClient",
            return_value=mock_ot_client,
        ):
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
        assert "Could not complete booking automatically" in text
        assert "opentable.com" in text
        mock_ot_client.close.assert_awaited_once()

    async def test_deep_link_fallback_both_venue_id_and_ot_slug(self, booking_mcp):
        """Both venue_id and ot_slug exist — both deep links shown."""
        mcp, db, _store, _auth = booking_mcp
        restaurant = make_restaurant(
            name="Carbone", resy_venue_id="rv1", opentable_id="carbone-nyc",
        )
        await db.cache_restaurant(restaurant)

        mock_ot_client = AsyncMock()
        mock_ot_client.book.return_value = {"error": "unavailable"}
        mock_ot_client.close = AsyncMock()

        with (
            patch("src.clients.resy.ResyClient") as mock_resy_cls,
            patch(
                "src.clients.opentable.OpenTableClient",
                return_value=mock_ot_client,
            ),
        ):
            resy_inst = AsyncMock()
            mock_resy_cls.return_value = resy_inst
            # No matching slot for the requested time
            resy_inst.find_availability.return_value = []

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
        assert "Could not complete booking automatically" in text
        assert "resy.com" in text
        assert "opentable.com" in text

    async def test_deep_link_with_only_venue_id(self, booking_mcp):
        """Only Resy venue_id exists, no ot_slug — only Resy deep link."""
        mcp, db, _store, _auth = booking_mcp
        restaurant = make_restaurant(
            name="Carbone", resy_venue_id="rv1", opentable_id=None,
        )
        await db.cache_restaurant(restaurant)

        with (
            patch("src.clients.resy.ResyClient") as mock_resy_cls,
            patch("src.matching.venue_matcher.VenueMatcher") as mock_matcher_cls,
        ):
            resy_inst = AsyncMock()
            mock_resy_cls.return_value = resy_inst
            # No matching time slot
            resy_inst.find_availability.return_value = []
            matcher_inst = AsyncMock()
            mock_matcher_cls.return_value = matcher_inst
            matcher_inst.find_opentable_slug.return_value = None

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
        assert "Could not complete booking automatically" in text
        assert "resy.com" in text
        assert "opentable.com" not in text

    async def test_deep_link_with_only_ot_slug(self, booking_mcp):
        """Only ot_slug exists, no resy venue_id — only OpenTable deep link."""
        mcp, db, mock_cred_store, _auth = booking_mcp
        mock_cred_store.get_credentials.return_value = None
        restaurant = make_restaurant(
            name="Carbone", resy_venue_id=None, opentable_id="carbone-nyc",
        )
        await db.cache_restaurant(restaurant)

        mock_ot_client = AsyncMock()
        mock_ot_client.book.return_value = {"error": "fail"}
        mock_ot_client.close = AsyncMock()

        with patch(
            "src.clients.opentable.OpenTableClient",
            return_value=mock_ot_client,
        ):
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
        assert "Could not complete booking automatically" in text
        assert "opentable.com" in text
        assert "resy.com" not in text

    async def test_neither_platform_available(self, booking_mcp):
        """No venue_id and no ot_slug — 'doesn't appear to be on Resy or OpenTable'."""
        mcp, db, mock_cred_store, _auth = booking_mcp
        mock_cred_store.get_credentials.return_value = None
        restaurant = make_restaurant(
            name="Local Spot", resy_venue_id=None, opentable_id=None,
        )
        await db.cache_restaurant(restaurant)

        with patch("src.matching.venue_matcher.VenueMatcher") as mock_matcher_cls:
            matcher_inst = AsyncMock()
            mock_matcher_cls.return_value = matcher_inst
            matcher_inst.find_opentable_slug.return_value = None

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "make_reservation",
                    {
                        "restaurant_name": "Local Spot",
                        "date": "2026-02-14",
                        "time": "19:00",
                    },
                )
        text = str(result)
        assert "doesn't appear to be on Resy or OpenTable" in text

    async def test_resy_auth_fails_tries_opentable(self, booking_mcp):
        """Resy auth error is caught — tries OpenTable next."""
        from src.clients.resy_auth import AuthError

        mcp, db, _store, mock_auth = booking_mcp
        mock_auth.ensure_valid_token.side_effect = AuthError("expired")
        restaurant = make_restaurant(
            name="Carbone", resy_venue_id="rv1", opentable_id="carbone-nyc",
        )
        await db.cache_restaurant(restaurant)

        mock_ot_client = AsyncMock()
        mock_ot_client.book.return_value = {"confirmation_number": "OT-AUTH"}
        mock_ot_client.close = AsyncMock()

        with patch(
            "src.clients.opentable.OpenTableClient",
            return_value=mock_ot_client,
        ):
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
        assert "Booked!" in text
        assert "OT-AUTH" in text
        assert "OpenTable" in text

    async def test_no_resy_creds_tries_opentable_directly(self, booking_mcp):
        """When no Resy creds, jumps straight to OpenTable attempt."""
        mcp, db, mock_cred_store, _auth = booking_mcp
        mock_cred_store.get_credentials.return_value = None
        restaurant = make_restaurant(
            name="Carbone", resy_venue_id=None, opentable_id="carbone-nyc",
        )
        await db.cache_restaurant(restaurant)

        mock_ot_client = AsyncMock()
        mock_ot_client.book.return_value = {"confirmation_number": "OT-DIRECT"}
        mock_ot_client.close = AsyncMock()

        with (
            patch("src.clients.resy.ResyClient") as mock_resy_cls,
            patch(
                "src.clients.opentable.OpenTableClient",
                return_value=mock_ot_client,
            ),
        ):
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
            mock_resy_cls.assert_not_called()
        text = str(result)
        assert "Booked!" in text
        assert "OT-DIRECT" in text

    async def test_venue_matcher_used_when_no_resy_venue_id(self, booking_mcp):
        """When restaurant has no resy_venue_id, VenueMatcher is called."""
        mcp, db, _store, _auth = booking_mcp
        restaurant = make_restaurant(name="Carbone", resy_venue_id=None)
        await db.cache_restaurant(restaurant)

        with (
            patch("src.clients.resy.ResyClient") as mock_resy_cls,
            patch("src.matching.venue_matcher.VenueMatcher") as mock_matcher_cls,
        ):
            resy_inst = AsyncMock()
            mock_resy_cls.return_value = resy_inst
            matcher_inst = AsyncMock()
            mock_matcher_cls.return_value = matcher_inst
            matcher_inst.find_resy_venue.return_value = "found-venue-id"
            matcher_inst.find_opentable_slug.return_value = None
            resy_inst.find_availability.return_value = [_make_slot("19:00")]
            resy_inst.get_booking_details.return_value = {
                "book_token": {"value": "bt-xyz"},
            }
            resy_inst.book.return_value = {"resy_token": "RES-OK"}

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "make_reservation",
                    {
                        "restaurant_name": "Carbone",
                        "date": "2026-02-14",
                        "time": "19:00",
                    },
                )
            matcher_inst.find_resy_venue.assert_called_once()
        text = str(result)
        assert "Booked!" in text

    async def test_resy_venue_not_found_falls_through_to_opentable(self, booking_mcp):
        """Resy creds exist and auth passes, but matcher returns no venue_id.

        The ``if venue_id:`` check at make_reservation line 291 is False,
        so execution falls through directly to the OpenTable section.
        """
        mcp, db, _store, _auth = booking_mcp
        restaurant = make_restaurant(
            name="Carbone", resy_venue_id=None, opentable_id="carbone-nyc",
        )
        await db.cache_restaurant(restaurant)

        mock_ot_client = AsyncMock()
        mock_ot_client.book.return_value = {"confirmation_number": "OT-FALLTHRU"}
        mock_ot_client.close = AsyncMock()

        with (
            patch("src.clients.resy.ResyClient") as mock_resy_cls,
            patch("src.matching.venue_matcher.VenueMatcher") as mock_matcher_cls,
            patch(
                "src.clients.opentable.OpenTableClient",
                return_value=mock_ot_client,
            ),
        ):
            resy_inst = AsyncMock()
            mock_resy_cls.return_value = resy_inst
            matcher_inst = AsyncMock()
            mock_matcher_cls.return_value = matcher_inst
            # Resy matcher returns None — no venue found
            matcher_inst.find_resy_venue.return_value = None

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
            # Resy availability should NOT be checked since venue_id is None
            resy_inst.find_availability.assert_not_called()
        text = str(result)
        assert "Booked!" in text
        assert "OT-FALLTHRU" in text
        assert "OpenTable" in text


# ── _book_via_resy ─────────────────────────────────────────────────────────


class TestBookViaResy:
    async def test_no_matching_slot_returns_none(self, db):
        """When no slot matches the requested time, returns None."""
        resy_client = AsyncMock()
        resy_client.find_availability.return_value = [
            _make_slot("18:00"),
            _make_slot("20:00"),
        ]
        restaurant = make_restaurant(name="Carbone")

        result = await _book_via_resy(
            resy_client, db, restaurant, "rv1",
            "2026-02-14", "19:00", 2, None, {},
        )
        assert result is None

    async def test_no_book_token_returns_none(self, db):
        """When booking details have no book_token, returns None."""
        resy_client = AsyncMock()
        resy_client.find_availability.return_value = [_make_slot("19:00")]
        resy_client.get_booking_details.return_value = {}
        restaurant = make_restaurant(name="Carbone")

        result = await _book_via_resy(
            resy_client, db, restaurant, "rv1",
            "2026-02-14", "19:00", 2, None, {},
        )
        assert result is None

    async def test_empty_book_token_value_returns_none(self, db):
        """When book_token.value is empty, returns None."""
        resy_client = AsyncMock()
        resy_client.find_availability.return_value = [_make_slot("19:00")]
        resy_client.get_booking_details.return_value = {
            "book_token": {"value": ""},
        }
        restaurant = make_restaurant(name="Carbone")

        result = await _book_via_resy(
            resy_client, db, restaurant, "rv1",
            "2026-02-14", "19:00", 2, None, {},
        )
        assert result is None

    async def test_book_returns_error_returns_none(self, db):
        """When book() returns an error dict, returns None."""
        resy_client = AsyncMock()
        resy_client.find_availability.return_value = [_make_slot("19:00")]
        resy_client.get_booking_details.return_value = {
            "book_token": {"value": "bt-xyz"},
        }
        resy_client.book.return_value = {"error": "Card declined"}
        restaurant = make_restaurant(name="Carbone")

        result = await _book_via_resy(
            resy_client, db, restaurant, "rv1",
            "2026-02-14", "19:00", 2, None, {},
        )
        assert result is None

    async def test_success_with_str_payment_wraps_in_dict(self, db):
        """When payment_methods is a string, it should be wrapped as {'id': ...}."""
        resy_client = AsyncMock()
        resy_client.find_availability.return_value = [_make_slot("19:00")]
        resy_client.get_booking_details.return_value = {
            "book_token": {"value": "bt-xyz"},
        }
        resy_client.book.return_value = {"resy_token": "RES-PAY"}
        restaurant = make_restaurant(name="Carbone")

        creds = {"payment_methods": "pm-string-id"}
        result = await _book_via_resy(
            resy_client, db, restaurant, "rv1",
            "2026-02-14", "19:00", 2, None, creds,
        )
        assert result is not None
        assert "Booked!" in result
        assert "RES-PAY" in result
        resy_client.book.assert_called_once_with(
            book_token="bt-xyz",
            payment_method={"id": "pm-string-id"},
        )

    async def test_success_with_int_payment_wraps_in_dict(self, db):
        """When payment_methods is an int, it should be wrapped as {'id': ...}."""
        resy_client = AsyncMock()
        resy_client.find_availability.return_value = [_make_slot("19:00")]
        resy_client.get_booking_details.return_value = {
            "book_token": {"value": "bt-xyz"},
        }
        resy_client.book.return_value = {"resy_token": "RES-INT"}
        restaurant = make_restaurant(name="Carbone")

        creds = {"payment_methods": 12345}
        result = await _book_via_resy(
            resy_client, db, restaurant, "rv1",
            "2026-02-14", "19:00", 2, None, creds,
        )
        assert result is not None
        resy_client.book.assert_called_once_with(
            book_token="bt-xyz",
            payment_method={"id": 12345},
        )

    async def test_success_without_payment_none_payment_dict(self, db):
        """When no payment_methods key, payment_method is None."""
        resy_client = AsyncMock()
        resy_client.find_availability.return_value = [_make_slot("19:00")]
        resy_client.get_booking_details.return_value = {
            "book_token": {"value": "bt-xyz"},
        }
        resy_client.book.return_value = {"resy_token": "RES-NP"}
        restaurant = make_restaurant(name="Carbone")

        result = await _book_via_resy(
            resy_client, db, restaurant, "rv1",
            "2026-02-14", "19:00", 2, "birthday", {},
        )
        assert result is not None
        assert "Booked!" in result
        resy_client.book.assert_called_once_with(
            book_token="bt-xyz",
            payment_method=None,
        )

    async def test_success_payment_list_passes_none(self, db):
        """When payment_methods is a list, isinstance check fails -> None."""
        resy_client = AsyncMock()
        resy_client.find_availability.return_value = [_make_slot("19:00")]
        resy_client.get_booking_details.return_value = {
            "book_token": {"value": "bt-xyz"},
        }
        resy_client.book.return_value = {"resy_token": "RES-LIST"}
        restaurant = make_restaurant(name="Carbone")

        creds = {"payment_methods": [{"id": 1}]}
        result = await _book_via_resy(
            resy_client, db, restaurant, "rv1",
            "2026-02-14", "19:00", 2, None, creds,
        )
        assert result is not None
        resy_client.book.assert_called_once_with(
            book_token="bt-xyz",
            payment_method=None,
        )

    async def test_reservation_id_fallback(self, db):
        """When resy_token absent, reservation_id is used."""
        resy_client = AsyncMock()
        resy_client.find_availability.return_value = [_make_slot("19:00")]
        resy_client.get_booking_details.return_value = {
            "book_token": {"value": "bt-xyz"},
        }
        resy_client.book.return_value = {"reservation_id": "fallback-id"}
        restaurant = make_restaurant(name="Carbone")

        result = await _book_via_resy(
            resy_client, db, restaurant, "rv1",
            "2026-02-14", "19:00", 2, None, {},
        )
        assert result is not None
        assert "fallback-id" in result

    async def test_saves_reservation_to_db(self, db):
        """Successful booking saves reservation to the database."""
        resy_client = AsyncMock()
        resy_client.find_availability.return_value = [_make_slot("19:00")]
        resy_client.get_booking_details.return_value = {
            "book_token": {"value": "bt-xyz"},
        }
        resy_client.book.return_value = {"resy_token": "RES-SAVE"}
        restaurant = make_restaurant(name="Carbone")

        result = await _book_via_resy(
            resy_client, db, restaurant, "rv1",
            "2026-02-14", "19:00", 2, "quiet table", {},
        )
        assert result is not None

        upcoming = await db.get_upcoming_reservations()
        assert len(upcoming) == 1
        assert upcoming[0].platform == BookingPlatform.RESY
        assert upcoming[0].platform_confirmation_id == "RES-SAVE"
        assert upcoming[0].special_requests == "quiet table"

    async def test_config_id_none_uses_empty_string(self, db):
        """When slot.config_id is None, empty string is passed to get_booking_details."""
        resy_client = AsyncMock()
        slot = TimeSlot(
            time="19:00", platform=BookingPlatform.RESY, config_id=None,
        )
        resy_client.find_availability.return_value = [slot]
        resy_client.get_booking_details.return_value = {
            "book_token": {"value": "bt-xyz"},
        }
        resy_client.book.return_value = {"resy_token": "RES-CFG"}
        restaurant = make_restaurant(name="Carbone")

        await _book_via_resy(
            resy_client, db, restaurant, "rv1",
            "2026-02-14", "19:00", 2, None, {},
        )
        resy_client.get_booking_details.assert_called_once_with(
            config_id="",
            date="2026-02-14",
            party_size=2,
        )


# ── cancel_reservation ─────────────────────────────────────────────────────


class TestCancelReservation:
    async def test_neither_name_nor_id_provided(self, booking_mcp):
        mcp, _db, _store, _auth = booking_mcp
        async with Client(mcp) as client:
            result = await client.call_tool("cancel_reservation", {})
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

    async def test_cancel_opentable_reservation_success(self, booking_mcp):
        """Cancel an OpenTable reservation — routes to OpenTable client."""
        mcp, db, _store, _auth = booking_mcp
        reservation = make_reservation(
            restaurant_name="Carbone",
            date="2099-12-31",
            time="19:00",
            platform=BookingPlatform.OPENTABLE,
            platform_confirmation_id="OT-CANCEL-123",
        )
        await db.save_reservation(reservation)

        mock_ot_client = AsyncMock()
        mock_ot_client.cancel.return_value = True
        mock_ot_client.close = AsyncMock()

        with patch(
            "src.clients.opentable.OpenTableClient",
            return_value=mock_ot_client,
        ):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "cancel_reservation",
                    {"restaurant_name": "Carbone"},
                )
        text = str(result)
        assert "Cancelled" in text
        assert "Carbone" in text
        mock_ot_client.cancel.assert_called_once_with("OT-CANCEL-123")
        mock_ot_client.close.assert_awaited_once()

    async def test_cancel_opentable_fails(self, booking_mcp):
        """OpenTable cancel returns False — failure message."""
        mcp, db, _store, _auth = booking_mcp
        reservation = make_reservation(
            restaurant_name="Carbone",
            date="2099-12-31",
            time="19:00",
            platform=BookingPlatform.OPENTABLE,
            platform_confirmation_id="OT-FAIL",
        )
        await db.save_reservation(reservation)

        mock_ot_client = AsyncMock()
        mock_ot_client.cancel.return_value = False
        mock_ot_client.close = AsyncMock()

        with patch(
            "src.clients.opentable.OpenTableClient",
            return_value=mock_ot_client,
        ):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "cancel_reservation",
                    {"restaurant_name": "Carbone"},
                )
        text = str(result)
        assert "Failed to cancel OpenTable reservation" in text
        assert "Carbone" in text
        mock_ot_client.close.assert_awaited_once()

    async def test_cancel_opentable_uses_id_fallback(self, booking_mcp):
        """When platform_confirmation_id is None, uses res.id for OT cancel."""
        mcp, db, _store, _auth = booking_mcp
        reservation = make_reservation(
            id="ot-local-id",
            restaurant_name="Carbone",
            date="2099-12-31",
            time="19:00",
            platform=BookingPlatform.OPENTABLE,
            platform_confirmation_id=None,
        )
        await db.save_reservation(reservation)

        mock_ot_client = AsyncMock()
        mock_ot_client.cancel.return_value = True
        mock_ot_client.close = AsyncMock()

        with patch(
            "src.clients.opentable.OpenTableClient",
            return_value=mock_ot_client,
        ):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "cancel_reservation",
                    {"restaurant_name": "Carbone"},
                )
        text = str(result)
        assert "Cancelled" in text
        mock_ot_client.cancel.assert_called_once_with("ot-local-id")

    async def test_cancel_resy_reservation_success(self, booking_mcp):
        """Cancel a Resy reservation — default path."""
        mcp, db, _store, _auth = booking_mcp
        reservation = make_reservation(
            restaurant_name="Carbone",
            date="2099-12-31",
            time="19:00",
            platform=BookingPlatform.RESY,
            platform_confirmation_id="RES-CANCEL-456",
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
            instance.cancel.assert_called_once_with("RES-CANCEL-456")
        text = str(result)
        assert "Cancelled" in text
        assert "Carbone" in text

    async def test_cancel_resy_by_confirmation_id(self, booking_mcp):
        """Cancel a Resy reservation by confirmation_id lookup."""
        mcp, db, _store, _auth = booking_mcp
        reservation = make_reservation(
            id="res-id-1",
            restaurant_name="Carbone",
            date="2099-12-31",
            time="19:00",
            platform=BookingPlatform.RESY,
            platform_confirmation_id="RES-BY-ID",
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

    async def test_resy_auth_fails(self, booking_mcp):
        from src.clients.resy_auth import AuthError

        mcp, db, _store, mock_auth = booking_mcp
        reservation = make_reservation(
            restaurant_name="Carbone",
            date="2099-12-31",
            platform=BookingPlatform.RESY,
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
            platform=BookingPlatform.RESY,
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

    async def test_resy_cancel_succeeds_by_name(self, booking_mcp):
        mcp, db, _store, _auth = booking_mcp
        reservation = make_reservation(
            restaurant_name="Carbone",
            date="2099-12-31",
            time="19:00",
            platform=BookingPlatform.RESY,
            platform_confirmation_id="RES-SUCCESS",
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
        assert "Cancelled reservation at Carbone on 2099-12-31" in text

    async def test_cancel_falls_back_to_id_when_no_confirmation(self, booking_mcp):
        """When platform_confirmation_id is None, uses res.id for Resy."""
        mcp, db, _store, _auth = booking_mcp
        reservation = make_reservation(
            id="local-id-only",
            restaurant_name="Carbone",
            date="2099-12-31",
            platform=BookingPlatform.RESY,
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
            platform=BookingPlatform.RESY,
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

    async def test_cancel_skips_non_matching_reservations(self, booking_mcp):
        """When multiple reservations exist, the loop skips non-matching ones."""
        mcp, db, _store, _auth = booking_mcp
        res_other = make_reservation(
            restaurant_name="Le Coucou",
            date="2099-12-31",
            time="18:00",
            platform=BookingPlatform.RESY,
            platform_confirmation_id="RES-OTHER",
        )
        res_target = make_reservation(
            restaurant_name="Carbone",
            date="2099-12-31",
            time="19:00",
            platform=BookingPlatform.RESY,
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
            instance.cancel.assert_called_once_with("RES-TARGET")
        text = str(result)
        assert "Cancelled" in text
        assert "Carbone" in text


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
            platform=BookingPlatform.RESY,
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

    async def test_reservation_without_confirmation_id(self, booking_mcp):
        mcp, db, _store, _auth = booking_mcp
        res = make_reservation(
            restaurant_name="Little Owl",
            date="2099-03-01",
            time="18:30",
            party_size=2,
            platform=BookingPlatform.RESY,
            platform_confirmation_id=None,
        )
        await db.save_reservation(res)

        async with Client(mcp) as client:
            result = await client.call_tool("my_reservations", {})
        text = str(result)
        assert "Little Owl" in text
        assert "6:30 PM" in text
        assert "Confirmation" not in text

    async def test_opentable_reservation_displays_platform(self, booking_mcp):
        mcp, db, _store, _auth = booking_mcp
        res = make_reservation(
            restaurant_name="Carbone",
            date="2099-12-31",
            time="20:00",
            party_size=2,
            platform=BookingPlatform.OPENTABLE,
            platform_confirmation_id="OT-VIEW",
        )
        await db.save_reservation(res)

        async with Client(mcp) as client:
            result = await client.call_tool("my_reservations", {})
        text = str(result)
        assert "opentable" in text
        assert "Confirmation: OT-VIEW" in text

    async def test_multiple_reservations(self, booking_mcp):
        mcp, db, _store, _auth = booking_mcp
        res1 = make_reservation(
            restaurant_name="Carbone",
            date="2099-06-01",
            time="19:00",
            party_size=2,
            platform=BookingPlatform.RESY,
            platform_confirmation_id="R1",
        )
        res2 = make_reservation(
            restaurant_name="Le Coucou",
            date="2099-07-01",
            time="20:00",
            party_size=4,
            platform=BookingPlatform.OPENTABLE,
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
