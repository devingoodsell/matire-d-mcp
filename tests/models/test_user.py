import pytest
from pydantic import ValidationError

from src.models.enums import Ambiance, CuisineCategory, PriceLevel, SeatingPreference
from src.models.user import (
    CuisinePreference,
    DietaryRestriction,
    Group,
    Location,
    Person,
    PricePreference,
    UserPreferences,
)
from tests.factories import (
    make_cuisine_preference,
    make_group,
    make_location,
    make_person,
    make_price_preference,
    make_user_preferences,
)


class TestUserPreferences:
    def test_defaults(self):
        prefs = UserPreferences(name="Alice")
        assert prefs.name == "Alice"
        assert prefs.rating_threshold == 4.0
        assert prefs.noise_preference is Ambiance.MODERATE
        assert prefs.seating_preference is SeatingPreference.NO_PREFERENCE
        assert prefs.max_walk_minutes == 15
        assert prefs.default_party_size == 2

    def test_custom_values(self):
        prefs = UserPreferences(
            name="Bob",
            rating_threshold=3.5,
            noise_preference=Ambiance.QUIET,
            seating_preference=SeatingPreference.OUTDOOR,
            max_walk_minutes=10,
            default_party_size=4,
        )
        assert prefs.rating_threshold == 3.5
        assert prefs.noise_preference is Ambiance.QUIET
        assert prefs.seating_preference is SeatingPreference.OUTDOOR
        assert prefs.max_walk_minutes == 10
        assert prefs.default_party_size == 4

    def test_factory(self):
        prefs = make_user_preferences()
        assert prefs.name == "Test User"
        assert prefs.rating_threshold == 4.0

    def test_factory_overrides(self):
        prefs = make_user_preferences(name="Custom", rating_threshold=3.0)
        assert prefs.name == "Custom"
        assert prefs.rating_threshold == 3.0

    def test_from_attributes_config(self):
        assert UserPreferences.model_config["from_attributes"] is True

    def test_missing_name_raises(self):
        with pytest.raises(ValidationError):
            UserPreferences()


class TestDietaryRestriction:
    def test_required_field(self):
        dr = DietaryRestriction(restriction="gluten-free")
        assert dr.restriction == "gluten-free"

    def test_from_attributes_config(self):
        assert DietaryRestriction.model_config["from_attributes"] is True

    def test_missing_restriction_raises(self):
        with pytest.raises(ValidationError):
            DietaryRestriction()


class TestCuisinePreference:
    def test_required_fields(self):
        cp = CuisinePreference(cuisine="thai", category=CuisineCategory.LIKE)
        assert cp.cuisine == "thai"
        assert cp.category is CuisineCategory.LIKE

    def test_factory(self):
        cp = make_cuisine_preference()
        assert cp.cuisine == "italian"
        assert cp.category is CuisineCategory.FAVORITE

    def test_factory_overrides(self):
        cp = make_cuisine_preference(cuisine="korean", category=CuisineCategory.NEUTRAL)
        assert cp.cuisine == "korean"
        assert cp.category is CuisineCategory.NEUTRAL

    def test_from_attributes_config(self):
        assert CuisinePreference.model_config["from_attributes"] is True

    def test_missing_field_raises(self):
        with pytest.raises(ValidationError):
            CuisinePreference(cuisine="thai")


class TestPricePreference:
    def test_required_and_default(self):
        pp = PricePreference(price_level=PriceLevel.UPSCALE)
        assert pp.price_level is PriceLevel.UPSCALE
        assert pp.acceptable is True

    def test_acceptable_false(self):
        pp = PricePreference(price_level=PriceLevel.FINE_DINING, acceptable=False)
        assert pp.acceptable is False

    def test_factory(self):
        pp = make_price_preference()
        assert pp.price_level is PriceLevel.MODERATE
        assert pp.acceptable is True

    def test_factory_overrides(self):
        pp = make_price_preference(price_level=PriceLevel.BUDGET, acceptable=False)
        assert pp.price_level is PriceLevel.BUDGET
        assert pp.acceptable is False

    def test_from_attributes_config(self):
        assert PricePreference.model_config["from_attributes"] is True

    def test_missing_price_level_raises(self):
        with pytest.raises(ValidationError):
            PricePreference()


class TestLocation:
    def test_required_fields_and_default(self):
        loc = Location(name="work", address="456 Elm St", lat=40.75, lng=-73.99)
        assert loc.name == "work"
        assert loc.address == "456 Elm St"
        assert loc.lat == 40.75
        assert loc.lng == -73.99
        assert loc.walk_radius_minutes == 15

    def test_custom_walk_radius(self):
        loc = Location(
            name="home", address="789 Oak St", lat=40.71, lng=-74.01, walk_radius_minutes=20
        )
        assert loc.walk_radius_minutes == 20

    def test_factory(self):
        loc = make_location()
        assert loc.name == "home"
        assert loc.walk_radius_minutes == 15

    def test_factory_overrides(self):
        loc = make_location(name="office", walk_radius_minutes=5)
        assert loc.name == "office"
        assert loc.walk_radius_minutes == 5

    def test_from_attributes_config(self):
        assert Location.model_config["from_attributes"] is True

    def test_missing_required_raises(self):
        with pytest.raises(ValidationError):
            Location(name="x")


class TestPerson:
    def test_defaults(self):
        p = Person(name="Jane")
        assert p.id is None
        assert p.name == "Jane"
        assert p.dietary_restrictions == []
        assert p.no_alcohol is False
        assert p.notes is None

    def test_all_fields(self):
        p = Person(
            id=7,
            name="Jane",
            dietary_restrictions=["vegan", "nut-free"],
            no_alcohol=True,
            notes="Prefers window seats",
        )
        assert p.id == 7
        assert p.dietary_restrictions == ["vegan", "nut-free"]
        assert p.no_alcohol is True
        assert p.notes == "Prefers window seats"

    def test_factory(self):
        p = make_person()
        assert p.name == "Test Person"
        assert p.dietary_restrictions == []
        assert p.no_alcohol is False

    def test_factory_overrides(self):
        p = make_person(name="Max", no_alcohol=True, id=5)
        assert p.name == "Max"
        assert p.no_alcohol is True
        assert p.id == 5

    def test_from_attributes_config(self):
        assert Person.model_config["from_attributes"] is True

    def test_missing_name_raises(self):
        with pytest.raises(ValidationError):
            Person()


class TestGroup:
    def test_defaults(self):
        g = Group(name="Crew")
        assert g.id is None
        assert g.name == "Crew"
        assert g.member_ids == []
        assert g.member_names == []

    def test_all_fields(self):
        g = Group(id=3, name="Crew", member_ids=[1, 2], member_names=["A", "B"])
        assert g.id == 3
        assert g.member_ids == [1, 2]
        assert g.member_names == ["A", "B"]

    def test_factory(self):
        g = make_group()
        assert g.name == "Test Group"
        assert g.member_ids == []
        assert g.member_names == []

    def test_factory_overrides(self):
        g = make_group(name="Squad", member_ids=[10], member_names=["Zara"])
        assert g.name == "Squad"
        assert g.member_ids == [10]
        assert g.member_names == ["Zara"]

    def test_from_attributes_config(self):
        assert Group.model_config["from_attributes"] is True

    def test_missing_name_raises(self):
        with pytest.raises(ValidationError):
            Group()
