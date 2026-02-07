from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import Client, FastMCP

from src.models.enums import CuisineCategory, PriceLevel
from src.models.restaurant import Restaurant
from src.models.user import CuisinePreference, PricePreference
from src.tools.search import _format_result, register_search_tools
from tests.factories import make_location, make_restaurant, make_user_preferences

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_settings():
    """Mock settings with a test Google API key."""
    return type("Settings", (), {"google_api_key": "test-key"})()


@pytest.fixture
async def search_mcp(db, mock_settings):
    """Return (mcp, db) with get_db and get_settings patched."""
    test_mcp = FastMCP("test")
    db_patch = patch("src.tools.search.get_db", return_value=db)
    settings_patch = patch(
        "src.config.get_settings", return_value=mock_settings
    )
    db_patch.start()
    settings_patch.start()
    register_search_tools(test_mcp)
    yield test_mcp, db
    db_patch.stop()
    settings_patch.stop()


def _make_places_client_mock(restaurants: list[Restaurant]) -> MagicMock:
    """Create a mock GooglePlacesClient whose search_nearby returns restaurants."""
    mock_client = MagicMock()
    mock_client.search_nearby = AsyncMock(return_value=restaurants)
    mock_class = MagicMock(return_value=mock_client)
    return mock_class


# ── _format_result tests ──────────────────────────────────────────────────────


class TestFormatResult:
    def test_basic_restaurant_with_all_fields(self):
        r = make_restaurant(
            name="Carbone",
            address="181 Thompson St, New York, NY 10012",
            rating=4.7,
            review_count=1200,
            price_level=4,
            cuisine=["italian"],
        )
        result = _format_result(1, r, 8)
        assert "1. Carbone (4.7\u2605, $$$$)" in result
        assert "~8 min walk" in result
        assert "181 Thompson St" in result
        assert "Cuisine: italian" in result

    def test_restaurant_no_rating_shows_question_mark(self):
        r = make_restaurant(rating=None)
        result = _format_result(1, r, 5)
        assert "(?\u2605" in result

    def test_restaurant_no_price_level_shows_question_mark(self):
        r = make_restaurant(price_level=None)
        result = _format_result(1, r, 5)
        assert "?)" in result

    def test_restaurant_no_walk_time_no_walk_string(self):
        r = make_restaurant()
        result = _format_result(1, r, None)
        assert "min walk" not in result

    def test_restaurant_with_resy_venue_id(self):
        r = make_restaurant(resy_venue_id="resy123")
        result = _format_result(1, r, 5)
        assert "Available on: Resy" in result

    def test_restaurant_with_opentable_id(self):
        r = make_restaurant(opentable_id="ot456")
        result = _format_result(1, r, 5)
        assert "Available on: OpenTable" in result

    def test_restaurant_with_both_platforms(self):
        r = make_restaurant(resy_venue_id="resy123", opentable_id="ot456")
        result = _format_result(1, r, 5)
        assert "Available on: Resy, OpenTable" in result

    def test_restaurant_no_cuisine_no_cuisine_line(self):
        r = make_restaurant(cuisine=[])
        result = _format_result(1, r, 5)
        assert "Cuisine" not in result

    def test_review_count_does_not_appear_in_output(self):
        """review_str is computed but not included in the formatted lines."""
        r = make_restaurant(review_count=500)
        result = _format_result(1, r, 5)
        # review_count is not currently rendered in the output
        assert "reviews" not in result

    def test_no_review_count_no_reviews_text(self):
        r = make_restaurant(review_count=None)
        result = _format_result(1, r, 5)
        assert "reviews" not in result

    def test_no_platforms_no_available_on_line(self):
        r = make_restaurant(resy_venue_id=None, opentable_id=None, cuisine=[])
        result = _format_result(1, r, 5)
        # With no cuisine and no platforms, no third line
        lines = result.strip().split("\n")
        assert len(lines) == 2  # name line + address line only

    def test_price_symbols_map_correctly(self):
        for level, symbol in [(1, "$"), (2, "$$"), (3, "$$$"), (4, "$$$$")]:
            r = make_restaurant(price_level=level)
            result = _format_result(1, r, 5)
            assert f", {symbol})" in result


# ── search_restaurants tool tests ─────────────────────────────────────────────


