"""Tests for recommendation and group dining search tools."""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import Client, FastMCP

from src.models.enums import CuisineCategory
from src.storage.database import DatabaseManager
from src.tools.recommendations import (
    _score_restaurant,
    register_recommendation_tools,
)
from tests.factories import (
    make_cuisine_preference,
    make_group,
    make_location,
    make_person,
    make_restaurant,
    make_user_preferences,
    make_visit,
    make_visit_review,
)

# ── Helpers ──────────────────────────────────────────────────────────────


def _mock_settings(openweather_key=None):
    return type(
        "Settings",
        (),
        {"google_api_key": "test-key", "openweather_api_key": openweather_key},
    )()


def _make_places_mock(restaurants):
    mock_client = MagicMock()
    mock_client.search_nearby = AsyncMock(return_value=restaurants)
    return MagicMock(return_value=mock_client)


async def _setup_rec_db():
    """Create an in-memory DB with a saved 'home' location and user prefs."""
    db = DatabaseManager(":memory:")
    await db.initialize()
    await db.save_location(make_location(name="home", lat=40.71, lng=-74.01))
    await db.save_preferences(make_user_preferences(name="User"))
    return db


def _patches(db, settings=None, restaurants=None, geocode=None):
    """Return a tuple of context managers for common patches."""
    if settings is None:
        settings = _mock_settings()
    if restaurants is None:
        restaurants = []
    patches = [
        patch("src.tools.recommendations.get_db", return_value=db),
        patch("src.config.get_settings", return_value=settings),
        patch(
            "src.tools.recommendations.GooglePlacesClient",
            _make_places_mock(restaurants),
        ),
    ]
    if geocode is not None:
        patches.append(
            patch(
                "src.tools.recommendations.geocode_address",
                AsyncMock(return_value=geocode),
            )
        )
    return patches


# ── Registration ─────────────────────────────────────────────────────────


class TestRegistration:
    def test_registration_succeeds(self):
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)


# ── _score_restaurant ────────────────────────────────────────────────────


