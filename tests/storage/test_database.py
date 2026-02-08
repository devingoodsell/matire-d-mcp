import json
from datetime import date

import pytest

from src.models.enums import (
    Ambiance,
    BookingPlatform,
    CuisineCategory,
    NoiseLevel,
    PriceLevel,
    SeatingPreference,
)
from src.storage.database import DatabaseManager
from tests.factories import (
    make_cuisine_preference,
    make_dish_review,
    make_group,
    make_location,
    make_person,
    make_price_preference,
    make_reservation,
    make_restaurant,
    make_user_preferences,
    make_visit,
    make_visit_review,
)


@pytest.fixture
async def db():
    manager = DatabaseManager(":memory:")
    await manager.initialize()
    yield manager
    await manager.close()


# ── Core Methods ─────────────────────────────────────────────────────────────


class TestCoreMethods:
    async def test_initialize_creates_tables(self, db: DatabaseManager):
        expected_tables = {
            "user_preferences",
            "user_dietary",
            "cuisine_preferences",
            "price_preferences",
            "locations",
            "people",
            "people_dietary",
            "groups",
            "group_members",
            "restaurant_cache",
            "visits",
            "visit_reviews",
            "dish_reviews",
            "reservations",
            "blacklist",
        }
        rows = await db.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        table_names = {r["name"] for r in rows}
        assert expected_tables.issubset(table_names)

    async def test_initialize_enables_wal_mode(self, db: DatabaseManager):
        row = await db.fetch_one("PRAGMA journal_mode")
        # In-memory databases use 'memory' journal mode; WAL is set for file DBs
        assert row["journal_mode"] in ("wal", "memory")

    async def test_initialize_enables_foreign_keys(self, db: DatabaseManager):
        row = await db.fetch_one("PRAGMA foreign_keys")
        assert row["foreign_keys"] == 1

    async def test_close_sets_connection_none(self, db: DatabaseManager):
        assert db.connection is not None
        await db.close()
        assert db.connection is None

    async def test_context_manager(self):
        async with DatabaseManager(":memory:") as manager:
            assert manager.connection is not None
            row = await manager.fetch_one("SELECT 1 AS val")
            assert row["val"] == 1
        assert manager.connection is None

    async def test_execute_and_fetch(self, db: DatabaseManager):
        await db.execute(
            "INSERT INTO user_preferences (id, name) VALUES (1, 'Alice')"
        )
        row = await db.fetch_one(
            "SELECT name FROM user_preferences WHERE id = 1"
        )
        assert row is not None
        assert row["name"] == "Alice"

    async def test_execute_many(self, db: DatabaseManager):
        await db.execute_many(
            "INSERT INTO user_dietary (restriction) VALUES (?)",
            [("vegan",), ("gluten-free",)],
        )
        rows = await db.fetch_all("SELECT restriction FROM user_dietary")
        assert len(rows) == 2
        restrictions = {r["restriction"] for r in rows}
        assert restrictions == {"vegan", "gluten-free"}

    async def test_fetch_one_returns_none(self, db: DatabaseManager):
        row = await db.fetch_one(
            "SELECT * FROM user_preferences WHERE id = 999"
        )
        assert row is None

    async def test_fetch_all_empty(self, db: DatabaseManager):
        rows = await db.fetch_all("SELECT * FROM user_preferences")
        assert rows == []


# ── User Preferences ─────────────────────────────────────────────────────────


class TestUserPreferences:
    async def test_get_preferences_none_when_empty(self, db: DatabaseManager):
        prefs = await db.get_preferences()
        assert prefs is None

    async def test_save_and_get_preferences(self, db: DatabaseManager):
        prefs = make_user_preferences(
            name="Alice",
            rating_threshold=4.2,
            noise_preference=Ambiance.QUIET,
            seating_preference=SeatingPreference.OUTDOOR,
            max_walk_minutes=20,
            default_party_size=4,
        )
        await db.save_preferences(prefs)
        result = await db.get_preferences()
        assert result is not None
        assert result.name == "Alice"
        assert result.rating_threshold == 4.2
        assert result.noise_preference == Ambiance.QUIET
        assert result.seating_preference == SeatingPreference.OUTDOOR
        assert result.max_walk_minutes == 20
        assert result.default_party_size == 4

    async def test_save_preferences_overwrites(self, db: DatabaseManager):
        prefs1 = make_user_preferences(name="Alice")
        await db.save_preferences(prefs1)
        prefs2 = make_user_preferences(name="Bob")
        await db.save_preferences(prefs2)
        result = await db.get_preferences()
        assert result is not None
        assert result.name == "Bob"


class TestDietaryRestrictions:
    async def test_dietary_restrictions_empty(self, db: DatabaseManager):
        restrictions = await db.get_dietary_restrictions()
        assert restrictions == []

    async def test_set_and_get_dietary_restrictions(self, db: DatabaseManager):
        await db.set_dietary_restrictions(["vegan", "nut-free"])
        restrictions = await db.get_dietary_restrictions()
        assert set(restrictions) == {"vegan", "nut-free"}

    async def test_dietary_restrictions_replaces_existing(self, db: DatabaseManager):
        await db.set_dietary_restrictions(["vegan", "nut-free"])
        await db.set_dietary_restrictions(["gluten-free"])
        restrictions = await db.get_dietary_restrictions()
        assert restrictions == ["gluten-free"]


