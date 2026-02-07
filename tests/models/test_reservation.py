from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.models.enums import BookingPlatform
from src.models.reservation import BookingResult, Reservation
from tests.factories import make_booking_result, make_reservation


class TestReservation:
    def test_required_fields(self):
        r = Reservation(
            restaurant_id="r1",
            restaurant_name="Nom",
            platform=BookingPlatform.RESY,
            date="2026-02-14",
            time="19:00",
            party_size=2,
        )
        assert r.restaurant_id == "r1"
        assert r.restaurant_name == "Nom"
        assert r.platform is BookingPlatform.RESY
        assert r.date == "2026-02-14"
        assert r.time == "19:00"
        assert r.party_size == 2

    def test_optional_defaults(self):
        r = Reservation(
            restaurant_id="r1",
            restaurant_name="Nom",
            platform=BookingPlatform.RESY,
            date="2026-02-14",
            time="19:00",
            party_size=2,
        )
        assert r.id is None
        assert r.platform_confirmation_id is None
        assert r.special_requests is None
        assert r.status == "confirmed"
        assert r.created_at is None
        assert r.cancelled_at is None

    def test_all_fields_populated(self):
        now = datetime.now(tz=UTC)
        r = Reservation(
            id="res_1",
            restaurant_id="r1",
            restaurant_name="Nom",
            platform=BookingPlatform.OPENTABLE,
            platform_confirmation_id="OT-12345",
            date="2026-02-14",
            time="20:00",
            party_size=4,
            special_requests="Window seat please",
            status="cancelled",
            created_at=now,
            cancelled_at=now,
        )
        assert r.id == "res_1"
        assert r.platform_confirmation_id == "OT-12345"
        assert r.special_requests == "Window seat please"
        assert r.status == "cancelled"
        assert r.created_at == now
        assert r.cancelled_at == now
        assert r.platform is BookingPlatform.OPENTABLE

    def test_factory_defaults(self):
        r = make_reservation()
        assert r.restaurant_id.startswith("place_")
        assert r.restaurant_name == "Test Restaurant"
        assert r.platform is BookingPlatform.RESY
        assert r.date == "2026-02-14"
        assert r.time == "19:00"
        assert r.party_size == 2

    def test_factory_overrides(self):
        r = make_reservation(
            id="custom_id",
            status="pending",
            special_requests="No onions",
        )
        assert r.id == "custom_id"
        assert r.status == "pending"
        assert r.special_requests == "No onions"

    def test_from_attributes_config(self):
        assert Reservation.model_config["from_attributes"] is True

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            Reservation(
                restaurant_id="r1",
                restaurant_name="Nom",
                platform=BookingPlatform.RESY,
                date="2026-02-14",
                time="19:00",
            )


class TestBookingResult:
    def test_success_with_reservation(self):
        res = make_reservation()
        br = BookingResult(
            success=True,
            reservation=res,
            message="Reservation confirmed",
        )
        assert br.success is True
        assert br.reservation is res
        assert br.error is None
        assert br.deep_link is None
        assert br.message == "Reservation confirmed"

    def test_failure_with_error(self):
        br = BookingResult(
            success=False,
            error="No availability",
            message="Could not complete booking",
        )
        assert br.success is False
        assert br.reservation is None
        assert br.error == "No availability"
        assert br.message == "Could not complete booking"

    def test_with_deep_link(self):
        br = BookingResult(
            success=True,
            deep_link="https://resy.com/booking/123",
            message="Booked via deep link",
        )
        assert br.deep_link == "https://resy.com/booking/123"

    def test_factory_defaults(self):
        br = make_booking_result()
        assert br.success is True
        assert br.message == "Reservation confirmed"
        assert br.reservation is None
        assert br.error is None
        assert br.deep_link is None

    def test_factory_overrides(self):
        br = make_booking_result(success=False, error="Timeout", message="Failed")
        assert br.success is False
        assert br.error == "Timeout"
        assert br.message == "Failed"

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            BookingResult(success=True)