class TestSearchRestaurants:
    async def test_basic_search_with_saved_home_location(self, search_mcp):
        mcp, db = search_mcp
        home = make_location(name="home", lat=40.7128, lng=-74.0060)
        await db.save_location(home)
        await db.save_preferences(make_user_preferences(name="Alice"))

        restaurants = [
            make_restaurant(
                name="Pasta Place",
                lat=40.7130,
                lng=-74.0058,
                rating=4.6,
            )
        ]
        mock_class = _make_places_client_mock(restaurants)

        with patch("src.tools.search.GooglePlacesClient", mock_class):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "search_restaurants", {"location": "home"}
                )
        text = str(result)
        assert "Pasta Place" in text
        assert "near home" in text

    async def test_search_unknown_location_falls_back_to_geocode(
        self, search_mcp
    ):
        mcp, db = search_mcp
        await db.save_preferences(make_user_preferences(name="Alice"))

        restaurants = [make_restaurant(name="Corner Bistro", rating=4.5)]
        mock_class = _make_places_client_mock(restaurants)

        with (
            patch("src.tools.search.GooglePlacesClient", mock_class),
            patch(
                "src.tools.search.geocode_address",
                new_callable=AsyncMock,
                return_value=(40.7300, -73.9950),
            ) as geo_mock,
        ):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "search_restaurants",
                    {"location": "123 Main St, New York"},
                )
        text = str(result)
        assert "Corner Bistro" in text
        geo_mock.assert_called_once_with("123 Main St, New York", "test-key")

    async def test_search_geocode_failure_returns_error(self, search_mcp):
        mcp, db = search_mcp

        with patch(
            "src.tools.search.geocode_address",
            new_callable=AsyncMock,
            return_value=None,
        ):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "search_restaurants",
                    {"location": "invalid place xyz"},
                )
        text = str(result)
        assert "Could not resolve location" in text
        assert "invalid place xyz" in text

    async def test_cuisine_parameter_builds_correct_query(self, search_mcp):
        mcp, db = search_mcp
        home = make_location(name="home")
        await db.save_location(home)
        await db.save_preferences(make_user_preferences(name="Alice"))

        restaurants = [make_restaurant(name="Sushi Spot", rating=4.5)]
        mock_client = MagicMock()
        mock_client.search_nearby = AsyncMock(return_value=restaurants)
        mock_class = MagicMock(return_value=mock_client)

        with patch("src.tools.search.GooglePlacesClient", mock_class):
            async with Client(mcp) as client:
                await client.call_tool(
                    "search_restaurants", {"cuisine": "sushi"}
                )
        # Verify the search query
        call_kwargs = mock_client.search_nearby.call_args
        assert call_kwargs.kwargs["query"] == "sushi restaurant"

    async def test_query_parameter_uses_query_new_york(self, search_mcp):
        mcp, db = search_mcp
        home = make_location(name="home")
        await db.save_location(home)
        await db.save_preferences(make_user_preferences(name="Alice"))

        restaurants = [make_restaurant(name="Rooftop Bar", rating=4.5)]
        mock_client = MagicMock()
        mock_client.search_nearby = AsyncMock(return_value=restaurants)
        mock_class = MagicMock(return_value=mock_client)

        with patch("src.tools.search.GooglePlacesClient", mock_class):
            async with Client(mcp) as client:
                await client.call_tool(
                    "search_restaurants", {"query": "rooftop bar"}
                )
        call_kwargs = mock_client.search_nearby.call_args
        assert call_kwargs.kwargs["query"] == "rooftop bar New York"

    async def test_no_cuisine_no_query_uses_restaurant(self, search_mcp):
        mcp, db = search_mcp
        home = make_location(name="home")
        await db.save_location(home)
        await db.save_preferences(make_user_preferences(name="Alice"))

        restaurants = [make_restaurant(name="Generic Place", rating=4.5)]
        mock_client = MagicMock()
        mock_client.search_nearby = AsyncMock(return_value=restaurants)
        mock_class = MagicMock(return_value=mock_client)

        with patch("src.tools.search.GooglePlacesClient", mock_class):
            async with Client(mcp) as client:
                await client.call_tool("search_restaurants", {})
        call_kwargs = mock_client.search_nearby.call_args
        assert call_kwargs.kwargs["query"] == "restaurant"

    async def test_outdoor_seating_appends_to_query(self, search_mcp):
        mcp, db = search_mcp
        home = make_location(name="home")
        await db.save_location(home)
        await db.save_preferences(make_user_preferences(name="Alice"))

        restaurants = [make_restaurant(name="Patio Place", rating=4.5)]
        mock_client = MagicMock()
        mock_client.search_nearby = AsyncMock(return_value=restaurants)
        mock_class = MagicMock(return_value=mock_client)

        with patch("src.tools.search.GooglePlacesClient", mock_class):
            async with Client(mcp) as client:
                await client.call_tool(
                    "search_restaurants",
                    {"cuisine": "italian", "outdoor_seating": True},
                )
        call_kwargs = mock_client.search_nearby.call_args
        assert call_kwargs.kwargs["query"] == "italian restaurant outdoor seating"

    async def test_max_results_capped_at_10(self, search_mcp):
        mcp, db = search_mcp
        home = make_location(name="home")
        await db.save_location(home)
        await db.save_preferences(make_user_preferences(name="Alice"))

        # Create 15 restaurants
        restaurants = [
            make_restaurant(
                id=f"place_{i}",
                name=f"Restaurant {i}",
                rating=4.5,
                lat=40.7128 + i * 0.0001,
                lng=-74.0060,
            )
            for i in range(15)
        ]
        mock_class = _make_places_client_mock(restaurants)

        with patch("src.tools.search.GooglePlacesClient", mock_class):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "search_restaurants", {"max_results": 20}
                )
        text = str(result)
        assert "Found 10" in text

    async def test_blacklisted_restaurants_excluded(self, search_mcp):
        mcp, db = search_mcp
        home = make_location(name="home")
        await db.save_location(home)
        await db.save_preferences(make_user_preferences(name="Alice"))

        good_restaurant = make_restaurant(
            id="place_good", name="Good Place", rating=4.5
        )
        bad_restaurant = make_restaurant(
            id="place_bad", name="Bad Place", rating=4.8
        )
        await db.add_to_blacklist("place_bad", "Bad Place", "terrible service")

        mock_class = _make_places_client_mock([good_restaurant, bad_restaurant])

        with patch("src.tools.search.GooglePlacesClient", mock_class):
            async with Client(mcp) as client:
                result = await client.call_tool("search_restaurants", {})
        text = str(result)
        assert "Good Place" in text
        assert "Bad Place" not in text

    async def test_low_rated_restaurants_filtered(self, search_mcp):
        mcp, db = search_mcp
        home = make_location(name="home")
        await db.save_location(home)
        await db.save_preferences(
            make_user_preferences(name="Alice", rating_threshold=4.0)
        )

        high_rated = make_restaurant(
            id="place_high", name="High Rated", rating=4.5
        )
        low_rated = make_restaurant(
            id="place_low", name="Low Rated", rating=3.5
        )
        # Restaurant with no rating should pass through (rating is None)
        no_rating = make_restaurant(
            id="place_none", name="No Rating", rating=None
        )

        mock_class = _make_places_client_mock(
            [high_rated, low_rated, no_rating]
        )

        with patch("src.tools.search.GooglePlacesClient", mock_class):
            async with Client(mcp) as client:
                result = await client.call_tool("search_restaurants", {})
        text = str(result)
        assert "High Rated" in text
        assert "Low Rated" not in text
        assert "No Rating" in text

    async def test_price_filter_by_price_max(self, search_mcp):
        mcp, db = search_mcp
        home = make_location(name="home")
        await db.save_location(home)
        await db.save_preferences(make_user_preferences(name="Alice"))

        cheap = make_restaurant(
            id="place_cheap", name="Budget Eats", rating=4.5, price_level=1
        )
        mid = make_restaurant(
            id="place_mid", name="Mid Range", rating=4.5, price_level=2
        )
        expensive = make_restaurant(
            id="place_exp", name="Fancy Place", rating=4.5, price_level=4
        )
        no_price = make_restaurant(
            id="place_noprice",
            name="No Price",
            rating=4.5,
            price_level=None,
        )

        mock_class = _make_places_client_mock(
            [cheap, mid, expensive, no_price]
        )

        with patch("src.tools.search.GooglePlacesClient", mock_class):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "search_restaurants", {"price_max": 2}
                )
        text = str(result)
        assert "Budget Eats" in text
        assert "Mid Range" in text
        assert "Fancy Place" not in text
        # No price level restaurants pass through (no price to reject)
        assert "No Price" in text

    async def test_price_filter_by_saved_preferences(self, search_mcp):
        mcp, db = search_mcp
        home = make_location(name="home")
        await db.save_location(home)
        await db.save_preferences(make_user_preferences(name="Alice"))
        await db.set_price_preferences([
            PricePreference(price_level=PriceLevel.BUDGET, acceptable=True),
            PricePreference(price_level=PriceLevel.MODERATE, acceptable=True),
            PricePreference(price_level=PriceLevel.UPSCALE, acceptable=False),
        ])

        cheap = make_restaurant(
            id="place_cheap", name="Budget Eats", rating=4.5, price_level=1
        )
        upscale = make_restaurant(
            id="place_upscale",
            name="Upscale Place",
            rating=4.5,
            price_level=3,
        )

        mock_class = _make_places_client_mock([cheap, upscale])

        with patch("src.tools.search.GooglePlacesClient", mock_class):
            async with Client(mcp) as client:
                result = await client.call_tool("search_restaurants", {})
        text = str(result)
        assert "Budget Eats" in text
        assert "Upscale Place" not in text

    async def test_avoided_cuisines_filtered(self, search_mcp):
        mcp, db = search_mcp
        home = make_location(name="home")
        await db.save_location(home)
        await db.save_preferences(make_user_preferences(name="Alice"))
        await db.set_cuisine_preferences([
            CuisinePreference(
                cuisine="fast_food", category=CuisineCategory.AVOID
            ),
        ])

        good = make_restaurant(
            id="place_italian",
            name="Italian Place",
            rating=4.5,
            cuisine=["italian"],
        )
        avoided = make_restaurant(
            id="place_ff",
            name="Fast Food Joint",
            rating=4.5,
            cuisine=["fast_food"],
        )

        mock_class = _make_places_client_mock([good, avoided])

        with patch("src.tools.search.GooglePlacesClient", mock_class):
            async with Client(mcp) as client:
                result = await client.call_tool("search_restaurants", {})
        text = str(result)
        assert "Italian Place" in text
        assert "Fast Food Joint" not in text

    async def test_no_results_returns_no_restaurants_message(
        self, search_mcp
    ):
        mcp, db = search_mcp
        home = make_location(name="home")
        await db.save_location(home)
        await db.save_preferences(make_user_preferences(name="Alice"))

        mock_class = _make_places_client_mock([])

        with patch("src.tools.search.GooglePlacesClient", mock_class):
            async with Client(mcp) as client:
                result = await client.call_tool("search_restaurants", {})
        text = str(result)
        assert "No restaurants found" in text

    async def test_results_sorted_by_rating_desc_then_distance(
        self, search_mcp
    ):
        mcp, db = search_mcp
        home = make_location(name="home", lat=40.7128, lng=-74.0060)
        await db.save_location(home)
        await db.save_preferences(make_user_preferences(name="Alice"))

        # Same rating, different distance
        close = make_restaurant(
            id="place_close",
            name="Close Place",
            rating=4.5,
            lat=40.7129,
            lng=-74.0059,
        )
        far = make_restaurant(
            id="place_far",
            name="Far Place",
            rating=4.5,
            lat=40.7200,
            lng=-73.9900,
        )
        # Higher rating should come first regardless of distance
        best = make_restaurant(
            id="place_best",
            name="Best Place",
            rating=4.9,
            lat=40.7200,
            lng=-73.9900,
        )

        mock_class = _make_places_client_mock([far, close, best])

        with patch("src.tools.search.GooglePlacesClient", mock_class):
            async with Client(mcp) as client:
                result = await client.call_tool("search_restaurants", {})
        text = str(result)
        # Best rating (4.9) first, then same-rated sorted by distance
        best_pos = text.index("Best Place")
        close_pos = text.index("Close Place")
        far_pos = text.index("Far Place")
        assert best_pos < close_pos < far_pos

    async def test_single_result_uses_singular_restaurant(self, search_mcp):
        mcp, db = search_mcp
        home = make_location(name="home")
        await db.save_location(home)
        await db.save_preferences(make_user_preferences(name="Alice"))

        restaurants = [make_restaurant(name="Solo Spot", rating=4.5)]
        mock_class = _make_places_client_mock(restaurants)

        with patch("src.tools.search.GooglePlacesClient", mock_class):
            async with Client(mcp) as client:
                result = await client.call_tool("search_restaurants", {})
        text = str(result)
        assert "Found 1 restaurant near" in text
        # Should NOT say "restaurants" (plural)
        assert "Found 1 restaurants" not in text

    async def test_multiple_results_uses_plural_restaurants(
        self, search_mcp
    ):
        mcp, db = search_mcp
        home = make_location(name="home")
        await db.save_location(home)
        await db.save_preferences(make_user_preferences(name="Alice"))

        restaurants = [
            make_restaurant(
                id=f"place_{i}", name=f"Place {i}", rating=4.5
            )
            for i in range(3)
        ]
        mock_class = _make_places_client_mock(restaurants)

        with patch("src.tools.search.GooglePlacesClient", mock_class):
            async with Client(mcp) as client:
                result = await client.call_tool("search_restaurants", {})
        text = str(result)
        assert "Found 3 restaurants near" in text

    async def test_cuisine_label_in_header_when_cuisine_specified(
        self, search_mcp
    ):
        mcp, db = search_mcp
        home = make_location(name="home")
        await db.save_location(home)
        await db.save_preferences(make_user_preferences(name="Alice"))

        restaurants = [
            make_restaurant(name="Mario's", rating=4.5, cuisine=["italian"])
        ]
        mock_class = _make_places_client_mock(restaurants)

        with patch("src.tools.search.GooglePlacesClient", mock_class):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "search_restaurants", {"cuisine": "italian"}
                )
        text = str(result)
        assert "Found 1 italian restaurant near" in text

    async def test_default_preferences_when_none_saved(self, search_mcp):
        """When no preferences exist, defaults are used (rating 4.0, walk 15)."""
        mcp, db = search_mcp
        home = make_location(name="home")
        await db.save_location(home)
        # No preferences saved -- defaults should apply

        # Restaurant below default threshold of 4.0 should be filtered
        low_rated = make_restaurant(
            id="place_low", name="Low Rated", rating=3.8
        )
        # Restaurant at threshold should pass
        ok_rated = make_restaurant(
            id="place_ok", name="OK Rated", rating=4.0
        )

        mock_class = _make_places_client_mock([low_rated, ok_rated])

        with patch("src.tools.search.GooglePlacesClient", mock_class):
            async with Client(mcp) as client:
                result = await client.call_tool("search_restaurants", {})
        text = str(result)
        assert "Low Rated" not in text
        assert "OK Rated" in text

    async def test_outdoor_seating_with_query(self, search_mcp):
        """outdoor_seating appends to query when query is set."""
        mcp, db = search_mcp
        home = make_location(name="home")
        await db.save_location(home)
        await db.save_preferences(make_user_preferences(name="Alice"))

        restaurants = [make_restaurant(name="Outdoor Place", rating=4.5)]
        mock_client = MagicMock()
        mock_client.search_nearby = AsyncMock(return_value=restaurants)
        mock_class = MagicMock(return_value=mock_client)

        with patch("src.tools.search.GooglePlacesClient", mock_class):
            async with Client(mcp) as client:
                await client.call_tool(
                    "search_restaurants",
                    {"query": "brunch", "outdoor_seating": True},
                )
        call_kwargs = mock_client.search_nearby.call_args
        assert (
            call_kwargs.kwargs["query"] == "brunch New York outdoor seating"
        )

    async def test_outdoor_seating_with_no_cuisine_no_query(
        self, search_mcp
    ):
        """outdoor_seating appends to default 'restaurant' query."""
        mcp, db = search_mcp
        home = make_location(name="home")
        await db.save_location(home)
        await db.save_preferences(make_user_preferences(name="Alice"))

        restaurants = [make_restaurant(name="Patio Spot", rating=4.5)]
        mock_client = MagicMock()
        mock_client.search_nearby = AsyncMock(return_value=restaurants)
        mock_class = MagicMock(return_value=mock_client)

        with patch("src.tools.search.GooglePlacesClient", mock_class):
            async with Client(mcp) as client:
                await client.call_tool(
                    "search_restaurants", {"outdoor_seating": True}
                )
        call_kwargs = mock_client.search_nearby.call_args
        assert call_kwargs.kwargs["query"] == "restaurant outdoor seating"

    async def test_results_cached_in_database(self, search_mcp):
        """Each result from the search is cached via db.cache_restaurant."""
        mcp, db = search_mcp
        home = make_location(name="home")
        await db.save_location(home)
        await db.save_preferences(make_user_preferences(name="Alice"))

        restaurants = [
            make_restaurant(
                id="place_cache1", name="Cached Place", rating=4.5
            )
        ]
        mock_class = _make_places_client_mock(restaurants)

        with patch("src.tools.search.GooglePlacesClient", mock_class):
            async with Client(mcp) as client:
                await client.call_tool("search_restaurants", {})

        # Verify the restaurant was cached
        cached = await db.get_cached_restaurant("place_cache1")
        assert cached is not None
        assert cached.name == "Cached Place"

    async def test_avoided_cuisine_case_insensitive(self, search_mcp):
        """Avoided cuisine matching is case-insensitive."""
        mcp, db = search_mcp
        home = make_location(name="home")
        await db.save_location(home)
        await db.save_preferences(make_user_preferences(name="Alice"))
        await db.set_cuisine_preferences([
            CuisinePreference(
                cuisine="Fast_Food", category=CuisineCategory.AVOID
            ),
        ])

        avoided = make_restaurant(
            id="place_ff",
            name="Fast Food Joint",
            rating=4.5,
            cuisine=["fast_food"],
        )
        mock_class = _make_places_client_mock([avoided])

        with patch("src.tools.search.GooglePlacesClient", mock_class):
            async with Client(mcp) as client:
                result = await client.call_tool("search_restaurants", {})
        text = str(result)
        assert "Fast Food Joint" not in text
        assert "No restaurants found" in text

    async def test_walk_limit_affects_search_radius(self, search_mcp):
        """max_walk_minutes from prefs determines the search radius."""
        mcp, db = search_mcp
        home = make_location(name="home")
        await db.save_location(home)
        await db.save_preferences(
            make_user_preferences(name="Alice", max_walk_minutes=20)
        )

        restaurants = [make_restaurant(name="Nearby", rating=4.5)]
        mock_client = MagicMock()
        mock_client.search_nearby = AsyncMock(return_value=restaurants)
        mock_class = MagicMock(return_value=mock_client)

        with patch("src.tools.search.GooglePlacesClient", mock_class):
            async with Client(mcp) as client:
                await client.call_tool("search_restaurants", {})

        call_kwargs = mock_client.search_nearby.call_args
        expected_radius = int(20 * 83 / 1.3)
        assert call_kwargs.kwargs["radius_meters"] == expected_radius

    async def test_price_max_overrides_saved_price_prefs(self, search_mcp):
        """When price_max is given, saved price preferences are ignored."""
        mcp, db = search_mcp
        home = make_location(name="home")
        await db.save_location(home)
        await db.save_preferences(make_user_preferences(name="Alice"))
        # Saved prefs say only budget is acceptable
        await db.set_price_preferences([
            PricePreference(price_level=PriceLevel.BUDGET, acceptable=True),
        ])

        # price_level=3 restaurant, but price_max=3 should allow it
        upscale = make_restaurant(
            id="place_upscale",
            name="Upscale Place",
            rating=4.5,
            price_level=3,
        )
        mock_class = _make_places_client_mock([upscale])

        with patch("src.tools.search.GooglePlacesClient", mock_class):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "search_restaurants", {"price_max": 3}
                )
        text = str(result)
        assert "Upscale Place" in text

    async def test_favorite_cuisine_pref_not_treated_as_avoided(
        self, search_mcp
    ):
        """Non-avoid cuisine preferences (e.g. favorite) must not filter."""
        mcp, db = search_mcp
        home = make_location(name="home")
        await db.save_location(home)
        await db.save_preferences(make_user_preferences(name="Alice"))
        await db.set_cuisine_preferences([
            CuisinePreference(
                cuisine="italian", category=CuisineCategory.FAVORITE
            ),
            CuisinePreference(
                cuisine="fast_food", category=CuisineCategory.AVOID
            ),
        ])

        italian = make_restaurant(
            id="place_it",
            name="Italian Spot",
            rating=4.5,
            cuisine=["italian"],
        )
        mock_class = _make_places_client_mock([italian])

        with patch("src.tools.search.GooglePlacesClient", mock_class):
            async with Client(mcp) as client:
                result = await client.call_tool("search_restaurants", {})
        text = str(result)
        assert "Italian Spot" in text

    async def test_all_results_filtered_returns_no_restaurants(
        self, search_mcp
    ):
        """When all results are filtered out, returns no-results message."""
        mcp, db = search_mcp
        home = make_location(name="home")
        await db.save_location(home)
        await db.save_preferences(
            make_user_preferences(name="Alice", rating_threshold=4.8)
        )

        low = make_restaurant(id="place_1", name="Low Place", rating=4.0)
        mock_class = _make_places_client_mock([low])

        with patch("src.tools.search.GooglePlacesClient", mock_class):
            async with Client(mcp) as client:
                result = await client.call_tool("search_restaurants", {})
        text = str(result)
        assert "No restaurants found" in text