class TestCuisinePreferences:
    async def test_cuisine_preferences_empty(self, db: DatabaseManager):
        prefs = await db.get_cuisine_preferences()
        assert prefs == []

    async def test_set_and_get_cuisine_preferences(self, db: DatabaseManager):
        cp1 = make_cuisine_preference(cuisine="italian", category=CuisineCategory.FAVORITE)
        cp2 = make_cuisine_preference(cuisine="thai", category=CuisineCategory.LIKE)
        await db.set_cuisine_preferences([cp1, cp2])
        result = await db.get_cuisine_preferences()
        assert len(result) == 2
        by_cuisine = {p.cuisine: p.category for p in result}
        assert by_cuisine["italian"] == CuisineCategory.FAVORITE
        assert by_cuisine["thai"] == CuisineCategory.LIKE


class TestPricePreferences:
    async def test_price_preferences_empty(self, db: DatabaseManager):
        prefs = await db.get_price_preferences()
        assert prefs == []

    async def test_set_and_get_price_preferences(self, db: DatabaseManager):
        pp1 = make_price_preference(price_level=PriceLevel.MODERATE, acceptable=True)
        pp2 = make_price_preference(price_level=PriceLevel.FINE_DINING, acceptable=False)
        await db.set_price_preferences([pp1, pp2])
        result = await db.get_price_preferences()
        assert len(result) == 2
        by_level = {p.price_level: p.acceptable for p in result}
        assert by_level[PriceLevel.MODERATE] is True
        assert by_level[PriceLevel.FINE_DINING] is False


class TestLocations:
    async def test_locations_empty(self, db: DatabaseManager):
        locations = await db.get_locations()
        assert locations == []

    async def test_save_and_get_all_locations(self, db: DatabaseManager):
        loc1 = make_location(name="home", address="100 Main St")
        loc2 = make_location(name="office", address="200 Broadway", lat=40.71, lng=-74.01)
        await db.save_location(loc1)
        await db.save_location(loc2)
        locations = await db.get_locations()
        assert len(locations) == 2
        names = {loc.name for loc in locations}
        assert names == {"home", "office"}

    async def test_get_location_by_name(self, db: DatabaseManager):
        loc = make_location(name="home", address="100 Main St")
        await db.save_location(loc)
        result = await db.get_location("home")
        assert result is not None
        assert result.name == "home"
        assert result.address == "100 Main St"

    async def test_get_location_case_insensitive(self, db: DatabaseManager):
        loc = make_location(name="Home")
        await db.save_location(loc)
        result = await db.get_location("HOME")
        assert result is not None
        assert result.name == "Home"

    async def test_get_location_returns_none(self, db: DatabaseManager):
        result = await db.get_location("nonexistent")
        assert result is None

    async def test_save_location_upsert(self, db: DatabaseManager):
        loc1 = make_location(name="home", address="100 Main St")
        await db.save_location(loc1)
        loc2 = make_location(name="home", address="200 Broadway")
        await db.save_location(loc2)
        result = await db.get_location("home")
        assert result is not None
        assert result.address == "200 Broadway"
        all_locs = await db.get_locations()
        assert len(all_locs) == 1


# ── People & Groups ──────────────────────────────────────────────────────────


class TestPeople:
    async def test_get_people_empty(self, db: DatabaseManager):
        people = await db.get_people()
        assert people == []

    async def test_get_people_with_data(self, db: DatabaseManager):
        await db.save_person(
            make_person(name="Alice", dietary_restrictions=["vegan"])
        )
        await db.save_person(make_person(name="Bob"))
        people = await db.get_people()
        assert len(people) == 2
        names = {p.name for p in people}
        assert names == {"Alice", "Bob"}
        alice = next(p for p in people if p.name == "Alice")
        assert alice.dietary_restrictions == ["vegan"]

    async def test_save_and_get_person(self, db: DatabaseManager):
        person = make_person(
            name="Alice",
            dietary_restrictions=["vegan", "nut-free"],
            no_alcohol=True,
            notes="Prefers window seat",
        )
        person_id = await db.save_person(person)
        assert person_id is not None
        result = await db.get_person("Alice")
        assert result is not None
        assert result.name == "Alice"
        assert set(result.dietary_restrictions) == {"vegan", "nut-free"}
        assert result.no_alcohol is True
        assert result.notes == "Prefers window seat"

    async def test_get_person_case_insensitive(self, db: DatabaseManager):
        person = make_person(name="Alice")
        await db.save_person(person)
        result = await db.get_person("ALICE")
        assert result is not None
        assert result.name == "Alice"

    async def test_get_person_returns_none(self, db: DatabaseManager):
        result = await db.get_person("Nobody")
        assert result is None

    async def test_save_person_upsert_preserves_id(self, db: DatabaseManager):
        person = make_person(name="Alice", notes="v1")
        first_id = await db.save_person(person)
        updated = make_person(name="Alice", notes="v2")
        second_id = await db.save_person(updated)
        assert first_id == second_id
        result = await db.get_person("Alice")
        assert result is not None
        assert result.notes == "v2"

    async def test_delete_person(self, db: DatabaseManager):
        person = make_person(name="Alice")
        await db.save_person(person)
        await db.delete_person("Alice")
        result = await db.get_person("Alice")
        assert result is None