class TestScoreRestaurant:
    """Unit tests for the scoring function."""

    async def test_base_rating_score(self):
        r = make_restaurant(rating=4.5, lat=40.71, lng=-74.01)
        score, _ = await _score_restaurant(
            r, 40.71, -74.01, None, set(), set(), set(), {}, {}
        )
        # Base: 4.5 * 10 = 45, minus tiny distance penalty
        assert score == pytest.approx(45.0, abs=1.0)

    async def test_no_rating(self):
        r = make_restaurant(rating=None, lat=40.71, lng=-74.01)
        score, _ = await _score_restaurant(
            r, 40.71, -74.01, None, set(), set(), set(), {}, {}
        )
        assert score <= 0

    async def test_favorite_cuisine_bonus(self):
        r = make_restaurant(rating=4.0, cuisine=["italian"], lat=40.71, lng=-74.01)
        score, reason = await _score_restaurant(
            r, 40.71, -74.01, None, {"italian"}, set(), set(), {}, {}
        )
        assert "Matches your favorite cuisines" in reason
        # 4.0*10 + 20 = 60, minus distance
        assert score > 55

    async def test_liked_cuisine_bonus(self):
        r = make_restaurant(rating=4.0, cuisine=["thai"], lat=40.71, lng=-74.01)
        score, reason = await _score_restaurant(
            r, 40.71, -74.01, None, set(), {"thai"}, set(), {}, {}
        )
        assert "A cuisine you enjoy" in reason

    async def test_avoided_cuisine_penalty(self):
        r = make_restaurant(rating=4.0, cuisine=["sushi"], lat=40.71, lng=-74.01)
        score, _ = await _score_restaurant(
            r, 40.71, -74.01, None, set(), set(), {"sushi"}, {}, {}
        )
        # 40 - 100 = -60 minus distance
        assert score < -50

    async def test_no_cuisine_match(self):
        """Restaurant cuisine doesn't match any preference set."""
        r = make_restaurant(rating=4.0, cuisine=["korean"], lat=40.71, lng=-74.01)
        score, _ = await _score_restaurant(
            r, 40.71, -74.01, None, {"italian"}, {"thai"}, {"sushi"}, {}, {}
        )
        # Just base rating, no cuisine bonus
        assert 35 < score < 45

    async def test_no_cuisine_on_restaurant(self):
        r = make_restaurant(rating=4.0, cuisine=[], lat=40.71, lng=-74.01)
        score, reason = await _score_restaurant(
            r, 40.71, -74.01, None, set(), set(), set(), {}, {}
        )
        assert reason == "Nearby option"

    async def test_recency_penalty(self):
        r = make_restaurant(rating=4.0, cuisine=["italian"], lat=40.71, lng=-74.01)
        penalties = {"italian": 0.8}
        score, _ = await _score_restaurant(
            r, 40.71, -74.01, None, set(), set(), set(), penalties, {}
        )
        # 40 - 0.8*30 = 16, minus distance
        assert score < 20

    async def test_recency_no_matching_penalty(self):
        r = make_restaurant(rating=4.0, cuisine=["italian"], lat=40.71, lng=-74.01)
        penalties = {"thai": 0.9}
        score, _ = await _score_restaurant(
            r, 40.71, -74.01, None, set(), set(), set(), penalties, {}
        )
        # No penalty, just base rating
        assert score > 35

    async def test_would_return_with_rating(self):
        r = make_restaurant(id="place_1", rating=4.0, lat=40.71, lng=-74.01)
        review_map = {"place_1": {"would_return": True, "overall_rating": 4}}
        _, reason = await _score_restaurant(
            r, 40.71, -74.01, None, set(), set(), set(), {}, review_map
        )
        assert "You rated it 4/5 last time" in reason

    async def test_would_return_without_rating(self):
        r = make_restaurant(id="place_1", rating=4.0, lat=40.71, lng=-74.01)
        review_map = {"place_1": {"would_return": True, "overall_rating": None}}
        _, reason = await _score_restaurant(
            r, 40.71, -74.01, None, set(), set(), set(), {}, review_map
        )
        assert "You'd return based on your last visit" in reason

    async def test_would_not_return(self):
        r = make_restaurant(id="place_1", rating=4.0, lat=40.71, lng=-74.01)
        review_map = {"place_1": {"would_return": False}}
        score, reason = await _score_restaurant(
            r, 40.71, -74.01, None, set(), set(), set(), {}, review_map
        )
        assert "wouldn't return" in reason
        assert score < 0

    async def test_occasion_min_price(self):
        """date_night has min_price=3; restaurant with price_level=3 gets +10."""
        r = make_restaurant(
            rating=4.5, price_level=3, lat=40.71, lng=-74.01, cuisine=[]
        )
        score_with, _ = await _score_restaurant(
            r, 40.71, -74.01, "date_night", set(), set(), set(), {}, {}
        )
        score_without, _ = await _score_restaurant(
            r, 40.71, -74.01, None, set(), set(), set(), {}, {}
        )
        assert score_with > score_without

    async def test_occasion_max_price(self):
        """quick has max_price=2; restaurant with price_level=2 gets +10."""
        r = make_restaurant(
            rating=4.0, price_level=2, lat=40.71, lng=-74.01, cuisine=[]
        )
        score_with, _ = await _score_restaurant(
            r, 40.71, -74.01, "quick", set(), set(), set(), {}, {}
        )
        score_without, _ = await _score_restaurant(
            r, 40.71, -74.01, None, set(), set(), set(), {}, {}
        )
        assert score_with > score_without

    async def test_unknown_occasion(self):
        """Unknown occasion name results in empty filters (no crash)."""
        r = make_restaurant(rating=4.0, lat=40.71, lng=-74.01)
        score, _ = await _score_restaurant(
            r, 40.71, -74.01, "brunch", set(), set(), set(), {}, {}
        )
        assert score > 0

    async def test_no_reasons_high_rating(self):
        r = make_restaurant(rating=4.6, cuisine=["italian"], lat=40.71, lng=-74.01)
        _, reason = await _score_restaurant(
            r, 40.71, -74.01, None, set(), set(), set(), {}, {}
        )
        assert "Highly rated" in reason

    async def test_no_reasons_cuisine_nearby(self):
        r = make_restaurant(rating=4.0, cuisine=["italian"], lat=40.71, lng=-74.01)
        _, reason = await _score_restaurant(
            r, 40.71, -74.01, None, set(), set(), set(), {}, {}
        )
        assert "italian" in reason
        assert "nearby" in reason

    async def test_no_reasons_no_cuisine_no_rating(self):
        r = make_restaurant(rating=None, cuisine=[], lat=40.71, lng=-74.01)
        _, reason = await _score_restaurant(
            r, 40.71, -74.01, None, set(), set(), set(), {}, {}
        )
        assert reason == "Nearby option"

    async def test_wishlist_boost(self):
        r = make_restaurant(id="wish_place", rating=4.0, lat=40.71, lng=-74.01)
        score_with, reason_with = await _score_restaurant(
            r, 40.71, -74.01, None, set(), set(), set(), {}, {},
            wishlist_ids={"wish_place"},
        )
        score_without, _ = await _score_restaurant(
            r, 40.71, -74.01, None, set(), set(), set(), {}, {},
        )
        assert score_with - score_without == pytest.approx(15.0, abs=0.1)
        assert "On your wishlist" in reason_with

    async def test_no_wishlist_boost(self):
        r = make_restaurant(id="other_place", rating=4.0, lat=40.71, lng=-74.01)
        score, reason = await _score_restaurant(
            r, 40.71, -74.01, None, set(), set(), set(), {}, {},
            wishlist_ids={"wish_place"},
        )
        assert "wishlist" not in reason.lower()
        # Score should be the same as without wishlist_ids
        score_base, _ = await _score_restaurant(
            r, 40.71, -74.01, None, set(), set(), set(), {}, {},
        )
        assert score == pytest.approx(score_base, abs=0.1)


