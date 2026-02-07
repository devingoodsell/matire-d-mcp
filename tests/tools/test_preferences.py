from unittest.mock import AsyncMock, patch

import pytest
from fastmcp import Client, FastMCP

from src.models.enums import CuisineCategory, PriceLevel
from src.models.user import (
    CuisinePreference,
    Location,
    PricePreference,
    UserPreferences,
)
from src.storage.database import DatabaseManager
from src.tools.preferences import register_preference_tools


@pytest.fixture
async def db():
    """In-memory SQLite database with schema applied."""
    manager = DatabaseManager(":memory:")
    await manager.initialize()
    yield manager
    await manager.close()


@pytest.fixture
def mock_settings():
    """Mock settings with a test Google API key."""
    return type("Settings", (), {"google_api_key": "test-key"})()


@pytest.fixture
def patched_mcp(db, mock_settings):
    """Return (mcp, db, geo_mock) with get_db, get_settings, and
    geocode_address patched for the entire tool lifetime."""
    test_mcp = FastMCP("test")
    db_patch = patch(
        "src.tools.preferences.get_db", return_value=db
    )
    settings_patch = patch(
        "src.config.get_settings", return_value=mock_settings
    )
    geocode_patch = patch(
        "src.tools.preferences.geocode_address",
        new_callable=AsyncMock,
        return_value=(40.7128, -74.0060),
    )
    db_patch.start()
    settings_patch.start()
    geo_mock = geocode_patch.start()
    register_preference_tools(test_mcp)
    yield test_mcp, db, geo_mock
    db_patch.stop()
    settings_patch.stop()
    geocode_patch.stop()


# ── setup_preferences ───────────────────────────────────────────────────────