class TestGroups:
    async def test_get_groups_empty(self, db: DatabaseManager):
        groups = await db.get_groups()
        assert groups == []

    async def test_get_groups_with_data(self, db: DatabaseManager):
        p1_id = await db.save_person(make_person(name="Alice"))
        p2_id = await db.save_person(make_person(name="Bob"))
        await db.save_group(
            make_group(name="Dinner Club", member_ids=[p1_id, p2_id])
        )
        await db.save_group(
            make_group(name="Lunch Crew", member_ids=[p1_id])
        )
        groups = await db.get_groups()
        assert len(groups) == 2
        names = {g.name for g in groups}
        assert names == {"Dinner Club", "Lunch Crew"}
        dinner = next(g for g in groups if g.name == "Dinner Club")
        assert set(dinner.member_names) == {"Alice", "Bob"}

    async def test_save_and_get_group_with_members(self, db: DatabaseManager):
        p1_id = await db.save_person(make_person(name="Alice"))
        p2_id = await db.save_person(make_person(name="Bob"))
        group = make_group(name="Dinner Club", member_ids=[p1_id, p2_id])
        group_id = await db.save_group(group)
        assert group_id is not None
        result = await db.get_group("Dinner Club")
        assert result is not None
        assert result.name == "Dinner Club"
        assert set(result.member_ids) == {p1_id, p2_id}
        assert set(result.member_names) == {"Alice", "Bob"}

    async def test_get_group_returns_none(self, db: DatabaseManager):
        result = await db.get_group("Nonexistent")
        assert result is None

    async def test_delete_group(self, db: DatabaseManager):
        p_id = await db.save_person(make_person(name="Alice"))
        group = make_group(name="Dinner Club", member_ids=[p_id])
        await db.save_group(group)
        await db.delete_group("Dinner Club")
        result = await db.get_group("Dinner Club")
        assert result is None

    async def test_get_group_dietary_restrictions(self, db: DatabaseManager):
        p1_id = await db.save_person(
            make_person(name="Alice", dietary_restrictions=["vegan", "nut-free"])
        )
        p2_id = await db.save_person(
            make_person(name="Bob", dietary_restrictions=["gluten-free", "vegan"])
        )
        group = make_group(name="Dinner Club", member_ids=[p1_id, p2_id])
        await db.save_group(group)
        restrictions = await db.get_group_dietary_restrictions("Dinner Club")
        assert set(restrictions) == {"vegan", "nut-free", "gluten-free"}

    async def test_get_group_dietary_restrictions_empty(self, db: DatabaseManager):
        p_id = await db.save_person(make_person(name="Alice", dietary_restrictions=[]))
        group = make_group(name="Dinner Club", member_ids=[p_id])
        await db.save_group(group)
        restrictions = await db.get_group_dietary_restrictions("Dinner Club")
        assert restrictions == []


# ── Restaurant Cache ─────────────────────────────────────────────────────────


