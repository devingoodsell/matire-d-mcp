from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.models.enums import BookingPlatform
from src.models.restaurant import AvailabilityResult, Restaurant, TimeSlot
from tests.factories import make_availability_result, make_restaurant, make_time_slot


class TestRestaurant:
    def test_minimal_fields(self):
        r = Restaurant(
            id="abc",
            name="Nom",
            address="1 Main St",
            lat=40.0,
            lng=-74.0,
        )
        assert r.id == "abc"
        assert r.name == "Nom"
        assert r.address == "1 Main St"
        assert r.lat == 40.0
        assert r.lng == -74.0

    def test_optional_defaults(self):
        r = Restaurant(
            id="abc",
            name="Nom",
            address="1 Main St",
            lat=40.0,
            lng=-74.0,
        )
        assert r.cuisine == []
        assert r.price_level is None
        assert r.rating is None
        assert r.review_count is None
        assert r.phone is None
        assert r.website is None
        assert r.hours is None
        assert r.resy_venue_id is None
        assert r.opentable_id is None
        assert r.cached_at is None

    def test_all_fields_populated(self):
        now = datetime.now(tz=UTC)
        r = make_restaurant(
            phone="555-1234",
            website="https://nom.com",
            hours={"mon": "9-5"},
            resy_venue_id="rv1",
            opentable_id="ot1",
            review_count=200,
            cached_at=now,
        )
        assert r.phone == "555-1234"
        assert r.website == "https://nom.com"
        assert r.hours == {"mon": "9-5"}
        assert r.resy_venue_id == "rv1"
        assert r.opentable_id == "ot1"
        assert r.review_count == 200
        assert r.cached_at == now

    def test_factory_defaults(self):
        r = make_restaurant()
        assert r.id.startswith("place_")
        assert r.name == "Test Restaurant"
        assert r.cuisine == ["italian"]
        assert r.price_level == 3
        assert r.rating == 4.5

    def test_factory_overrides(self):
        r = make_restaurant(name="Pizza Place", cuisine=["pizza"], rating=3.8)
        assert r.name == "Pizza Place"
        assert r.cuisine == ["pizza"]
        assert r.rating == 3.8

    def test_from_attributes_config(self):
        assert Restaurant.model_config["from_attributes"] is True

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            Restaurant(name="Nom", address="1 Main St", lat=40.0, lng=-74.0)


class TestTimeSlot:
    def test_required_fields(self):
        ts = TimeSlot(time="19:00", platform=BookingPlatform.RESY)
        assert ts.time == "19:00"
        assert ts.platform is BookingPlatform.RESY

    def test_optional_defaults(self):
        ts = TimeSlot(time="19:00", platform=BookingPlatform.RESY)
        assert ts.type is None
        assert ts.config_id is None

    def test_all_fields(self):
        ts = TimeSlot(
            time="20:30",
            type="dining_room",
            platform=BookingPlatform.OPENTABLE,
            config_id="cfg_1",
        )
        assert ts.type == "dining_room"
        assert ts.config_id == "cfg_1"
        assert ts.platform is BookingPlatform.OPENTABLE

    def test_factory(self):
        ts = make_time_slot()
        assert ts.time == "19:00"
        assert ts.platform is BookingPlatform.RESY

    def test_factory_overrides(self):
        ts = make_time_slot(time="21:00", type="bar", config_id="cfg_x")
        assert ts.time == "21:00"
        assert ts.type == "bar"
        assert ts.config_id == "cfg_x"

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            TimeSlot(time="19:00")


class TestAvailabilityResult:
    def test_all_required_fields(self):
        now = datetime.now(tz=UTC)
        ar = AvailabilityResult(
            restaurant_id="r1",
            restaurant_name="Nom",
            date="2026-02-14",
            slots=[],
            platform=BookingPlatform.RESY,
            checked_at=now,
        )
        assert ar.restaurant_id == "r1"
        assert ar.restaurant_name == "Nom"
        assert ar.date == "2026-02-14"
        assert ar.slots == []
        assert ar.platform is BookingPlatform.RESY
        assert ar.checked_at == now

    def test_checked_at_is_datetime(self):
        ar = make_availability_result()
        assert isinstance(ar.checked_at, datetime)

    def test_with_slots(self):
        slot = make_time_slot(time="18:00")
        ar = make_availability_result(slots=[slot])
        assert len(ar.slots) == 1
        assert ar.slots[0].time == "18:00"

    def test_factory_defaults(self):
        ar = make_availability_result()
        assert ar.restaurant_id.startswith("place_")
        assert ar.restaurant_name == "Test Restaurant"
        assert ar.date == "2026-02-14"
        assert ar.platform is BookingPlatform.RESY

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            AvailabilityResult(
                restaurant_id="r1",
                restaurant_name="Nom",
                date="2026-02-14",
                slots=[],
                platform=BookingPlatform.RESY,
            )