class TestSetupPreferences:
    async def test_saves_core_prefs_and_returns_confirmation(
        self, patched_mcp
    ):
        mcp, db, _ = patched_mcp
        async with Client(mcp) as client:
            result = await client.call_tool(
                "setup_preferences", {"name": "Alice"}
            )
        text = str(result)
        assert "Preferences saved for Alice" in text

        prefs = await db.get_preferences()
        assert prefs is not None
        assert prefs.name == "Alice"
        assert prefs.rating_threshold == 4.0
        assert prefs.max_walk_minutes == 15
        assert prefs.default_party_size == 2

    async def test_saves_dietary_restrictions(self, patched_mcp):
        mcp, db, _ = patched_mcp
        async with Client(mcp) as client:
            result = await client.call_tool(
                "setup_preferences",
                {
                    "name": "Bob",
                    "dietary_restrictions": ["vegan", "nut-free"],
                },
            )
        text = str(result)
        assert "Dietary: vegan, nut-free" in text

        restrictions = await db.get_dietary_restrictions()
        assert set(restrictions) == {"vegan", "nut-free"}

    async def test_saves_favorite_and_avoid_cuisines(
        self, patched_mcp
    ):
        mcp, db, _ = patched_mcp
        async with Client(mcp) as client:
            result = await client.call_tool(
                "setup_preferences",
                {
                    "name": "Carol",
                    "favorite_cuisines": ["italian", "korean"],
                    "cuisines_to_avoid": ["fast_food"],
                },
            )
        text = str(result)
        assert "Favorites: italian, korean" in text
        assert "Avoid: fast_food" in text

        cuisines = await db.get_cuisine_preferences()
        by_cuisine = {c.cuisine: c.category for c in cuisines}
        assert by_cuisine["italian"] == CuisineCategory.FAVORITE
        assert by_cuisine["korean"] == CuisineCategory.FAVORITE
        assert by_cuisine["fast_food"] == CuisineCategory.AVOID

    async def test_saves_only_favorite_cuisines(self, patched_mcp):
        """favorite_cuisines set, cuisines_to_avoid is None."""
        mcp, db, _ = patched_mcp
        async with Client(mcp) as client:
            result = await client.call_tool(
                "setup_preferences",
                {
                    "name": "Dave",
                    "favorite_cuisines": ["japanese"],
                },
            )
        text = str(result)
        assert "Favorites: japanese" in text
        assert "Avoid" not in text

        cuisines = await db.get_cuisine_preferences()
        assert len(cuisines) == 1
        assert cuisines[0].cuisine == "japanese"
        assert cuisines[0].category == CuisineCategory.FAVORITE

    async def test_saves_only_avoid_cuisines(self, patched_mcp):
        """cuisines_to_avoid set, favorite_cuisines is None."""
        mcp, db, _ = patched_mcp
        async with Client(mcp) as client:
            result = await client.call_tool(
                "setup_preferences",
                {
                    "name": "Eve",
                    "cuisines_to_avoid": ["mexican"],
                },
            )
        text = str(result)
        assert "Avoid: mexican" in text
        assert "Favorites" not in text

        cuisines = await db.get_cuisine_preferences()
        assert len(cuisines) == 1
        assert cuisines[0].cuisine == "mexican"
        assert cuisines[0].category == CuisineCategory.AVOID

    async def test_saves_price_levels(self, patched_mcp):
        mcp, db, _ = patched_mcp
        async with Client(mcp) as client:
            result = await client.call_tool(
                "setup_preferences",
                {
                    "name": "Frank",
                    "price_levels": [2, 3],
                },
            )
        text = str(result)
        assert "Price levels: 2, 3" in text

        prices = await db.get_price_preferences()
        levels = {p.price_level for p in prices}
        assert levels == {PriceLevel.MODERATE, PriceLevel.UPSCALE}
        assert all(p.acceptable for p in prices)

    async def test_geocodes_home_address(self, patched_mcp):
        mcp, db, geo_mock = patched_mcp
        geo_mock.return_value = (40.748, -73.985)
        async with Client(mcp) as client:
            result = await client.call_tool(
                "setup_preferences",
                {
                    "name": "Grace",
                    "home_address": "350 5th Ave, New York, NY",
                },
            )
        text = str(result)
        assert "home (350 5th Ave, New York, NY)" in text

        loc = await db.get_location("home")
        assert loc is not None
        assert loc.address == "350 5th Ave, New York, NY"
        assert loc.lat == 40.748
        assert loc.lng == -73.985

    async def test_geocodes_work_address(self, patched_mcp):
        mcp, db, geo_mock = patched_mcp
        geo_mock.return_value = (40.758, -73.979)
        async with Client(mcp) as client:
            result = await client.call_tool(
                "setup_preferences",
                {
                    "name": "Hank",
                    "work_address": "1515 Broadway, New York, NY",
                },
            )
        text = str(result)
        assert "work (1515 Broadway, New York, NY)" in text

        loc = await db.get_location("work")
        assert loc is not None
        assert loc.address == "1515 Broadway, New York, NY"

    async def test_geocodes_both_addresses(self, patched_mcp):
        mcp, db, geo_mock = patched_mcp
        geo_mock.side_effect = [
            (40.748, -73.985),
            (40.758, -73.979),
        ]
        async with Client(mcp) as client:
            result = await client.call_tool(
                "setup_preferences",
                {
                    "name": "Ivy",
                    "home_address": "350 5th Ave",
                    "work_address": "1515 Broadway",
                },
            )
        text = str(result)
        assert "home (350 5th Ave)" in text
        assert "work (1515 Broadway)" in text
        assert geo_mock.call_count == 2

    async def test_geocoding_failure_reports_error(self, patched_mcp):
        mcp, db, geo_mock = patched_mcp
        geo_mock.return_value = None
        async with Client(mcp) as client:
            result = await client.call_tool(
                "setup_preferences",
                {
                    "name": "Jack",
                    "home_address": "invalid address xyz",
                },
            )
        text = str(result)
        assert "could not geocode: invalid address xyz" in text

        loc = await db.get_location("home")
        assert loc is None

    async def test_custom_scalar_preferences(self, patched_mcp):
        mcp, db, _ = patched_mcp
        async with Client(mcp) as client:
            result = await client.call_tool(
                "setup_preferences",
                {
                    "name": "Kate",
                    "noise_preference": "quiet",
                    "seating_preference": "outdoor",
                    "max_walk_minutes": 25,
                    "default_party_size": 6,
                    "rating_threshold": 4.5,
                },
            )
        text = str(result)
        assert "Noise: quiet" in text
        assert "Seating: outdoor" in text
        assert "Walk: 25min" in text
        assert "Party: 6" in text
        assert "Min rating: 4.5" in text

        prefs = await db.get_preferences()
        assert prefs is not None
        assert prefs.noise_preference.value == "quiet"
        assert prefs.seating_preference.value == "outdoor"
        assert prefs.max_walk_minutes == 25
        assert prefs.default_party_size == 6
        assert prefs.rating_threshold == 4.5

    async def test_no_optional_fields_minimal_output(
        self, patched_mcp
    ):
        """No optional fields -> confirmation has no extras."""
        mcp, _, _ = patched_mcp
        async with Client(mcp) as client:
            result = await client.call_tool(
                "setup_preferences", {"name": "Minimal"}
            )
        text = str(result)
        assert "Preferences saved for Minimal" in text
        assert "Dietary" not in text
        assert "Favorites" not in text
        assert "Avoid" not in text
        assert "Price levels" not in text
        assert "Locations" not in text

    async def test_geocode_called_with_correct_api_key(
        self, patched_mcp
    ):
        mcp, _, geo_mock = patched_mcp
        geo_mock.return_value = (40.7, -74.0)
        async with Client(mcp) as client:
            await client.call_tool(
                "setup_preferences",
                {
                    "name": "Leo",
                    "home_address": "123 Main St",
                },
            )
        geo_mock.assert_called_once_with("123 Main St", "test-key")

    async def test_location_walk_radius_matches_max_walk(
        self, patched_mcp
    ):
        mcp, db, geo_mock = patched_mcp
        geo_mock.return_value = (40.7, -74.0)
        async with Client(mcp) as client:
            await client.call_tool(
                "setup_preferences",
                {
                    "name": "Mike",
                    "home_address": "123 Main St",
                    "max_walk_minutes": 30,
                },
            )
        loc = await db.get_location("home")
        assert loc is not None
        assert loc.walk_radius_minutes == 30