class TestRestaurantCache:
    async def test_cache_and_get_restaurant(self, db: DatabaseManager):
        restaurant = make_restaurant(
            id="place_abc",
            name="Luigi's",
            cuisine=["italian", "pizza"],
            hours={"Monday": "11:00-22:00", "Tuesday": "11:00-22:00"},
        )
        await db.cache_restaurant(restaurant)
        result = await db.get_cached_restaurant("place_abc")
        assert result is not None
        assert result.id == "place_abc"
        assert result.name == "Luigi's"
        assert result.cuisine == ["italian", "pizza"]
        assert result.hours == {"Monday": "11:00-22:00", "Tuesday": "11:00-22:00"}

    async def test_get_cached_restaurant_none(self, db: DatabaseManager):
        result = await db.get_cached_restaurant("nonexistent")
        assert result is None

    async def test_cache_restaurant_null_fields(self, db: DatabaseManager):
        restaurant = make_restaurant(
            id="place_xyz",
            name="No Hours Place",
            cuisine=[],
            hours=None,
        )
        await db.cache_restaurant(restaurant)
        result = await db.get_cached_restaurant("place_xyz")
        assert result is not None
        assert result.cuisine == []
        assert result.hours is None

    async def test_search_cached_restaurants(self, db: DatabaseManager):
        await db.cache_restaurant(make_restaurant(id="p1", name="Luigi's Italian"))
        await db.cache_restaurant(make_restaurant(id="p2", name="Luigi's Pizza"))
        await db.cache_restaurant(make_restaurant(id="p3", name="Sushi Nakazawa"))
        results = await db.search_cached_restaurants("luigi")
        assert len(results) == 2
        names = {r.name for r in results}
        assert names == {"Luigi's Italian", "Luigi's Pizza"}

    async def test_search_cached_restaurants_no_results(self, db: DatabaseManager):
        await db.cache_restaurant(make_restaurant(id="p1", name="Luigi's"))
        results = await db.search_cached_restaurants("nonexistent")
        assert results == []

    async def test_get_stale_cache_ids(self, db: DatabaseManager):
        restaurant = make_restaurant(id="place_stale", name="Old Place")
        await db.cache_restaurant(restaurant)
        await db.execute(
            "UPDATE restaurant_cache SET cached_at = datetime('now', '-48 hours') WHERE id = ?",
            ("place_stale",),
        )
        stale_ids = await db.get_stale_cache_ids(max_age_hours=24)
        assert "place_stale" in stale_ids

    async def test_get_stale_cache_ids_none_stale(self, db: DatabaseManager):
        restaurant = make_restaurant(id="place_fresh", name="Fresh Place")
        await db.cache_restaurant(restaurant)
        stale_ids = await db.get_stale_cache_ids(max_age_hours=24)
        assert stale_ids == []

    async def test_get_platform_cache_age_hours_recent(self, db: DatabaseManager):
        restaurant = make_restaurant(id="age_fresh", name="Fresh")
        await db.cache_restaurant(restaurant)
        age = await db.get_platform_cache_age_hours("age_fresh")
        assert age is not None
        assert age < 1.0  # just cached, should be near zero

    async def test_get_platform_cache_age_hours_old(self, db: DatabaseManager):
        restaurant = make_restaurant(id="age_old", name="Old")
        await db.cache_restaurant(restaurant)
        await db.execute(
            "UPDATE restaurant_cache SET updated_at = datetime('now', '-48 hours') WHERE id = ?",
            ("age_old",),
        )
        age = await db.get_platform_cache_age_hours("age_old")
        assert age is not None
        assert age >= 47.0  # roughly 48 hours

    async def test_get_platform_cache_age_hours_missing(self, db: DatabaseManager):
        age = await db.get_platform_cache_age_hours("nonexistent")
        assert age is None

    async def test_update_platform_ids(self, db: DatabaseManager):
        restaurant = make_restaurant(id="place_plat", name="Platform Test")
        await db.cache_restaurant(restaurant)
        await db.update_platform_ids("place_plat", resy_id="resy_123", opentable_id="ot_456")
        result = await db.get_cached_restaurant("place_plat")
        assert result is not None
        assert result.resy_venue_id == "resy_123"
        assert result.opentable_id == "ot_456"

    async def test_update_resy_venue_id(self, db: DatabaseManager):
        restaurant = make_restaurant(id="place_resy", name="Resy Only")
        await db.cache_restaurant(restaurant)
        await db.update_resy_venue_id("place_resy", "resy_abc")
        result = await db.get_cached_restaurant("place_resy")
        assert result is not None
        assert result.resy_venue_id == "resy_abc"
        # opentable_id unchanged
        assert result.opentable_id == restaurant.opentable_id

    async def test_update_resy_venue_id_empty_string(self, db: DatabaseManager):
        """Empty string sentinel means 'checked, not on Resy'."""
        restaurant = make_restaurant(id="place_resy_neg", name="Not on Resy")
        await db.cache_restaurant(restaurant)
        await db.update_resy_venue_id("place_resy_neg", "")
        result = await db.get_cached_restaurant("place_resy_neg")
        assert result is not None
        assert result.resy_venue_id == ""

    async def test_update_opentable_id(self, db: DatabaseManager):
        restaurant = make_restaurant(id="place_ot", name="OT Only")
        await db.cache_restaurant(restaurant)
        await db.update_opentable_id("place_ot", "ot_xyz")
        result = await db.get_cached_restaurant("place_ot")
        assert result is not None
        assert result.opentable_id == "ot_xyz"
        # resy_venue_id unchanged
        assert result.resy_venue_id == restaurant.resy_venue_id

    async def test_update_opentable_id_empty_string(self, db: DatabaseManager):
        """Empty string sentinel means 'checked, not on OpenTable'."""
        restaurant = make_restaurant(id="place_ot_neg", name="Not on OT")
        await db.cache_restaurant(restaurant)
        await db.update_opentable_id("place_ot_neg", "")
        result = await db.get_cached_restaurant("place_ot_neg")
        assert result is not None
        assert result.opentable_id == ""

    async def test_update_resy_venue_id_does_not_clobber_opentable(self, db: DatabaseManager):
        """Updating resy_venue_id should not affect opentable_id."""
        restaurant = make_restaurant(
            id="place_both", name="Both", opentable_id="ot-existing",
        )
        await db.cache_restaurant(restaurant)
        await db.update_resy_venue_id("place_both", "resy-new")
        result = await db.get_cached_restaurant("place_both")
        assert result is not None
        assert result.resy_venue_id == "resy-new"
        assert result.opentable_id == "ot-existing"

    async def test_update_opentable_id_does_not_clobber_resy(self, db: DatabaseManager):
        """Updating opentable_id should not affect resy_venue_id."""
        restaurant = make_restaurant(
            id="place_both2", name="Both2", resy_venue_id="resy-existing",
        )
        await db.cache_restaurant(restaurant)
        await db.update_opentable_id("place_both2", "ot-new")
        result = await db.get_cached_restaurant("place_both2")
        assert result is not None
        assert result.opentable_id == "ot-new"
        assert result.resy_venue_id == "resy-existing"


# ── Visits & Reviews ─────────────────────────────────────────────────────────


class TestVisits:
    async def test_log_visit_returns_id(self, db: DatabaseManager):
        visit = make_visit(restaurant_id="place_1", restaurant_name="Test")
        visit_id = await db.log_visit(visit)
        assert isinstance(visit_id, int)
        assert visit_id > 0

    async def test_log_visit_with_companions(self, db: DatabaseManager):
        visit = make_visit(
            restaurant_id="place_1",
            restaurant_name="Test",
            companions=["Alice", "Bob"],
        )
        visit_id = await db.log_visit(visit)
        rows = await db.fetch_all("SELECT * FROM visits WHERE id = ?", (visit_id,))
        assert len(rows) == 1
        assert json.loads(rows[0]["companions"]) == ["Alice", "Bob"]

    async def test_get_recent_visits(self, db: DatabaseManager):
        today = date.today().isoformat()
        visit = make_visit(restaurant_id="place_1", restaurant_name="Today Spot", date=today)
        await db.log_visit(visit)
        results = await db.get_recent_visits(days=14)
        assert len(results) == 1
        assert results[0].restaurant_name == "Today Spot"

    async def test_get_recent_visits_empty(self, db: DatabaseManager):
        results = await db.get_recent_visits(days=14)
        assert results == []

    async def test_get_visits_for_restaurant(self, db: DatabaseManager):
        v1 = make_visit(restaurant_id="place_r", restaurant_name="R1", date="2026-01-10")
        v2 = make_visit(restaurant_id="place_r", restaurant_name="R1", date="2026-01-20")
        v3 = make_visit(restaurant_id="place_other", restaurant_name="R2", date="2026-01-15")
        await db.log_visit(v1)
        await db.log_visit(v2)
        await db.log_visit(v3)
        results = await db.get_visits_for_restaurant("place_r")
        assert len(results) == 2
        assert all(v.restaurant_id == "place_r" for v in results)

    async def test_get_visits_for_restaurant_empty(self, db: DatabaseManager):
        results = await db.get_visits_for_restaurant("nonexistent")
        assert results == []


