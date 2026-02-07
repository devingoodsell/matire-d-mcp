import pytest
from pydantic import ValidationError

from src.models.enums import NoiseLevel
from src.models.review import DishReview, Visit, VisitReview
from tests.factories import make_dish_review, make_visit, make_visit_review


class TestVisit:
    def test_required_fields(self):
        v = Visit(
            restaurant_id="r1",
            restaurant_name="Nom",
            date="2026-02-14",
            party_size=2,
        )
        assert v.restaurant_id == "r1"
        assert v.restaurant_name == "Nom"
        assert v.date == "2026-02-14"
        assert v.party_size == 2

    def test_optional_defaults(self):
        v = Visit(
            restaurant_id="r1",
            restaurant_name="Nom",
            date="2026-02-14",
            party_size=2,
        )
        assert v.id is None
        assert v.companions == []
        assert v.source == "booked"

    def test_all_fields(self):
        v = Visit(
            id=42,
            restaurant_id="r1",
            restaurant_name="Nom",
            date="2026-02-14",
            party_size=3,
            companions=["Alice", "Bob"],
            source="walk-in",
        )
        assert v.id == 42
        assert v.companions == ["Alice", "Bob"]
        assert v.source == "walk-in"

    def test_factory_defaults(self):
        v = make_visit()
        assert v.restaurant_id.startswith("place_")
        assert v.restaurant_name == "Test Restaurant"
        assert v.date == "2026-02-14"
        assert v.party_size == 2
        assert v.companions == []
        assert v.source == "booked"

    def test_factory_overrides(self):
        v = make_visit(id=10, companions=["Eve"], source="invited")
        assert v.id == 10
        assert v.companions == ["Eve"]
        assert v.source == "invited"

    def test_from_attributes_config(self):
        assert Visit.model_config["from_attributes"] is True

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            Visit(restaurant_id="r1", restaurant_name="Nom", date="2026-02-14")


class TestVisitReview:
    def test_required_fields(self):
        vr = VisitReview(visit_id=1, would_return=True)
        assert vr.visit_id == 1
        assert vr.would_return is True

    def test_optional_defaults(self):
        vr = VisitReview(visit_id=1, would_return=False)
        assert vr.overall_rating is None
        assert vr.ambiance_rating is None
        assert vr.noise_level is None
        assert vr.notes is None

    def test_all_fields(self):
        vr = VisitReview(
            visit_id=5,
            would_return=True,
            overall_rating=9,
            ambiance_rating=8,
            noise_level=NoiseLevel.QUIET,
            notes="Fantastic meal",
        )
        assert vr.overall_rating == 9
        assert vr.ambiance_rating == 8
        assert vr.noise_level is NoiseLevel.QUIET
        assert vr.notes == "Fantastic meal"

    def test_would_return_false(self):
        vr = VisitReview(visit_id=1, would_return=False)
        assert vr.would_return is False

    def test_factory_defaults(self):
        vr = make_visit_review()
        assert vr.visit_id == 1
        assert vr.would_return is True
        assert vr.overall_rating is None

    def test_factory_overrides(self):
        vr = make_visit_review(
            visit_id=99,
            would_return=False,
            overall_rating=3,
            noise_level=NoiseLevel.LOUD,
            notes="Too noisy",
        )
        assert vr.visit_id == 99
        assert vr.would_return is False
        assert vr.overall_rating == 3
        assert vr.noise_level is NoiseLevel.LOUD
        assert vr.notes == "Too noisy"

    def test_from_attributes_config(self):
        assert VisitReview.model_config["from_attributes"] is True

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            VisitReview(visit_id=1)


class TestDishReview:
    def test_required_fields(self):
        dr = DishReview(
            visit_id=1,
            dish_name="Pasta",
            rating=5,
            would_order_again=True,
        )
        assert dr.visit_id == 1
        assert dr.dish_name == "Pasta"
        assert dr.rating == 5
        assert dr.would_order_again is True

    def test_optional_default(self):
        dr = DishReview(
            visit_id=1,
            dish_name="Pasta",
            rating=4,
            would_order_again=False,
        )
        assert dr.notes is None

    def test_with_notes(self):
        dr = DishReview(
            visit_id=1,
            dish_name="Risotto",
            rating=3,
            would_order_again=False,
            notes="Under-seasoned",
        )
        assert dr.notes == "Under-seasoned"

    def test_would_order_again_false(self):
        dr = DishReview(
            visit_id=1,
            dish_name="Salad",
            rating=2,
            would_order_again=False,
        )
        assert dr.would_order_again is False

    def test_factory_defaults(self):
        dr = make_dish_review()
        assert dr.visit_id == 1
        assert dr.dish_name == "Spicy Rigatoni"
        assert dr.rating == 5
        assert dr.would_order_again is True
        assert dr.notes is None

    def test_factory_overrides(self):
        dr = make_dish_review(
            dish_name="Tiramisu",
            rating=4,
            would_order_again=True,
            notes="Rich and creamy",
        )
        assert dr.dish_name == "Tiramisu"
        assert dr.rating == 4
        assert dr.notes == "Rich and creamy"

    def test_from_attributes_config(self):
        assert DishReview.model_config["from_attributes"] is True

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            DishReview(visit_id=1, dish_name="Pasta", rating=5)