# ── get_my_preferences ──────────────────────────────────────────────────────


class TestGetMyPreferences:
    async def test_no_prefs_configured(self, patched_mcp):
        mcp, _, _ = patched_mcp
        async with Client(mcp) as client:
            result = await client.call_tool(
                "get_my_preferences", {}
            )
        text = str(result)
        assert "No preferences configured" in text
        assert "setup_preferences" in text

    async def test_returns_full_preferences(self, patched_mcp):
        mcp, db, _ = patched_mcp

        prefs = UserPreferences(
            name="Alice",
            rating_threshold=4.2,
            noise_preference="quiet",
            seating_preference="outdoor",
            max_walk_minutes=20,
            default_party_size=4,
        )
        await db.save_preferences(prefs)
        await db.set_dietary_restrictions(["vegan", "nut-free"])
        await db.set_cuisine_preferences([
            CuisinePreference(
                cuisine="italian",
                category=CuisineCategory.FAVORITE,
            ),
            CuisinePreference(
                cuisine="korean",
                category=CuisineCategory.FAVORITE,
            ),
            CuisinePreference(
                cuisine="fast_food",
                category=CuisineCategory.AVOID,
            ),
        ])
        await db.set_price_preferences([
            PricePreference(
                price_level=PriceLevel.MODERATE, acceptable=True
            ),
            PricePreference(
                price_level=PriceLevel.UPSCALE, acceptable=True
            ),
        ])
        await db.save_location(Location(
            name="home",
            address="350 5th Ave",
            lat=40.748,
            lng=-73.985,
        ))

        async with Client(mcp) as client:
            result = await client.call_tool(
                "get_my_preferences", {}
            )
        text = str(result)

        assert "Preferences for Alice" in text
        assert "Noise: quiet" in text
        assert "Seating: outdoor" in text
        assert "Walk: 20min" in text
        assert "Party size: 4" in text
        assert "Min rating: 4.2" in text
        assert "Dietary: vegan, nut-free" in text
        assert "Favorite cuisines: italian, korean" in text
        assert "Avoid cuisines: fast_food" in text
        assert "Price levels: 2, 3" in text
        assert "Location 'home': 350 5th Ave" in text

    async def test_returns_prefs_without_optional_data(
        self, patched_mcp
    ):
        """Prefs exist but no dietary/cuisines/prices/locations."""
        mcp, db, _ = patched_mcp
        await db.save_preferences(UserPreferences(name="Bob"))

        async with Client(mcp) as client:
            result = await client.call_tool(
                "get_my_preferences", {}
            )
        text = str(result)

        assert "Preferences for Bob" in text
        assert "Noise: moderate" in text
        assert "Seating: no_preference" in text
        assert "Dietary" not in text
        assert "Favorite cuisines" not in text
        assert "Avoid cuisines" not in text
        assert "Price levels" not in text
        assert "Location" not in text

    async def test_returns_prefs_with_only_favorites(
        self, patched_mcp
    ):
        """Cuisines has favorites but no avoid."""
        mcp, db, _ = patched_mcp
        await db.save_preferences(UserPreferences(name="Fav"))
        await db.set_cuisine_preferences([
            CuisinePreference(
                cuisine="sushi",
                category=CuisineCategory.FAVORITE,
            ),
        ])

        async with Client(mcp) as client:
            result = await client.call_tool(
                "get_my_preferences", {}
            )
        text = str(result)
        assert "Favorite cuisines: sushi" in text
        assert "Avoid cuisines" not in text

    async def test_returns_prefs_with_only_avoid(self, patched_mcp):
        """Cuisines has avoid but no favorites."""
        mcp, db, _ = patched_mcp
        await db.save_preferences(UserPreferences(name="Avd"))
        await db.set_cuisine_preferences([
            CuisinePreference(
                cuisine="fast_food",
                category=CuisineCategory.AVOID,
            ),
        ])

        async with Client(mcp) as client:
            result = await client.call_tool(
                "get_my_preferences", {}
            )
        text = str(result)
        assert "Avoid cuisines: fast_food" in text
        assert "Favorite cuisines" not in text

    async def test_returns_multiple_locations(self, patched_mcp):
        mcp, db, _ = patched_mcp
        await db.save_preferences(UserPreferences(name="Multi"))
        await db.save_location(Location(
            name="home",
            address="100 Main St",
            lat=40.7,
            lng=-74.0,
        ))
        await db.save_location(Location(
            name="work",
            address="200 Broadway",
            lat=40.71,
            lng=-74.01,
        ))

        async with Client(mcp) as client:
            result = await client.call_tool(
                "get_my_preferences", {}
            )
        text = str(result)
        assert "Location 'home': 100 Main St" in text
        assert "Location 'work': 200 Broadway" in text

    async def test_price_levels_only_shows_acceptable(
        self, patched_mcp
    ):
        """Only acceptable=True prices should appear."""
        mcp, db, _ = patched_mcp
        await db.save_preferences(
            UserPreferences(name="PriceTest")
        )
        await db.set_price_preferences([
            PricePreference(
                price_level=PriceLevel.BUDGET, acceptable=True
            ),
            PricePreference(
                price_level=PriceLevel.FINE_DINING, acceptable=False
            ),
        ])

        async with Client(mcp) as client:
            result = await client.call_tool(
                "get_my_preferences", {}
            )
        text = str(result)
        assert "Price levels: 1" in text
        # Fine dining (level 4) must not appear in the price list
        assert "Price levels: 1, 4" not in text
        assert "Price levels: 4" not in text