class TestReviews:
    async def test_save_visit_review(self, db: DatabaseManager):
        visit = make_visit(restaurant_id="place_1", restaurant_name="R1")
        visit_id = await db.log_visit(visit)
        review = make_visit_review(
            visit_id=visit_id,
            would_return=True,
            overall_rating=4,
            ambiance_rating=5,
            notes="Great atmosphere",
        )
        await db.save_visit_review(review)
        row = await db.fetch_one(
            "SELECT * FROM visit_reviews WHERE visit_id = ?", (visit_id,)
        )
        assert row is not None
        assert row["would_return"] == 1
        assert row["overall_rating"] == 4
        assert row["ambiance_rating"] == 5
        assert row["notes"] == "Great atmosphere"

    async def test_save_visit_review_with_noise_level(self, db: DatabaseManager):
        visit = make_visit(restaurant_id="place_1", restaurant_name="R1")
        visit_id = await db.log_visit(visit)
        review = make_visit_review(
            visit_id=visit_id,
            would_return=False,
            noise_level=NoiseLevel.LOUD,
        )
        await db.save_visit_review(review)
        row = await db.fetch_one(
            "SELECT * FROM visit_reviews WHERE visit_id = ?", (visit_id,)
        )
        assert row is not None
        assert row["noise_level"] == "loud"

    async def test_save_visit_review_null_optionals(self, db: DatabaseManager):
        visit = make_visit(restaurant_id="place_1", restaurant_name="R1")
        visit_id = await db.log_visit(visit)
        review = make_visit_review(
            visit_id=visit_id,
            would_return=True,
            overall_rating=None,
            ambiance_rating=None,
            noise_level=None,
            notes=None,
        )
        await db.save_visit_review(review)
        row = await db.fetch_one(
            "SELECT * FROM visit_reviews WHERE visit_id = ?", (visit_id,)
        )
        assert row is not None
        assert row["overall_rating"] is None
        assert row["ambiance_rating"] is None
        assert row["noise_level"] is None
        assert row["notes"] is None

    async def test_save_dish_review(self, db: DatabaseManager):
        visit = make_visit(restaurant_id="place_1", restaurant_name="R1")
        visit_id = await db.log_visit(visit)
        review = make_dish_review(
            visit_id=visit_id,
            dish_name="Spicy Rigatoni",
            rating=5,
            would_order_again=True,
            notes="Perfect al dente",
        )
        await db.save_dish_review(review)
        row = await db.fetch_one(
            "SELECT * FROM dish_reviews WHERE visit_id = ?", (visit_id,)
        )
        assert row is not None
        assert row["dish_name"] == "Spicy Rigatoni"
        assert row["rating"] == 5
        assert row["would_order_again"] == 1
        assert row["notes"] == "Perfect al dente"


class TestRecentCuisines:
    async def test_get_recent_cuisines(self, db: DatabaseManager):
        today = date.today().isoformat()
        restaurant = make_restaurant(
            id="place_rc", name="Cuisine Test", cuisine=["italian", "pizza"]
        )
        await db.cache_restaurant(restaurant)
        visit = make_visit(restaurant_id="place_rc", restaurant_name="Cuisine Test", date=today)
        await db.log_visit(visit)
        cuisines = await db.get_recent_cuisines(days=7)
        assert set(cuisines) == {"italian", "pizza"}

    async def test_get_recent_cuisines_empty(self, db: DatabaseManager):
        cuisines = await db.get_recent_cuisines(days=7)
        assert cuisines == []

    async def test_get_recent_cuisines_null_cuisine(self, db: DatabaseManager):
        today = date.today().isoformat()
        restaurant = make_restaurant(id="place_nc", name="No Cuisine", cuisine=[])
        await db.cache_restaurant(restaurant)
        # Manually set cuisine to NULL in the database to test the None branch
        await db.execute(
            "UPDATE restaurant_cache SET cuisine = NULL WHERE id = ?",
            ("place_nc",),
        )
        visit = make_visit(restaurant_id="place_nc", restaurant_name="No Cuisine", date=today)
        await db.log_visit(visit)
        cuisines = await db.get_recent_cuisines(days=7)
        assert cuisines == []


# ── Reservations ─────────────────────────────────────────────────────────────


