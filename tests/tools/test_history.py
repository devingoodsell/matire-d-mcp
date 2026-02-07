from datetime import date
from unittest.mock import AsyncMock, patch

from fastmcp import Client, FastMCP

from src.storage.database import DatabaseManager
from src.tools.history import register_history_tools
from tests.factories import (
    make_restaurant,
    make_visit,
    make_visit_review,
)


class TestRegisterHistoryTools:
    """Test tool registration."""

    def test_registration_succeeds(self):
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)


# ── log_visit ────────────────────────────────────────────────────────────


class TestLogVisit:
    """Test the log_visit tool."""

    async def test_basic_log_visit(self):
        """Log a visit with just a restaurant name — no cache match."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "log_visit",
                    {"restaurant_name": "Joe's Pizza"},
                )
        text = str(result)
        assert "Visit logged!" in text
        assert "Joe's Pizza" in text
        assert "party of 2" in text
        assert "Visit ID:" in text
        assert "rate_visit" in text
        await db.close()

    async def test_log_visit_with_companions(self):
        """Companions list appears in the confirmation message."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "log_visit",
                    {
                        "restaurant_name": "Le Bernardin",
                        "party_size": 3,
                        "companions": ["Alice", "Bob"],
                    },
                )
        text = str(result)
        assert "with Alice, Bob" in text
        assert "party of 3" in text
        await db.close()

    async def test_log_visit_with_cuisine(self):
        """Cuisine provided by user is stored on the visit."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "log_visit",
                    {
                        "restaurant_name": "Sushi Nakazawa",
                        "cuisine": "japanese",
                    },
                )
        text = str(result)
        assert "Visit logged!" in text
        # Verify the visit was stored with cuisine
        visit = await db.get_visit_by_restaurant_name("Sushi Nakazawa")
        assert visit is not None
        assert visit.cuisine == "japanese"
        await db.close()

    async def test_log_visit_matches_cached_restaurant(self):
        """When a cached restaurant matches, use its ID and display name."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        restaurant = make_restaurant(
            id="place_abc123",
            name="Carbone",
            cuisine=["italian"],
        )
        await db.cache_restaurant(restaurant)
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "log_visit",
                    {"restaurant_name": "Carbone"},
                )
        text = str(result)
        assert "Carbone" in text
        # Verify restaurant_id was set from cache
        visit = await db.get_visit_by_restaurant_name("Carbone")
        assert visit is not None
        assert visit.restaurant_id == "place_abc123"
        await db.close()

    async def test_log_visit_cached_restaurant_cuisine_inherited(self):
        """When no cuisine is provided, inherit from cached restaurant."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        restaurant = make_restaurant(
            id="place_italian1",
            name="Lilia",
            cuisine=["italian"],
        )
        await db.cache_restaurant(restaurant)
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                await client.call_tool(
                    "log_visit",
                    {"restaurant_name": "Lilia"},
                )
        visit = await db.get_visit_by_restaurant_name("Lilia")
        assert visit is not None
        assert visit.cuisine == "italian"
        await db.close()

    async def test_log_visit_cached_restaurant_cuisine_not_overridden(self):
        """When user provides cuisine, do NOT override with cached value."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        restaurant = make_restaurant(
            id="place_mixed1",
            name="Momofuku",
            cuisine=["korean"],
        )
        await db.cache_restaurant(restaurant)
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                await client.call_tool(
                    "log_visit",
                    {
                        "restaurant_name": "Momofuku",
                        "cuisine": "japanese",
                    },
                )
        visit = await db.get_visit_by_restaurant_name("Momofuku")
        assert visit is not None
        assert visit.cuisine == "japanese"
        await db.close()

    async def test_log_visit_cached_restaurant_empty_cuisine(self):
        """Cached restaurant with empty cuisine list does not set cuisine."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        restaurant = make_restaurant(
            id="place_empty_cuisine",
            name="Mystery Spot",
            cuisine=[],
        )
        await db.cache_restaurant(restaurant)
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                await client.call_tool(
                    "log_visit",
                    {"restaurant_name": "Mystery Spot"},
                )
        visit = await db.get_visit_by_restaurant_name("Mystery Spot")
        assert visit is not None
        assert visit.cuisine is None
        await db.close()

    async def test_log_visit_no_cache_match(self):
        """When no cached restaurant matches, restaurant_id is empty string."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                await client.call_tool(
                    "log_visit",
                    {"restaurant_name": "Hole In The Wall"},
                )
        visit = await db.get_visit_by_restaurant_name("Hole In The Wall")
        assert visit is not None
        assert visit.restaurant_id == ""
        assert visit.source == "manual"
        await db.close()

    async def test_log_visit_date_parsing_iso(self):
        """ISO date string is passed through correctly."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "log_visit",
                    {
                        "restaurant_name": "Test Place",
                        "date_str": "2026-02-14",
                    },
                )
        text = str(result)
        assert "2026-02-14" in text
        await db.close()

    async def test_log_visit_date_parsing_natural(self):
        """Natural date string like 'tomorrow' is parsed."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "log_visit",
                    {
                        "restaurant_name": "Test Place",
                        "date_str": "today",
                    },
                )
        text = str(result)
        assert date.today().isoformat() in text
        await db.close()

    async def test_log_visit_invalid_date_fallback_to_today(self):
        """Invalid date string falls back to today."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "log_visit",
                    {
                        "restaurant_name": "Test Place",
                        "date_str": "not-a-real-date!!",
                    },
                )
        text = str(result)
        assert date.today().isoformat() in text
        await db.close()

    async def test_log_visit_no_date_defaults_to_today(self):
        """When no date_str is provided, defaults to today."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "log_visit",
                    {"restaurant_name": "Test Place"},
                )
        text = str(result)
        assert date.today().isoformat() in text
        await db.close()

    async def test_log_visit_no_companions_omits_companion_note(self):
        """When companions is None/empty, no 'with ...' text appears."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "log_visit",
                    {"restaurant_name": "Solo Dinner"},
                )
        text = str(result)
        assert " with " not in text
        await db.close()


# ── rate_visit ───────────────────────────────────────────────────────────


class TestRateVisit:
    """Test the rate_visit tool."""

    async def test_basic_rating(self):
        """Rate a visit with just would_return and overall_rating."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        visit = make_visit(restaurant_name="Carbone", date=date.today().isoformat())
        visit_id = await db.log_visit(visit)
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "rate_visit",
                    {
                        "restaurant_name": "Carbone",
                        "would_return": True,
                        "overall_rating": 5,
                    },
                )
        text = str(result)
        assert "Review saved for Carbone" in text
        assert "(5/5)" in text
        assert "would return" in text
        # Verify persisted
        review = await db.get_visit_review(visit_id)
        assert review is not None
        assert review.would_return is True
        assert review.overall_rating == 5
        await db.close()

    async def test_rate_visit_with_dishes(self):
        """Rate a visit with dish reviews."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        visit = make_visit(restaurant_name="L'Artusi", date=date.today().isoformat())
        await db.log_visit(visit)
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "rate_visit",
                    {
                        "restaurant_name": "L'Artusi",
                        "would_return": True,
                        "overall_rating": 4,
                        "dishes": [
                            {"name": "cacio e pepe", "rating": 5, "order_again": True},
                            {"name": "burrata", "rating": 4, "order_again": True},
                        ],
                    },
                )
        text = str(result)
        assert "Review saved" in text
        assert "2 dish reviews saved" in text
        await db.close()

    async def test_rate_visit_dish_defaults(self):
        """Dish with missing keys uses defaults (name=Unknown, rating=3, order_again=True)."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        visit = make_visit(restaurant_name="Defaults Spot", date=date.today().isoformat())
        await db.log_visit(visit)
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "rate_visit",
                    {
                        "restaurant_name": "Defaults Spot",
                        "would_return": True,
                        "dishes": [{}],
                    },
                )
        text = str(result)
        assert "1 dish reviews saved" in text
        await db.close()

    async def test_rate_visit_dish_with_notes(self):
        """Dish review with notes field set."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        visit = make_visit(restaurant_name="Notes Spot", date=date.today().isoformat())
        visit_id = await db.log_visit(visit)
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                await client.call_tool(
                    "rate_visit",
                    {
                        "restaurant_name": "Notes Spot",
                        "would_return": True,
                        "dishes": [
                            {
                                "name": "truffle pasta",
                                "rating": 5,
                                "order_again": True,
                                "notes": "Best I ever had",
                            },
                        ],
                    },
                )
        # We just ensure no error; the dish notes are saved at DB level
        review = await db.get_visit_review(visit_id)
        assert review is not None
        await db.close()

    async def test_rate_visit_would_not_return(self):
        """would_return=False shows 'would not return'."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        visit = make_visit(restaurant_name="Bad Place", date=date.today().isoformat())
        await db.log_visit(visit)
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "rate_visit",
                    {
                        "restaurant_name": "Bad Place",
                        "would_return": False,
                        "overall_rating": 1,
                    },
                )
        text = str(result)
        assert "would not return" in text
        assert "(1/5)" in text
        await db.close()

    async def test_rate_visit_no_overall_rating(self):
        """No overall_rating omits the rating from the response string."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        visit = make_visit(restaurant_name="No Rating", date=date.today().isoformat())
        await db.log_visit(visit)
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "rate_visit",
                    {
                        "restaurant_name": "No Rating",
                        "would_return": True,
                    },
                )
        text = str(result)
        assert "Review saved for No Rating" in text
        assert "/5)" not in text
        await db.close()

    async def test_rate_visit_with_noise_level_quiet(self):
        """Valid noise level 'quiet' is parsed correctly."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        visit = make_visit(restaurant_name="Quiet Spot", date=date.today().isoformat())
        visit_id = await db.log_visit(visit)
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                await client.call_tool(
                    "rate_visit",
                    {
                        "restaurant_name": "Quiet Spot",
                        "would_return": True,
                        "noise_level": "quiet",
                    },
                )
        review = await db.get_visit_review(visit_id)
        assert review is not None
        assert review.noise_level == "quiet"
        await db.close()

    async def test_rate_visit_with_noise_level_moderate(self):
        """Valid noise level 'moderate'."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        visit = make_visit(restaurant_name="Moderate Spot", date=date.today().isoformat())
        visit_id = await db.log_visit(visit)
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                await client.call_tool(
                    "rate_visit",
                    {
                        "restaurant_name": "Moderate Spot",
                        "would_return": True,
                        "noise_level": "Moderate",
                    },
                )
        review = await db.get_visit_review(visit_id)
        assert review is not None
        assert review.noise_level == "moderate"
        await db.close()

    async def test_rate_visit_with_noise_level_loud(self):
        """Valid noise level 'loud'."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        visit = make_visit(restaurant_name="Loud Spot", date=date.today().isoformat())
        visit_id = await db.log_visit(visit)
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                await client.call_tool(
                    "rate_visit",
                    {
                        "restaurant_name": "Loud Spot",
                        "would_return": True,
                        "noise_level": "LOUD",
                    },
                )
        review = await db.get_visit_review(visit_id)
        assert review is not None
        assert review.noise_level == "loud"
        await db.close()

    async def test_rate_visit_invalid_noise_level(self):
        """Invalid noise level is silently ignored (parsed_noise stays None)."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        visit = make_visit(restaurant_name="Noisy Place", date=date.today().isoformat())
        visit_id = await db.log_visit(visit)
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "rate_visit",
                    {
                        "restaurant_name": "Noisy Place",
                        "would_return": True,
                        "noise_level": "deafening",
                    },
                )
        text = str(result)
        assert "Review saved" in text
        review = await db.get_visit_review(visit_id)
        assert review is not None
        assert review.noise_level is None
        await db.close()

    async def test_rate_visit_with_notes(self):
        """Notes are saved on the review."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        visit = make_visit(restaurant_name="Notes Place", date=date.today().isoformat())
        visit_id = await db.log_visit(visit)
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                await client.call_tool(
                    "rate_visit",
                    {
                        "restaurant_name": "Notes Place",
                        "would_return": True,
                        "notes": "Great for date night",
                    },
                )
        review = await db.get_visit_review(visit_id)
        assert review is not None
        assert review.notes == "Great for date night"
        await db.close()

    async def test_rate_visit_no_visit_found(self):
        """No matching visit returns a helpful error message."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "rate_visit",
                    {
                        "restaurant_name": "Nonexistent Place",
                        "would_return": True,
                    },
                )
        text = str(result)
        assert "No recent visit found for 'Nonexistent Place'" in text
        assert "log_visit" in text
        await db.close()

    async def test_rate_visit_already_reviewed(self):
        """Attempting to review a visit that already has a review."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        visit = make_visit(restaurant_name="Double Review", date=date.today().isoformat())
        visit_id = await db.log_visit(visit)
        # Save an existing review
        review = make_visit_review(visit_id=visit_id, would_return=True, overall_rating=4)
        await db.save_visit_review(review)
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "rate_visit",
                    {
                        "restaurant_name": "Double Review",
                        "would_return": False,
                    },
                )
        text = str(result)
        assert "already has a review" in text
        assert "Double Review" in text
        await db.close()

    async def test_rate_visit_no_dishes(self):
        """No dishes results in no dish count message."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        visit = make_visit(restaurant_name="No Dishes", date=date.today().isoformat())
        await db.log_visit(visit)
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "rate_visit",
                    {
                        "restaurant_name": "No Dishes",
                        "would_return": True,
                        "overall_rating": 3,
                    },
                )
        text = str(result)
        assert "dish reviews saved" not in text
        await db.close()


# ── visit_history ────────────────────────────────────────────────────────


class TestVisitHistory:
    """Test the visit_history tool."""

    async def test_default_no_visits(self):
        """No visits returns a 'no visits' message."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool("visit_history", {})
        text = str(result)
        assert "No visits recorded" in text
        assert "last 90 days" in text
        await db.close()

    async def test_no_visits_with_cuisine_filter(self):
        """No visits with cuisine filter includes cuisine in the message."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "visit_history",
                    {"cuisine": "thai"},
                )
        text = str(result)
        assert "No visits recorded" in text
        assert "for thai" in text
        await db.close()

    async def test_with_visits(self):
        """Visits are listed with restaurant name, date, party size."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        today = date.today().isoformat()
        visit1 = make_visit(
            restaurant_name="Carbone",
            date=today,
            party_size=2,
        )
        visit2 = make_visit(
            restaurant_name="L'Artusi",
            date=today,
            party_size=4,
            companions=["Alice", "Bob", "Carol"],
        )
        await db.log_visit(visit1)
        await db.log_visit(visit2)
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool("visit_history", {})
        text = str(result)
        assert "2 visits" in text
        assert "Carbone" in text
        assert "L'Artusi" in text
        assert "party of 4" in text
        assert "with Alice, Bob, Carol" in text
        await db.close()

    async def test_visit_with_cuisine_displayed(self):
        """Cuisine label appears in parentheses after restaurant name."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        today = date.today().isoformat()
        visit = make_visit(
            restaurant_name="Tatiana",
            date=today,
            cuisine="mexican",
        )
        await db.log_visit(visit)
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool("visit_history", {})
        text = str(result)
        assert "(mexican)" in text
        await db.close()

    async def test_cuisine_filter_by_visit_cuisine(self):
        """Filter by cuisine matches against visit-level cuisine field."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        today = date.today().isoformat()
        visit_italian = make_visit(
            restaurant_name="Carbone",
            date=today,
            cuisine="Italian",
        )
        visit_japanese = make_visit(
            restaurant_name="Sushi Nakazawa",
            date=today,
            cuisine="Japanese",
        )
        await db.log_visit(visit_italian)
        await db.log_visit(visit_japanese)
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "visit_history",
                    {"cuisine": "italian"},
                )
        text = str(result)
        assert "1 visits" in text
        assert "Carbone" in text
        assert "Sushi Nakazawa" not in text
        await db.close()

    async def test_cuisine_filter_by_cached_restaurant(self):
        """Filter by cuisine matches against cached restaurant cuisine list."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        today = date.today().isoformat()
        restaurant = make_restaurant(
            id="place_ital1",
            name="Via Carota",
            cuisine=["Italian"],
        )
        await db.cache_restaurant(restaurant)
        visit = make_visit(
            restaurant_id="place_ital1",
            restaurant_name="Via Carota",
            date=today,
            cuisine=None,  # no visit-level cuisine
        )
        await db.log_visit(visit)
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "visit_history",
                    {"cuisine": "italian"},
                )
        text = str(result)
        assert "1 visits" in text
        assert "Via Carota" in text
        await db.close()

    async def test_cuisine_filter_no_match_cached_or_visit(self):
        """Visit without matching visit cuisine or cached cuisine is excluded."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        today = date.today().isoformat()
        visit = make_visit(
            restaurant_name="Random Place",
            date=today,
            cuisine="american",
            restaurant_id="",
        )
        await db.log_visit(visit)
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "visit_history",
                    {"cuisine": "thai"},
                )
        text = str(result)
        assert "No visits recorded" in text
        await db.close()

    async def test_cuisine_filter_visit_no_cuisine_no_restaurant_id(self):
        """Visit with no cuisine and no restaurant_id (empty) is excluded from filter."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        today = date.today().isoformat()
        visit = make_visit(
            restaurant_name="Mystery",
            date=today,
            cuisine=None,
            restaurant_id="",
        )
        await db.log_visit(visit)
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "visit_history",
                    {"cuisine": "italian"},
                )
        text = str(result)
        assert "No visits recorded" in text
        await db.close()

    async def test_cuisine_filter_restaurant_id_but_no_cache(self):
        """Visit has restaurant_id but no cached restaurant — excluded from filter."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        today = date.today().isoformat()
        visit = make_visit(
            restaurant_name="Gone Place",
            date=today,
            cuisine=None,
            restaurant_id="place_gone",
        )
        await db.log_visit(visit)
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "visit_history",
                    {"cuisine": "italian"},
                )
        text = str(result)
        assert "No visits recorded" in text
        await db.close()

    async def test_with_reviews_showing_ratings(self):
        """Reviews are displayed inline with ratings and return status."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        today = date.today().isoformat()
        visit = make_visit(restaurant_name="Reviewed Place", date=today)
        visit_id = await db.log_visit(visit)
        review = make_visit_review(
            visit_id=visit_id,
            would_return=True,
            overall_rating=4,
        )
        await db.save_visit_review(review)
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool("visit_history", {})
        text = str(result)
        assert "4/5" in text
        assert "(would return)" in text
        await db.close()

    async def test_with_review_would_not_return(self):
        """Review with would_return=False shows 'would not return'."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        today = date.today().isoformat()
        visit = make_visit(restaurant_name="Never Again", date=today)
        visit_id = await db.log_visit(visit)
        review = make_visit_review(
            visit_id=visit_id,
            would_return=False,
            overall_rating=1,
        )
        await db.save_visit_review(review)
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool("visit_history", {})
        text = str(result)
        assert "1/5" in text
        assert "(would not return)" in text
        await db.close()

    async def test_with_review_no_overall_rating(self):
        """Review without overall_rating omits the rating number."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        today = date.today().isoformat()
        visit = make_visit(restaurant_name="No Score Place", date=today)
        visit_id = await db.log_visit(visit)
        review = make_visit_review(
            visit_id=visit_id,
            would_return=True,
            overall_rating=None,
        )
        await db.save_visit_review(review)
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool("visit_history", {})
        text = str(result)
        assert "/5" not in text
        assert "(would return)" in text
        await db.close()

    async def test_visit_without_companions(self):
        """Visit with no companions omits 'with ...' text."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        today = date.today().isoformat()
        visit = make_visit(
            restaurant_name="Solo Diner",
            date=today,
            companions=[],
        )
        await db.log_visit(visit)
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool("visit_history", {})
        text = str(result)
        assert "Solo Diner" in text
        assert " with " not in text
        await db.close()

    async def test_visit_without_cuisine(self):
        """Visit with no cuisine omits the cuisine parenthetical."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        today = date.today().isoformat()
        visit = make_visit(
            restaurant_name="Cuisine Free",
            date=today,
            cuisine=None,
        )
        await db.log_visit(visit)
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool("visit_history", {})
        text = str(result)
        assert "Cuisine Free" in text
        # No parenthetical cuisine
        assert "Cuisine Free (" not in text
        await db.close()

    async def test_custom_days_parameter(self):
        """Custom days parameter is forwarded to the query."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "visit_history",
                    {"days": 7},
                )
        text = str(result)
        assert "No visits recorded" in text
        assert "last 7 days" in text
        await db.close()

    async def test_visit_no_review_no_id(self):
        """Visit with id=None does not attempt to fetch a review."""
        # This is hard to trigger via the tool since log_visit always
        # assigns an ID, but we test the branch by ensuring visits
        # without reviews don't show review info.
        db = DatabaseManager(":memory:")
        await db.initialize()
        today = date.today().isoformat()
        visit = make_visit(restaurant_name="Unreviewed", date=today)
        await db.log_visit(visit)
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool("visit_history", {})
        text = str(result)
        assert "Unreviewed" in text
        assert "/5" not in text
        assert "(would return)" not in text
        assert "(would not return)" not in text
        await db.close()

    async def test_cuisine_filter_case_insensitive(self):
        """Cuisine filtering is case-insensitive."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        today = date.today().isoformat()
        visit = make_visit(
            restaurant_name="Pasta House",
            date=today,
            cuisine="Italian",
        )
        await db.log_visit(visit)
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "visit_history",
                    {"cuisine": "ITALIAN"},
                )
        text = str(result)
        assert "Pasta House" in text
        assert "1 visits" in text
        await db.close()

    async def test_visit_with_id_none_skips_review_lookup(self):
        """When a visit has id=None, the review lookup is skipped."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        # Mock get_recent_visits to return a visit with id=None
        visit_no_id = make_visit(
            restaurant_name="Phantom Place",
            date=date.today().isoformat(),
        )
        visit_no_id.id = None  # Force id to None
        original_get = db.get_recent_visits
        db.get_recent_visits = AsyncMock(return_value=[visit_no_id])
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool("visit_history", {})
        text = str(result)
        assert "Phantom Place" in text
        # No review info should appear
        assert "/5" not in text
        assert "(would return)" not in text
        db.get_recent_visits = original_get
        await db.close()

    async def test_cuisine_filter_cached_restaurant_no_matching_cuisine(self):
        """Cached restaurant cuisine does not match the filter."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        today = date.today().isoformat()
        restaurant = make_restaurant(
            id="place_jp1",
            name="Sushi Spot",
            cuisine=["Japanese"],
        )
        await db.cache_restaurant(restaurant)
        visit = make_visit(
            restaurant_id="place_jp1",
            restaurant_name="Sushi Spot",
            date=today,
            cuisine=None,
        )
        await db.log_visit(visit)
        test_mcp = FastMCP("test")
        register_history_tools(test_mcp)
        with patch("src.tools.history.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "visit_history",
                    {"cuisine": "mexican"},
                )
        text = str(result)
        assert "No visits recorded" in text
        await db.close()