# ── update_preferences ──────────────────────────────────────────────────────


class TestUpdatePreferences:
    async def test_no_prefs_exist_returns_error(self, patched_mcp):
        mcp, _, _ = patched_mcp
        async with Client(mcp) as client:
            result = await client.call_tool(
                "update_preferences",
                {"noise_preference": "quiet"},
            )
        text = str(result)
        assert "No preferences configured" in text
        assert "setup_preferences" in text

    async def test_update_dietary_restrictions(self, patched_mcp):
        mcp, db, _ = patched_mcp
        await db.save_preferences(UserPreferences(name="Alice"))
        await db.set_dietary_restrictions(["vegan"])

        async with Client(mcp) as client:
            result = await client.call_tool(
                "update_preferences",
                {
                    "dietary_restrictions": [
                        "gluten-free",
                        "dairy-free",
                    ],
                },
            )
        text = str(result)
        assert "Dietary: gluten-free, dairy-free" in text

        restrictions = await db.get_dietary_restrictions()
        assert set(restrictions) == {"gluten-free", "dairy-free"}

    async def test_add_favorite_cuisine(self, patched_mcp):
        mcp, db, _ = patched_mcp
        await db.save_preferences(UserPreferences(name="Alice"))

        async with Client(mcp) as client:
            result = await client.call_tool(
                "update_preferences",
                {"add_favorite_cuisine": "thai"},
            )
        text = str(result)
        assert "Added favorite: thai" in text

        cuisines = await db.get_cuisine_preferences()
        assert len(cuisines) == 1
        assert cuisines[0].cuisine == "thai"
        assert cuisines[0].category == CuisineCategory.FAVORITE

    async def test_remove_favorite_cuisine(self, patched_mcp):
        mcp, db, _ = patched_mcp
        await db.save_preferences(UserPreferences(name="Alice"))
        await db.set_cuisine_preferences([
            CuisinePreference(
                cuisine="italian",
                category=CuisineCategory.FAVORITE,
            ),
            CuisinePreference(
                cuisine="korean",
                category=CuisineCategory.FAVORITE,
            ),
        ])

        async with Client(mcp) as client:
            result = await client.call_tool(
                "update_preferences",
                {"remove_favorite_cuisine": "italian"},
            )
        text = str(result)
        assert "Removed favorite: italian" in text

        cuisines = await db.get_cuisine_preferences()
        assert len(cuisines) == 1
        assert cuisines[0].cuisine == "korean"

    async def test_add_avoid_cuisine(self, patched_mcp):
        mcp, db, _ = patched_mcp
        await db.save_preferences(UserPreferences(name="Alice"))

        async with Client(mcp) as client:
            result = await client.call_tool(
                "update_preferences",
                {"add_avoid_cuisine": "fast_food"},
            )
        text = str(result)
        assert "Added avoid: fast_food" in text

        cuisines = await db.get_cuisine_preferences()
        assert len(cuisines) == 1
        assert cuisines[0].cuisine == "fast_food"
        assert cuisines[0].category == CuisineCategory.AVOID

    async def test_update_noise_preference(self, patched_mcp):
        mcp, db, _ = patched_mcp
        await db.save_preferences(UserPreferences(name="Alice"))

        async with Client(mcp) as client:
            result = await client.call_tool(
                "update_preferences",
                {"noise_preference": "quiet"},
            )
        text = str(result)
        assert "Noise: quiet" in text

        prefs = await db.get_preferences()
        assert prefs is not None
        assert prefs.noise_preference.value == "quiet"

    async def test_update_seating_preference(self, patched_mcp):
        mcp, db, _ = patched_mcp
        await db.save_preferences(UserPreferences(name="Alice"))

        async with Client(mcp) as client:
            result = await client.call_tool(
                "update_preferences",
                {"seating_preference": "outdoor"},
            )
        text = str(result)
        assert "Seating: outdoor" in text

        prefs = await db.get_preferences()
        assert prefs is not None
        assert prefs.seating_preference.value == "outdoor"

    async def test_update_rating_threshold(self, patched_mcp):
        mcp, db, _ = patched_mcp
        await db.save_preferences(UserPreferences(name="Alice"))

        async with Client(mcp) as client:
            result = await client.call_tool(
                "update_preferences",
                {"rating_threshold": 3.5},
            )
        text = str(result)
        assert "Min rating: 3.5" in text

        prefs = await db.get_preferences()
        assert prefs is not None
        assert prefs.rating_threshold == 3.5

    async def test_update_default_party_size(self, patched_mcp):
        mcp, db, _ = patched_mcp
        await db.save_preferences(UserPreferences(name="Alice"))

        async with Client(mcp) as client:
            result = await client.call_tool(
                "update_preferences",
                {"default_party_size": 8},
            )
        text = str(result)
        assert "Party size: 8" in text

        prefs = await db.get_preferences()
        assert prefs is not None
        assert prefs.default_party_size == 8

    async def test_update_max_walk_minutes(self, patched_mcp):
        mcp, db, _ = patched_mcp
        await db.save_preferences(UserPreferences(name="Alice"))

        async with Client(mcp) as client:
            result = await client.call_tool(
                "update_preferences",
                {"max_walk_minutes": 30},
            )
        text = str(result)
        assert "Walk: 30min" in text

        prefs = await db.get_preferences()
        assert prefs is not None
        assert prefs.max_walk_minutes == 30

    async def test_update_multiple_scalar_fields(self, patched_mcp):
        mcp, db, _ = patched_mcp
        await db.save_preferences(UserPreferences(name="Alice"))

        async with Client(mcp) as client:
            result = await client.call_tool(
                "update_preferences",
                {
                    "noise_preference": "lively",
                    "seating_preference": "indoor",
                    "rating_threshold": 4.8,
                    "default_party_size": 3,
                    "max_walk_minutes": 10,
                },
            )
        text = str(result)
        assert "Noise: lively" in text
        assert "Seating: indoor" in text
        assert "Min rating: 4.8" in text
        assert "Party size: 3" in text
        assert "Walk: 10min" in text

        prefs = await db.get_preferences()
        assert prefs is not None
        assert prefs.noise_preference.value == "lively"
        assert prefs.seating_preference.value == "indoor"
        assert prefs.rating_threshold == 4.8
        assert prefs.default_party_size == 3
        assert prefs.max_walk_minutes == 10

    async def test_no_changes_specified(self, patched_mcp):
        mcp, db, _ = patched_mcp
        await db.save_preferences(UserPreferences(name="Alice"))

        async with Client(mcp) as client:
            result = await client.call_tool(
                "update_preferences", {}
            )
        text = str(result)
        assert "No changes specified" in text

    async def test_add_and_remove_cuisine_same_call(
        self, patched_mcp
    ):
        """Both add_favorite and remove_favorite in one call."""
        mcp, db, _ = patched_mcp
        await db.save_preferences(UserPreferences(name="Alice"))
        await db.set_cuisine_preferences([
            CuisinePreference(
                cuisine="italian",
                category=CuisineCategory.FAVORITE,
            ),
        ])

        async with Client(mcp) as client:
            result = await client.call_tool(
                "update_preferences",
                {
                    "add_favorite_cuisine": "korean",
                    "remove_favorite_cuisine": "italian",
                },
            )
        text = str(result)
        assert "Added favorite: korean" in text
        assert "Removed favorite: italian" in text

        cuisines = await db.get_cuisine_preferences()
        names = [c.cuisine for c in cuisines]
        assert "korean" in names
        assert "italian" not in names

    async def test_add_favorite_and_avoid_same_call(
        self, patched_mcp
    ):
        mcp, db, _ = patched_mcp
        await db.save_preferences(UserPreferences(name="Alice"))

        async with Client(mcp) as client:
            result = await client.call_tool(
                "update_preferences",
                {
                    "add_favorite_cuisine": "sushi",
                    "add_avoid_cuisine": "fast_food",
                },
            )
        text = str(result)
        assert "Added favorite: sushi" in text
        assert "Added avoid: fast_food" in text

        cuisines = await db.get_cuisine_preferences()
        by_cuisine = {c.cuisine: c.category for c in cuisines}
        assert by_cuisine["sushi"] == CuisineCategory.FAVORITE
        assert by_cuisine["fast_food"] == CuisineCategory.AVOID

    async def test_cuisine_update_preserves_existing(
        self, patched_mcp
    ):
        """Adding a cuisine keeps existing ones."""
        mcp, db, _ = patched_mcp
        await db.save_preferences(UserPreferences(name="Alice"))
        await db.set_cuisine_preferences([
            CuisinePreference(
                cuisine="italian",
                category=CuisineCategory.FAVORITE,
            ),
            CuisinePreference(
                cuisine="fast_food",
                category=CuisineCategory.AVOID,
            ),
        ])

        async with Client(mcp) as client:
            await client.call_tool(
                "update_preferences",
                {"add_favorite_cuisine": "thai"},
            )

        cuisines = await db.get_cuisine_preferences()
        names = {c.cuisine for c in cuisines}
        assert names == {"italian", "fast_food", "thai"}

    async def test_dietary_and_scalar_combined(self, patched_mcp):
        """Update dietary and scalars in one call."""
        mcp, db, _ = patched_mcp
        await db.save_preferences(UserPreferences(name="Alice"))

        async with Client(mcp) as client:
            result = await client.call_tool(
                "update_preferences",
                {
                    "dietary_restrictions": ["kosher"],
                    "noise_preference": "lively",
                },
            )
        text = str(result)
        assert "Dietary: kosher" in text
        assert "Noise: lively" in text

    async def test_scalar_not_saved_when_no_scalar_changes(
        self, patched_mcp
    ):
        """Only dietary changed -> prefs unchanged."""
        mcp, db, _ = patched_mcp
        await db.save_preferences(UserPreferences(name="Alice"))

        async with Client(mcp) as client:
            result = await client.call_tool(
                "update_preferences",
                {"dietary_restrictions": ["halal"]},
            )
        text = str(result)
        assert "Updated: Dietary: halal" in text

        prefs = await db.get_preferences()
        assert prefs is not None
        assert prefs.name == "Alice"
        assert prefs.noise_preference.value == "moderate"

    async def test_empty_dietary_replaces_existing(
        self, patched_mcp
    ):
        """Setting dietary_restrictions=[] clears them."""
        mcp, db, _ = patched_mcp
        await db.save_preferences(UserPreferences(name="Alice"))
        await db.set_dietary_restrictions(["vegan"])

        async with Client(mcp) as client:
            result = await client.call_tool(
                "update_preferences",
                {"dietary_restrictions": []},
            )
        text = str(result)
        assert "Dietary: " in text

        restrictions = await db.get_dietary_restrictions()
        assert restrictions == []