class TestReservations:
    async def test_save_and_get_reservation(self, db: DatabaseManager):
        reservation = make_reservation(
            id="res_001",
            restaurant_id="place_1",
            restaurant_name="Fine Diner",
            platform=BookingPlatform.RESY,
            platform_confirmation_id="conf_abc",
            date="2099-12-31",
            time="19:00",
            party_size=4,
            special_requests="Window seat",
        )
        await db.save_reservation(reservation)
        result = await db.get_reservation("res_001")
        assert result is not None
        assert result.id == "res_001"
        assert result.restaurant_name == "Fine Diner"
        assert result.platform == BookingPlatform.RESY
        assert result.platform_confirmation_id == "conf_abc"
        assert result.date == "2099-12-31"
        assert result.time == "19:00"
        assert result.party_size == 4
        assert result.special_requests == "Window seat"
        assert result.status == "confirmed"

    async def test_get_reservation_none(self, db: DatabaseManager):
        result = await db.get_reservation("nonexistent")
        assert result is None

    async def test_get_upcoming_reservations(self, db: DatabaseManager):
        future = make_reservation(
            id="res_future",
            restaurant_name="Future Place",
            date="2099-12-31",
            time="19:00",
        )
        await db.save_reservation(future)
        upcoming = await db.get_upcoming_reservations()
        assert len(upcoming) == 1
        assert upcoming[0].id == "res_future"

    async def test_get_upcoming_reservations_excludes_past(self, db: DatabaseManager):
        past = make_reservation(
            id="res_past",
            restaurant_name="Past Place",
            date="2000-01-01",
            time="19:00",
        )
        await db.save_reservation(past)
        upcoming = await db.get_upcoming_reservations()
        assert len(upcoming) == 0

    async def test_get_upcoming_reservations_excludes_cancelled(self, db: DatabaseManager):
        cancelled = make_reservation(
            id="res_cancelled",
            restaurant_name="Cancelled Place",
            date="2099-12-31",
            time="19:00",
            status="cancelled",
        )
        await db.save_reservation(cancelled)
        upcoming = await db.get_upcoming_reservations()
        assert len(upcoming) == 0

    async def test_cancel_reservation(self, db: DatabaseManager):
        reservation = make_reservation(
            id="res_to_cancel",
            restaurant_name="Cancel Me",
            date="2099-12-31",
            time="19:00",
        )
        await db.save_reservation(reservation)
        await db.cancel_reservation("res_to_cancel")
        result = await db.get_reservation("res_to_cancel")
        assert result is not None
        assert result.status == "cancelled"
        assert result.cancelled_at is not None


# ── Blacklist ────────────────────────────────────────────────────────────────


class TestBlacklist:
    async def test_add_and_check_blacklist(self, db: DatabaseManager):
        await db.add_to_blacklist("place_bad", "Bad Restaurant", "Terrible service")
        is_bl = await db.is_blacklisted("place_bad")
        assert is_bl is True

    async def test_is_blacklisted_false(self, db: DatabaseManager):
        is_bl = await db.is_blacklisted("place_good")
        assert is_bl is False

    async def test_get_blacklist_empty(self, db: DatabaseManager):
        blacklist = await db.get_blacklist()
        assert blacklist == []

    async def test_get_blacklist_with_entries(self, db: DatabaseManager):
        await db.add_to_blacklist("place_bad1", "Bad One", "Rude staff")
        await db.add_to_blacklist("place_bad2", "Bad Two", "Food poisoning")
        blacklist = await db.get_blacklist()
        assert len(blacklist) == 2
        ids = {entry["restaurant_id"] for entry in blacklist}
        assert ids == {"place_bad1", "place_bad2"}

    async def test_remove_from_blacklist(self, db: DatabaseManager):
        await db.add_to_blacklist("place_bad", "Bad Restaurant", "Reason")
        await db.remove_from_blacklist("place_bad")
        is_bl = await db.is_blacklisted("place_bad")
        assert is_bl is False
        blacklist = await db.get_blacklist()
        assert len(blacklist) == 0


# ── API Logging ──────────────────────────────────────────────────────────────


class TestAPILogging:
    async def test_log_api_call(self, db: DatabaseManager):
        await db.log_api_call(
            provider="google",
            endpoint="/places/search",
            cost_cents=2.5,
            status_code=200,
            cached=False,
        )
        rows = await db.fetch_all("SELECT * FROM api_calls")
        assert len(rows) == 1
        assert rows[0]["provider"] == "google"
        assert rows[0]["endpoint"] == "/places/search"
        assert rows[0]["cost_cents"] == 2.5
        assert rows[0]["status_code"] == 200
        assert rows[0]["cached"] == 0

    async def test_get_api_costs_empty(self, db: DatabaseManager):
        costs = await db.get_api_costs(days=30)
        assert costs == {}

    async def test_get_api_costs_sums_by_provider(self, db: DatabaseManager):
        await db.log_api_call("google", "/places", 2.0, 200, False)
        await db.log_api_call("google", "/details", 3.0, 200, False)
        await db.log_api_call("resy", "/venues", 1.5, 200, True)
        costs = await db.get_api_costs(days=30)
        assert costs["google"] == 5.0
        assert costs["resy"] == 1.5

    async def test_get_api_call_stats_empty(self, db: DatabaseManager):
        stats = await db.get_api_call_stats(days=30)
        assert stats == []

    async def test_get_api_call_stats_aggregates(self, db: DatabaseManager):
        await db.log_api_call("google", "/places", 3.2, 200, False)
        await db.log_api_call("google", "/places", 3.2, 200, True)
        await db.log_api_call("resy", "/venues", 0.0, 200, False)
        stats = await db.get_api_call_stats(days=30)
        assert len(stats) == 2
        google = next(s for s in stats if s["provider"] == "google")
        assert google["total_calls"] == 2
        assert google["cached_calls"] == 1
        assert google["total_cost_cents"] == 6.4
        resy = next(s for s in stats if s["provider"] == "resy")
        assert resy["total_calls"] == 1
        assert resy["cached_calls"] == 0
        assert resy["total_cost_cents"] == 0.0


# ── EPIC-07: get_visit_by_restaurant_name ────────────────────────────────────