# ── get_recommendations ──────────────────────────────────────────────────


class TestGetRecommendations:
    """Integration tests for the get_recommendations tool."""

    async def test_basic_with_saved_location(self):
        db = await _setup_rec_db()
        r1 = make_restaurant(name="Good Place", rating=4.5)
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([r1]),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool("get_recommendations", {})
        text = str(result)
        assert "Good Place" in text
        assert "My picks" in text
        await db.close()

    async def test_geocoded_location(self):
        db = await _setup_rec_db()
        r1 = make_restaurant(name="Geo Place", rating=4.5)
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([r1]),
            ),
            patch(
                "src.tools.recommendations.geocode_address",
                AsyncMock(return_value=(40.75, -73.99)),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "get_recommendations",
                    {"location": "123 Broadway, NYC"},
                )
        text = str(result)
        assert "Geo Place" in text
        await db.close()

    async def test_location_not_found(self):
        db = await _setup_rec_db()
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.geocode_address",
                AsyncMock(return_value=None),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "get_recommendations",
                    {"location": "middle of nowhere"},
                )
        text = str(result)
        assert "Could not resolve location" in text
        await db.close()

    async def test_no_results(self):
        db = await _setup_rec_db()
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([]),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool("get_recommendations", {})
        text = str(result)
        assert "No recommendations found" in text
        await db.close()

    async def test_occasion_date_night(self):
        db = await _setup_rec_db()
        r1 = make_restaurant(name="Romantic Spot", rating=4.5, price_level=3)
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        mock_class = _make_places_mock([r1])
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch("src.tools.recommendations.GooglePlacesClient", mock_class),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "get_recommendations",
                    {"occasion": "date_night"},
                )
        text = str(result)
        assert "date night" in text
        # Verify query was "romantic restaurant"
        call_args = mock_class.return_value.search_nearby.call_args
        assert "romantic" in call_args.kwargs.get("query", call_args[1].get("query", ""))

    async def test_occasion_special(self):
        db = await _setup_rec_db()
        r1 = make_restaurant(name="Fine Dining", rating=4.8, price_level=4)
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        mock_class = _make_places_mock([r1])
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch("src.tools.recommendations.GooglePlacesClient", mock_class),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "get_recommendations",
                    {"occasion": "special"},
                )
        text = str(result)
        assert "special" in text

    async def test_occasion_quick(self):
        db = await _setup_rec_db()
        r1 = make_restaurant(name="Quick Bite", rating=4.0, price_level=1)
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        mock_class = _make_places_mock([r1])
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch("src.tools.recommendations.GooglePlacesClient", mock_class),
        ):
            async with Client(mcp) as client:
                await client.call_tool(
                    "get_recommendations",
                    {"occasion": "quick"},
                )

    async def test_weather_note_shown(self):
        db = await _setup_rec_db()
        r1 = make_restaurant(name="Weather Place", rating=4.5)
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        mock_weather = MagicMock()
        mock_weather.outdoor_suitable = True
        mock_weather.temperature_f = 72.0
        mock_wc = MagicMock(return_value=MagicMock(
            get_weather=AsyncMock(return_value=mock_weather)
        ))
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch(
                "src.config.get_settings",
                return_value=_mock_settings(openweather_key="test-key"),
            ),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([r1]),
            ),
            patch("src.clients.weather.WeatherClient", mock_wc),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool("get_recommendations", {})
        text = str(result)
        assert "Great weather for outdoor dining" in text
        assert "72" in text
        await db.close()

    async def test_weather_not_outdoor_suitable(self):
        """When weather is not outdoor suitable, no weather note."""
        db = await _setup_rec_db()
        r1 = make_restaurant(name="Rain Place", rating=4.5)
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        mock_weather = MagicMock()
        mock_weather.outdoor_suitable = False
        mock_wc = MagicMock(return_value=MagicMock(
            get_weather=AsyncMock(return_value=mock_weather)
        ))
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch(
                "src.config.get_settings",
                return_value=_mock_settings(openweather_key="test-key"),
            ),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([r1]),
            ),
            patch("src.clients.weather.WeatherClient", mock_wc),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool("get_recommendations", {})
        text = str(result)
        assert "Great weather" not in text
        await db.close()

    async def test_weather_exception_caught(self):
        db = await _setup_rec_db()
        r1 = make_restaurant(name="Safe Place", rating=4.5)
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        mock_wc = MagicMock(return_value=MagicMock(
            get_weather=AsyncMock(side_effect=RuntimeError("API down"))
        ))
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch(
                "src.config.get_settings",
                return_value=_mock_settings(openweather_key="test-key"),
            ),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([r1]),
            ),
            patch("src.clients.weather.WeatherClient", mock_wc),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool("get_recommendations", {})
        text = str(result)
        assert "Safe Place" in text
        await db.close()

    async def test_blacklisted_excluded(self):
        db = await _setup_rec_db()
        r1 = make_restaurant(id="bad_place", name="Blacklisted", rating=4.5)
        r2 = make_restaurant(id="good_place", name="Good One", rating=4.5)
        await db.add_to_blacklist("bad_place", "Blacklisted", "test")
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([r1, r2]),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool("get_recommendations", {})
        text = str(result)
        assert "Blacklisted" not in text
        assert "Good One" in text
        await db.close()

    async def test_recently_visited_excluded(self):
        db = await _setup_rec_db()
        r1 = make_restaurant(id="visited_place", name="Old News", rating=4.5)
        r2 = make_restaurant(id="new_place", name="New Spot", rating=4.5)
        # Log a recent visit
        visit = make_visit(
            restaurant_id="visited_place",
            restaurant_name="Old News",
            date=date.today().isoformat(),
        )
        await db.log_visit(visit)
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([r1, r2]),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool("get_recommendations", {})
        text = str(result)
        assert "Old News" not in text
        assert "New Spot" in text
        await db.close()

    async def test_recently_visited_would_return_included(self):
        db = await _setup_rec_db()
        r1 = make_restaurant(id="return_place", name="Come Back", rating=4.5)
        visit = make_visit(
            restaurant_id="return_place",
            restaurant_name="Come Back",
            date=date.today().isoformat(),
        )
        visit_id = await db.log_visit(visit)
        review = make_visit_review(
            visit_id=visit_id, would_return=True, overall_rating=5
        )
        await db.save_visit_review(review)
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([r1]),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool("get_recommendations", {})
        text = str(result)
        assert "Come Back" in text
        await db.close()

    async def test_low_rating_filtered(self):
        db = await _setup_rec_db()
        r_low = make_restaurant(name="Low Rated", rating=3.5)
        r_high = make_restaurant(name="High Rated", rating=4.5)
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([r_low, r_high]),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool("get_recommendations", {})
        text = str(result)
        assert "Low Rated" not in text
        assert "High Rated" in text
        await db.close()

    async def test_rating_none_passes_filter(self):
        """Restaurant with None rating is NOT filtered out by rating check."""
        db = await _setup_rec_db()
        r = make_restaurant(name="No Rating Place", rating=None)
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([r]),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool("get_recommendations", {})
        text = str(result)
        assert "No Rating Place" in text
        await db.close()

    async def test_avoided_cuisines_filtered(self):
        db = await _setup_rec_db()
        # Set avoided cuisine
        cp = make_cuisine_preference(
            cuisine="sushi", category=CuisineCategory.AVOID
        )
        await db.set_cuisine_preferences([cp])
        r1 = make_restaurant(name="Sushi Bad", rating=4.5, cuisine=["sushi"])
        r2 = make_restaurant(name="Italian OK", rating=4.5, cuisine=["italian"])
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([r1, r2]),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool("get_recommendations", {})
        text = str(result)
        assert "Sushi Bad" not in text
        assert "Italian OK" in text
        await db.close()

    async def test_price_filter_min(self):
        """date_night min_price=3 filters out price_level=2."""
        db = await _setup_rec_db()
        r_cheap = make_restaurant(name="Cheap Place", rating=4.5, price_level=2)
        r_nice = make_restaurant(name="Nice Place", rating=4.5, price_level=3)
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([r_cheap, r_nice]),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "get_recommendations",
                    {"occasion": "date_night"},
                )
        text = str(result)
        assert "Cheap Place" not in text
        assert "Nice Place" in text
        await db.close()

    async def test_price_filter_max(self):
        """quick max_price=2 filters out price_level=3."""
        db = await _setup_rec_db()
        r_exp = make_restaurant(name="Expensive", rating=4.0, price_level=3)
        r_cheap = make_restaurant(name="Affordable", rating=4.0, price_level=2)
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([r_exp, r_cheap]),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "get_recommendations",
                    {"occasion": "quick"},
                )
        text = str(result)
        assert "Expensive" not in text
        assert "Affordable" in text
        await db.close()

    async def test_group_dietary_restrictions(self):
        db = await _setup_rec_db()
        # Save a person with dietary restrictions
        person = make_person(
            name="Alice", dietary_restrictions=["gluten-free"], no_alcohol=False
        )
        person_id = await db.save_person(person)
        grp = make_group(name="team", member_ids=[person_id], member_names=["Alice"])
        await db.save_group(grp)
        r1 = make_restaurant(name="Team Spot", rating=4.5)
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([r1]),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "get_recommendations",
                    {"group": "team"},
                )
        text = str(result)
        assert "gluten-free" in text
        await db.close()

    async def test_no_preferences(self):
        """When no user preferences saved, walk_limit defaults to 15."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        await db.save_location(make_location(name="home", lat=40.71, lng=-74.01))
        # Don't save preferences
        r1 = make_restaurant(name="Default Walk", rating=4.5)
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([r1]),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool("get_recommendations", {})
        text = str(result)
        assert "Default Walk" in text
        await db.close()

    async def test_cuisine_prefs_all_categories(self):
        """Favorite, liked, and avoided cuisines are properly categorized."""
        db = await _setup_rec_db()
        await db.set_cuisine_preferences([
            make_cuisine_preference(cuisine="italian", category=CuisineCategory.FAVORITE),
            make_cuisine_preference(cuisine="thai", category=CuisineCategory.LIKE),
            make_cuisine_preference(cuisine="sushi", category=CuisineCategory.AVOID),
        ])
        r_it = make_restaurant(name="Fav Italian", rating=4.5, cuisine=["italian"])
        r_th = make_restaurant(name="Liked Thai", rating=4.5, cuisine=["thai"])
        r_jp = make_restaurant(
            name="Avoid Sushi", rating=4.5, cuisine=["sushi"]
        )
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([r_it, r_th, r_jp]),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool("get_recommendations", {})
        text = str(result)
        assert "Fav Italian" in text
        assert "Liked Thai" in text
        assert "Avoid Sushi" not in text
        await db.close()

    async def test_restaurant_no_cuisine_in_output(self):
        """Restaurant with no cuisine shows 'Various' in output."""
        db = await _setup_rec_db()
        r = make_restaurant(name="No Cuisine", rating=4.5, cuisine=[])
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([r]),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool("get_recommendations", {})
        text = str(result)
        assert "Various" in text
        await db.close()

    async def test_restaurant_no_rating_in_output(self):
        """Restaurant with no rating shows '?' in output."""
        db = await _setup_rec_db()
        r = make_restaurant(name="Mystery", rating=None, cuisine=["italian"])
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([r]),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool("get_recommendations", {})
        text = str(result)
        assert "?" in text
        await db.close()

    async def test_no_occasion_label(self):
        """No occasion → no occasion label in output."""
        db = await _setup_rec_db()
        r = make_restaurant(name="General", rating=4.5)
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([r]),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool("get_recommendations", {})
        text = str(result)
        assert "My picks:" in text or "My picks\n" in text
        await db.close()

    async def test_visit_without_restaurant_id_skipped_in_review_map(self):
        """Visits with empty restaurant_id are skipped when building review map."""
        db = await _setup_rec_db()
        visit = make_visit(
            restaurant_id="",
            restaurant_name="Manual Visit",
            date=date.today().isoformat(),
        )
        await db.log_visit(visit)
        r1 = make_restaurant(name="Unrelated", rating=4.5)
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([r1]),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool("get_recommendations", {})
        text = str(result)
        assert "Unrelated" in text
        await db.close()

    async def test_price_level_none_passes_min_price_filter(self):
        """Restaurant with None price_level is NOT excluded by min_price."""
        db = await _setup_rec_db()
        r = make_restaurant(name="No Price", rating=4.5, price_level=None)
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([r]),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "get_recommendations",
                    {"occasion": "date_night"},
                )
        text = str(result)
        assert "No Price" in text
        await db.close()

    async def test_avoided_cuisines_empty_restaurant_cuisine(self):
        """Restaurant with no cuisine is not filtered by avoided cuisines."""
        db = await _setup_rec_db()
        await db.set_cuisine_preferences([
            make_cuisine_preference(cuisine="sushi", category=CuisineCategory.AVOID),
        ])
        r = make_restaurant(name="No Cuisine Place", rating=4.5, cuisine=[])
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([r]),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool("get_recommendations", {})
        text = str(result)
        assert "No Cuisine Place" in text
        await db.close()

    async def test_no_group_no_dietary_section(self):
        """Without group or user dietary restrictions, no dietary section."""
        db = await _setup_rec_db()
        r = make_restaurant(name="Free Place", rating=4.5)
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([r]),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool("get_recommendations", {})
        text = str(result)
        assert "Dietary restrictions" not in text
        await db.close()

    async def test_neutral_cuisine_preference_ignored(self):
        """Neutral cuisine prefs don't affect favorite/liked/avoided sets."""
        db = await _setup_rec_db()
        await db.set_cuisine_preferences([
            make_cuisine_preference(
                cuisine="mexican", category=CuisineCategory.NEUTRAL
            ),
            make_cuisine_preference(
                cuisine="italian", category=CuisineCategory.FAVORITE
            ),
        ])
        r = make_restaurant(name="Mexican Place", rating=4.5, cuisine=["mexican"])
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([r]),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool("get_recommendations", {})
        text = str(result)
        assert "Mexican Place" in text
        await db.close()


