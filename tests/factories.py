from uuid import uuid4

from src.models.enums import BookingPlatform, CuisineCategory, PriceLevel
from src.models.reservation import BookingResult, Reservation
from src.models.restaurant import AvailabilityResult, Restaurant, TimeSlot
from src.models.review import DishReview, Visit, VisitReview
from src.models.user import (
    CuisinePreference,
    Group,
    Location,
    Person,
    PricePreference,
    UserPreferences,
)


def make_restaurant(**overrides: object) -> Restaurant:
    defaults: dict = {
        "id": f"place_{uuid4().hex[:8]}",
        "name": "Test Restaurant",
        "address": "123 Test St, New York, NY 10001",
        "lat": 40.7128,
        "lng": -74.0060,
        "cuisine": ["italian"],
        "price_level": 3,
        "rating": 4.5,
    }
    defaults.update(overrides)
    return Restaurant(**defaults)


def make_person(**overrides: object) -> Person:
    defaults: dict = {
        "name": "Test Person",
        "dietary_restrictions": [],
        "no_alcohol": False,
    }
    defaults.update(overrides)
    return Person(**defaults)


def make_user_preferences(**overrides: object) -> UserPreferences:
    defaults: dict = {"name": "Test User"}
    defaults.update(overrides)
    return UserPreferences(**defaults)


def make_location(**overrides: object) -> Location:
    defaults: dict = {
        "name": "home",
        "address": "123 Test St, New York, NY 10001",
        "lat": 40.7128,
        "lng": -74.0060,
    }
    defaults.update(overrides)
    return Location(**defaults)


def make_visit(**overrides: object) -> Visit:
    defaults: dict = {
        "restaurant_id": f"place_{uuid4().hex[:8]}",
        "restaurant_name": "Test Restaurant",
        "date": "2026-02-14",
        "party_size": 2,
    }
    defaults.update(overrides)
    return Visit(**defaults)


def make_reservation(**overrides: object) -> Reservation:
    defaults: dict = {
        "restaurant_id": f"place_{uuid4().hex[:8]}",
        "restaurant_name": "Test Restaurant",
        "platform": BookingPlatform.RESY,
        "date": "2026-02-14",
        "time": "19:00",
        "party_size": 2,
    }
    defaults.update(overrides)
    return Reservation(**defaults)


def make_group(**overrides: object) -> Group:
    defaults: dict = {"name": "Test Group"}
    defaults.update(overrides)
    return Group(**defaults)


def make_cuisine_preference(**overrides: object) -> CuisinePreference:
    defaults: dict = {"cuisine": "italian", "category": CuisineCategory.FAVORITE}
    defaults.update(overrides)
    return CuisinePreference(**defaults)


def make_price_preference(**overrides: object) -> PricePreference:
    defaults: dict = {"price_level": PriceLevel.MODERATE, "acceptable": True}
    defaults.update(overrides)
    return PricePreference(**defaults)


def make_visit_review(**overrides: object) -> VisitReview:
    defaults: dict = {"visit_id": 1, "would_return": True}
    defaults.update(overrides)
    return VisitReview(**defaults)


def make_dish_review(**overrides: object) -> DishReview:
    defaults: dict = {
        "visit_id": 1,
        "dish_name": "Spicy Rigatoni",
        "rating": 5,
        "would_order_again": True,
    }
    defaults.update(overrides)
    return DishReview(**defaults)


def make_time_slot(**overrides: object) -> TimeSlot:
    defaults: dict = {
        "time": "19:00",
        "platform": BookingPlatform.RESY,
    }
    defaults.update(overrides)
    return TimeSlot(**defaults)


def make_booking_result(**overrides: object) -> BookingResult:
    defaults: dict = {
        "success": True,
        "message": "Reservation confirmed",
    }
    defaults.update(overrides)
    return BookingResult(**defaults)


def make_availability_result(**overrides: object) -> AvailabilityResult:
    from datetime import UTC, datetime

    defaults: dict = {
        "restaurant_id": f"place_{uuid4().hex[:8]}",
        "restaurant_name": "Test Restaurant",
        "date": "2026-02-14",
        "slots": [],
        "platform": BookingPlatform.RESY,
        "checked_at": datetime.now(tz=UTC),
    }
    defaults.update(overrides)
    return AvailabilityResult(**defaults)