class TestGetVisitByRestaurantName:
    async def test_found_exact_match(self, db: DatabaseManager):
        visit = make_visit(
            restaurant_id="place_1",
            restaurant_name="Carbone",
            date="2026-02-01",
        )
        await db.log_visit(visit)
        result = await db.get_visit_by_restaurant_name("Carbone")
        assert result is not None
        assert result.restaurant_name == "Carbone"
        assert result.restaurant_id == "place_1"

    async def test_not_found(self, db: DatabaseManager):
        result = await db.get_visit_by_restaurant_name("Nonexistent Place")
        assert result is None

    async def test_partial_match(self, db: DatabaseManager):
        visit = make_visit(
            restaurant_id="place_2",
            restaurant_name="Luigi's Italian Kitchen",
            date="2026-02-05",
        )
        await db.log_visit(visit)
        result = await db.get_visit_by_restaurant_name("Luigi")
        assert result is not None
        assert result.restaurant_name == "Luigi's Italian Kitchen"

    async def test_returns_most_recent_visit(self, db: DatabaseManager):
        v1 = make_visit(
            restaurant_id="place_3",
            restaurant_name="Sushi Nakazawa",
            date="2026-01-10",
        )
        v2 = make_visit(
            restaurant_id="place_3",
            restaurant_name="Sushi Nakazawa",
            date="2026-02-01",
        )
        await db.log_visit(v1)
        await db.log_visit(v2)
        result = await db.get_visit_by_restaurant_name("Sushi Nakazawa")
        assert result is not None
        assert result.date == "2026-02-01"

    async def test_case_insensitive(self, db: DatabaseManager):
        visit = make_visit(
            restaurant_id="place_4",
            restaurant_name="Le Bernardin",
            date="2026-02-01",
        )
        await db.log_visit(visit)
        result = await db.get_visit_by_restaurant_name("le bernardin")
        assert result is not None
        assert result.restaurant_name == "Le Bernardin"


# ── EPIC-07: get_visit_review ────────────────────────────────────────────────


class TestGetVisitReview:
    async def test_found(self, db: DatabaseManager):
        visit = make_visit(restaurant_id="place_1", restaurant_name="R1")
        visit_id = await db.log_visit(visit)
        review = make_visit_review(
            visit_id=visit_id,
            would_return=True,
            overall_rating=4,
            notes="Great meal",
        )
        await db.save_visit_review(review)
        result = await db.get_visit_review(visit_id)
        assert result is not None
        assert result.visit_id == visit_id
        assert result.would_return is True
        assert result.overall_rating == 4
        assert result.notes == "Great meal"

    async def test_not_found(self, db: DatabaseManager):
        result = await db.get_visit_review(9999)
        assert result is None


# ── EPIC-07: get_restaurant_reviews ──────────────────────────────────────────


class TestGetRestaurantReviews:
    async def test_with_reviews(self, db: DatabaseManager):
        v1 = make_visit(
            restaurant_id="place_r1",
            restaurant_name="Test Restaurant",
            date="2026-01-10",
        )
        v2 = make_visit(
            restaurant_id="place_r1",
            restaurant_name="Test Restaurant",
            date="2026-02-01",
        )
        v1_id = await db.log_visit(v1)
        v2_id = await db.log_visit(v2)
        await db.save_visit_review(
            make_visit_review(visit_id=v1_id, would_return=True, overall_rating=4)
        )
        await db.save_visit_review(
            make_visit_review(visit_id=v2_id, would_return=False, overall_rating=2)
        )
        reviews = await db.get_restaurant_reviews("place_r1")
        assert len(reviews) == 2
        ratings = {r.overall_rating for r in reviews}
        assert ratings == {4, 2}

    async def test_empty(self, db: DatabaseManager):
        reviews = await db.get_restaurant_reviews("nonexistent")
        assert reviews == []

    async def test_only_returns_reviews_for_target_restaurant(
        self, db: DatabaseManager
    ):
        v1 = make_visit(
            restaurant_id="place_target",
            restaurant_name="Target",
            date="2026-02-01",
        )
        v2 = make_visit(
            restaurant_id="place_other",
            restaurant_name="Other",
            date="2026-02-01",
        )
        v1_id = await db.log_visit(v1)
        v2_id = await db.log_visit(v2)
        await db.save_visit_review(
            make_visit_review(visit_id=v1_id, would_return=True, overall_rating=5)
        )
        await db.save_visit_review(
            make_visit_review(visit_id=v2_id, would_return=True, overall_rating=3)
        )
        reviews = await db.get_restaurant_reviews("place_target")
        assert len(reviews) == 1
        assert reviews[0].overall_rating == 5


# ── EPIC-07: get_recency_penalties ───────────────────────────────────────────