# ── search_for_group ─────────────────────────────────────────────────────


class TestSearchForGroup:
    """Integration tests for the search_for_group tool."""

    async def test_basic_group_search(self):
        db = await _setup_rec_db()
        await db.save_location(make_location(name="work", lat=40.75, lng=-73.99))
        person = make_person(name="Alice", dietary_restrictions=[])
        pid = await db.save_person(person)
        grp = make_group(name="team", member_ids=[pid], member_names=["Alice"])
        await db.save_group(grp)
        r1 = make_restaurant(name="Team Lunch", rating=4.5)
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([r1]),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "search_for_group",
                    {"group_name": "team"},
                )
        text = str(result)
        assert "team" in text
        assert "Alice" in text
        assert "party of 2" in text
        assert "Team Lunch" in text
        await db.close()

    async def test_group_not_found(self):
        db = await _setup_rec_db()
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "search_for_group",
                    {"group_name": "nonexistent"},
                )
        text = str(result)
        assert "not found" in text
        await db.close()

    async def test_location_not_found(self):
        db = await _setup_rec_db()
        grp = make_group(name="team", member_names=[])
        await db.save_group(grp)
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.geocode_address",
                AsyncMock(return_value=None),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "search_for_group",
                    {"group_name": "team", "location": "nowhere"},
                )
        text = str(result)
        assert "Could not resolve location" in text
        await db.close()

    async def test_geocoded_location(self):
        db = await _setup_rec_db()
        person = make_person(name="Bob")
        pid = await db.save_person(person)
        grp = make_group(name="friends", member_ids=[pid], member_names=["Bob"])
        await db.save_group(grp)
        r1 = make_restaurant(name="Geocoded Spot", rating=4.5)
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([r1]),
            ),
            patch(
                "src.tools.recommendations.geocode_address",
                AsyncMock(return_value=(40.75, -73.99)),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "search_for_group",
                    {"group_name": "friends", "location": "123 Broadway"},
                )
        text = str(result)
        assert "Geocoded Spot" in text
        await db.close()

    async def test_with_cuisine_filter(self):
        db = await _setup_rec_db()
        await db.save_location(make_location(name="work", lat=40.75, lng=-73.99))
        grp = make_group(name="team", member_names=[])
        await db.save_group(grp)
        r1 = make_restaurant(name="Thai Spot", rating=4.5, cuisine=["thai"])
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        mock_class = _make_places_mock([r1])
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch("src.tools.recommendations.GooglePlacesClient", mock_class),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "search_for_group",
                    {"group_name": "team", "cuisine": "thai"},
                )
        text = str(result)
        assert "Thai Spot" in text
        # Verify cuisine was in the query
        call_args = mock_class.return_value.search_nearby.call_args
        query = call_args.kwargs.get("query", "")
        assert "thai" in query

    async def test_no_results(self):
        db = await _setup_rec_db()
        await db.save_location(make_location(name="work", lat=40.75, lng=-73.99))
        grp = make_group(name="team", member_names=[])
        await db.save_group(grp)
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([]),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "search_for_group",
                    {"group_name": "team"},
                )
        text = str(result)
        assert "No suitable restaurants" in text
        await db.close()

    async def test_dietary_restrictions_merged(self):
        db = await _setup_rec_db()
        await db.save_location(make_location(name="work", lat=40.75, lng=-73.99))
        alice = make_person(name="Alice", dietary_restrictions=["vegan"])
        bob = make_person(name="Bob", dietary_restrictions=["nut-free"])
        aid = await db.save_person(alice)
        bid = await db.save_person(bob)
        grp = make_group(
            name="team", member_ids=[aid, bid], member_names=["Alice", "Bob"]
        )
        await db.save_group(grp)
        r1 = make_restaurant(name="Diet Place", rating=4.5)
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([r1]),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "search_for_group",
                    {"group_name": "team"},
                )
        text = str(result)
        assert "nut-free" in text
        assert "vegan" in text
        await db.close()

    async def test_no_alcohol_note(self):
        db = await _setup_rec_db()
        await db.save_location(make_location(name="work", lat=40.75, lng=-73.99))
        person = make_person(name="Charlie", no_alcohol=True)
        pid = await db.save_person(person)
        grp = make_group(name="team", member_ids=[pid], member_names=["Charlie"])
        await db.save_group(grp)
        r1 = make_restaurant(name="Sober Place", rating=4.5)
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([r1]),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "search_for_group",
                    {"group_name": "team"},
                )
        text = str(result)
        assert "Charlie" in text
        assert "doesn't drink" in text
        await db.close()

    async def test_blacklisted_excluded(self):
        db = await _setup_rec_db()
        await db.save_location(make_location(name="work", lat=40.75, lng=-73.99))
        grp = make_group(name="team", member_names=[])
        await db.save_group(grp)
        await db.add_to_blacklist("bad_id", "Bad Restaurant", "test")
        r_bad = make_restaurant(id="bad_id", name="Bad Restaurant", rating=4.5)
        r_good = make_restaurant(id="good_id", name="Good Restaurant", rating=4.5)
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([r_bad, r_good]),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "search_for_group",
                    {"group_name": "team"},
                )
        text = str(result)
        assert "Bad Restaurant" not in text
        assert "Good Restaurant" in text
        await db.close()

    async def test_low_rating_excluded(self):
        db = await _setup_rec_db()
        await db.save_location(make_location(name="work", lat=40.75, lng=-73.99))
        grp = make_group(name="team", member_names=[])
        await db.save_group(grp)
        r_low = make_restaurant(name="Low Place", rating=3.5)
        r_high = make_restaurant(name="High Place", rating=4.5)
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([r_low, r_high]),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "search_for_group",
                    {"group_name": "team"},
                )
        text = str(result)
        assert "Low Place" not in text
        assert "High Place" in text
        await db.close()

    async def test_rating_none_not_excluded(self):
        """Restaurants with None rating are NOT excluded (condition checks is not None)."""
        db = await _setup_rec_db()
        await db.save_location(make_location(name="work", lat=40.75, lng=-73.99))
        grp = make_group(name="team", member_names=[])
        await db.save_group(grp)
        r = make_restaurant(name="Unrated", rating=None)
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([r]),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "search_for_group",
                    {"group_name": "team"},
                )
        text = str(result)
        assert "Unrated" in text
        await db.close()

    async def test_avoided_cuisines_excluded(self):
        db = await _setup_rec_db()
        await db.save_location(make_location(name="work", lat=40.75, lng=-73.99))
        await db.set_cuisine_preferences([
            make_cuisine_preference(cuisine="sushi", category=CuisineCategory.AVOID),
        ])
        grp = make_group(name="team", member_names=[])
        await db.save_group(grp)
        r1 = make_restaurant(name="Sushi Spot", rating=4.5, cuisine=["sushi"])
        r2 = make_restaurant(name="Pizza Spot", rating=4.5, cuisine=["italian"])
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([r1, r2]),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "search_for_group",
                    {"group_name": "team"},
                )
        text = str(result)
        assert "Sushi Spot" not in text
        assert "Pizza Spot" in text
        await db.close()

    async def test_no_cuisine_restaurant_not_excluded_by_avoided(self):
        """Restaurant with no cuisine is not filtered by avoided cuisines."""
        db = await _setup_rec_db()
        await db.save_location(make_location(name="work", lat=40.75, lng=-73.99))
        await db.set_cuisine_preferences([
            make_cuisine_preference(cuisine="sushi", category=CuisineCategory.AVOID),
        ])
        grp = make_group(name="team", member_names=[])
        await db.save_group(grp)
        r = make_restaurant(name="No Cuisine", rating=4.5, cuisine=[])
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([r]),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "search_for_group",
                    {"group_name": "team"},
                )
        text = str(result)
        assert "No Cuisine" in text
        await db.close()

    async def test_no_prefs_defaults_walk_limit(self):
        """Without user preferences, walk_limit defaults to 15."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        await db.save_location(make_location(name="work", lat=40.75, lng=-73.99))
        grp = make_group(name="team", member_names=[])
        await db.save_group(grp)
        r = make_restaurant(name="Walk Place", rating=4.5)
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([r]),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "search_for_group",
                    {"group_name": "team"},
                )
        text = str(result)
        assert "Walk Place" in text
        await db.close()

    async def test_member_not_found_skipped(self):
        """If a group member doesn't have a person record, they're skipped."""
        db = await _setup_rec_db()
        await db.save_location(make_location(name="work", lat=40.75, lng=-73.99))
        grp = make_group(name="team", member_names=["Ghost"])
        await db.save_group(grp)
        r = make_restaurant(name="Ghost Place", rating=4.5)
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([r]),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "search_for_group",
                    {"group_name": "team"},
                )
        text = str(result)
        # Party should be 1 (just user, Ghost not found)
        assert "party of 1" in text
        await db.close()

    async def test_no_cuisine_shows_various(self):
        """Restaurant with no cuisine shows 'Various' in output."""
        db = await _setup_rec_db()
        await db.save_location(make_location(name="work", lat=40.75, lng=-73.99))
        grp = make_group(name="team", member_names=[])
        await db.save_group(grp)
        r = make_restaurant(name="Various Place", rating=4.5, cuisine=[])
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([r]),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "search_for_group",
                    {"group_name": "team"},
                )
        text = str(result)
        assert "Various" in text
        await db.close()

    async def test_no_rating_shows_question_mark(self):
        """Restaurant with no rating shows '?' in output."""
        db = await _setup_rec_db()
        await db.save_location(make_location(name="work", lat=40.75, lng=-73.99))
        grp = make_group(name="team", member_names=[])
        await db.save_group(grp)
        r = make_restaurant(name="Unrated", rating=None)
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([r]),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "search_for_group",
                    {"group_name": "team"},
                )
        text = str(result)
        assert "?" in text
        await db.close()

    async def test_no_restrictions_no_notes_section(self):
        """Without dietary restrictions or no_alcohol, no notes section."""
        db = await _setup_rec_db()
        await db.save_location(make_location(name="work", lat=40.75, lng=-73.99))
        grp = make_group(name="team", member_names=[])
        await db.save_group(grp)
        r = make_restaurant(name="Clean Place", rating=4.5)
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([r]),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "search_for_group",
                    {"group_name": "team"},
                )
        text = str(result)
        assert "Dietary restrictions" not in text
        assert "doesn't drink" not in text
        await db.close()

    async def test_neutral_cuisine_preference_in_group_search(self):
        """Neutral cuisine prefs don't add to avoided set in group search."""
        db = await _setup_rec_db()
        await db.save_location(make_location(name="work", lat=40.75, lng=-73.99))
        await db.set_cuisine_preferences([
            make_cuisine_preference(
                cuisine="mexican", category=CuisineCategory.NEUTRAL
            ),
        ])
        grp = make_group(name="team", member_names=[])
        await db.save_group(grp)
        r = make_restaurant(name="Mex Place", rating=4.5, cuisine=["mexican"])
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([r]),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "search_for_group",
                    {"group_name": "team"},
                )
        text = str(result)
        assert "Mex Place" in text
        await db.close()

    async def test_member_person_not_found(self):
        """When get_person returns None for a member, they're skipped."""
        db = await _setup_rec_db()
        await db.save_location(make_location(name="work", lat=40.75, lng=-73.99))
        # Save a person and create group with them
        person = make_person(name="Alice")
        pid = await db.save_person(person)
        grp = make_group(name="team", member_ids=[pid], member_names=["Alice"])
        await db.save_group(grp)
        r = make_restaurant(name="Orphan Place", rating=4.5)
        mcp = FastMCP("test")
        register_recommendation_tools(mcp)
        # Mock get_person to return None (simulates race condition)
        original_get_person = db.get_person
        db.get_person = AsyncMock(return_value=None)
        with (
            patch("src.tools.recommendations.get_db", return_value=db),
            patch("src.config.get_settings", return_value=_mock_settings()),
            patch(
                "src.tools.recommendations.GooglePlacesClient",
                _make_places_mock([r]),
            ),
        ):
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "search_for_group",
                    {"group_name": "team"},
                )
        text = str(result)
        assert "Orphan Place" in text
        # Party should be 1 (just user, no members resolved)
        assert "party of 1" in text
        db.get_person = original_get_person
        await db.close()