class TestGetRecencyPenalties:
    async def test_with_visits(self, db: DatabaseManager):
        today = date.today().isoformat()
        visit = make_visit(
            restaurant_id="place_it",
            restaurant_name="Italian Spot",
            date=today,
            cuisine="italian",
        )
        await db.log_visit(visit)
        penalties = await db.get_recency_penalties(days=14)
        assert "italian" in penalties
        # Visited today: days_ago ~ 0, penalty ~ 1.0
        assert penalties["italian"] > 0.8

    async def test_empty(self, db: DatabaseManager):
        penalties = await db.get_recency_penalties(days=14)
        assert penalties == {}

    async def test_mixed_cuisines(self, db: DatabaseManager):
        today = date.today().isoformat()
        v1 = make_visit(
            restaurant_id="place_it",
            restaurant_name="Italian Spot",
            date=today,
            cuisine="italian",
        )
        v2 = make_visit(
            restaurant_id="place_jp",
            restaurant_name="Japanese Spot",
            date=today,
            cuisine="japanese",
        )
        await db.log_visit(v1)
        await db.log_visit(v2)
        penalties = await db.get_recency_penalties(days=14)
        assert "italian" in penalties
        assert "japanese" in penalties
        assert penalties["italian"] > 0.8
        assert penalties["japanese"] > 0.8

    async def test_cuisine_is_lowercased(self, db: DatabaseManager):
        today = date.today().isoformat()
        visit = make_visit(
            restaurant_id="place_mixed",
            restaurant_name="Mixed Case",
            date=today,
            cuisine="Italian",
        )
        await db.log_visit(visit)
        penalties = await db.get_recency_penalties(days=14)
        assert "italian" in penalties
        assert "Italian" not in penalties

    async def test_falls_back_to_cached_cuisine(self, db: DatabaseManager):
        """When visit has no cuisine, falls back to restaurant_cache cuisine."""
        today = date.today().isoformat()
        restaurant = make_restaurant(
            id="place_cached",
            name="Cached Cuisine Place",
            cuisine=["mexican"],
        )
        await db.cache_restaurant(restaurant)
        visit = make_visit(
            restaurant_id="place_cached",
            restaurant_name="Cached Cuisine Place",
            date=today,
            cuisine=None,
        )
        await db.log_visit(visit)
        penalties = await db.get_recency_penalties(days=14)
        assert "mexican" in penalties

    async def test_no_cuisine_anywhere_skipped(self, db: DatabaseManager):
        """Visit with no cuisine and no cached restaurant cuisine is skipped."""
        today = date.today().isoformat()
        # Visit with no cuisine and no matching cache entry
        visit = make_visit(
            restaurant_id="place_unknown",
            restaurant_name="Mystery Place",
            date=today,
            cuisine=None,
        )
        await db.log_visit(visit)
        penalties = await db.get_recency_penalties(days=14)
        assert penalties == {}

    async def test_cached_restaurant_empty_cuisine_list_skipped(
        self, db: DatabaseManager
    ):
        """Visit with empty cached cuisine list is also skipped."""
        today = date.today().isoformat()
        restaurant = make_restaurant(
            id="place_empty_c",
            name="Empty Cuisine",
            cuisine=[],
        )
        await db.cache_restaurant(restaurant)
        visit = make_visit(
            restaurant_id="place_empty_c",
            restaurant_name="Empty Cuisine",
            date=today,
            cuisine=None,
        )
        await db.log_visit(visit)
        penalties = await db.get_recency_penalties(days=14)
        assert penalties == {}

    async def test_keeps_highest_penalty_for_same_cuisine(
        self, db: DatabaseManager
    ):
        """When same cuisine visited multiple times, highest penalty wins."""
        today = date.today().isoformat()
        # Recent visit (high penalty)
        v1 = make_visit(
            restaurant_id="place_it1",
            restaurant_name="Italian Today",
            date=today,
            cuisine="italian",
        )
        # Older visit (lower penalty) — 7 days ago
        seven_days_ago = (
            date.today() - __import__("datetime").timedelta(days=7)
        ).isoformat()
        v2 = make_visit(
            restaurant_id="place_it2",
            restaurant_name="Italian Last Week",
            date=seven_days_ago,
            cuisine="italian",
        )
        await db.log_visit(v1)
        await db.log_visit(v2)
        penalties = await db.get_recency_penalties(days=14)
        assert "italian" in penalties
        # Should keep the higher penalty (~1.0 from today, not ~0.5 from 7 days ago)
        assert penalties["italian"] > 0.8


# ── EPIC-07: Visit model cuisine field ───────────────────────────────────────


class TestVisitCuisineField:
    async def test_log_visit_stores_cuisine(self, db: DatabaseManager):
        visit = make_visit(
            restaurant_id="place_cuisine",
            restaurant_name="Cuisine Test",
            cuisine="thai",
        )
        visit_id = await db.log_visit(visit)
        row = await db.fetch_one(
            "SELECT cuisine FROM visits WHERE id = ?", (visit_id,)
        )
        assert row is not None
        assert row["cuisine"] == "thai"

    async def test_log_visit_stores_null_cuisine(self, db: DatabaseManager):
        visit = make_visit(
            restaurant_id="place_no_cuisine",
            restaurant_name="No Cuisine",
            cuisine=None,
        )
        visit_id = await db.log_visit(visit)
        row = await db.fetch_one(
            "SELECT cuisine FROM visits WHERE id = ?", (visit_id,)
        )
        assert row is not None
        assert row["cuisine"] is None

    async def test_log_visit_cuisine_roundtrips(self, db: DatabaseManager):
        """Cuisine stored via log_visit is returned via get_recent_visits."""
        today = date.today().isoformat()
        visit = make_visit(
            restaurant_id="place_rt",
            restaurant_name="Roundtrip",
            date=today,
            cuisine="korean",
        )
        await db.log_visit(visit)
        visits = await db.get_recent_visits(days=14)
        assert len(visits) == 1
        assert visits[0].cuisine == "korean"

    async def test_get_visits_for_restaurant_includes_cuisine(
        self, db: DatabaseManager
    ):
        visit = make_visit(
            restaurant_id="place_vc",
            restaurant_name="Visit Cuisine",
            cuisine="french",
        )
        await db.log_visit(visit)
        visits = await db.get_visits_for_restaurant("place_vc")
        assert len(visits) == 1
        assert visits[0].cuisine == "french"
