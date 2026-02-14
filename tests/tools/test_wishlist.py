from unittest.mock import patch

from fastmcp import Client, FastMCP

from src.storage.database import DatabaseManager
from src.tools.wishlist import register_wishlist_tools
from tests.factories import make_restaurant


class TestRegisterWishlistTools:
    """Test tool registration."""

    def test_registration_succeeds(self):
        test_mcp = FastMCP("test")
        register_wishlist_tools(test_mcp)


class TestManageWishlist:
    """Test the manage_wishlist tool."""

    async def test_add_cached_restaurant(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        restaurant = make_restaurant(id="place_wish1", name="Dream Spot")
        await db.cache_restaurant(restaurant)
        test_mcp = FastMCP("test")
        register_wishlist_tools(test_mcp)
        with patch("src.tools.wishlist.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "manage_wishlist",
                    {"restaurant_name": "Dream Spot"},
                )
        text = str(result)
        assert "Added 'Dream Spot' to your wishlist" in text
        assert await db.is_on_wishlist("place_wish1")
        await db.close()

    async def test_add_with_notes_and_tags(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        restaurant = make_restaurant(id="place_wish2", name="Fancy Place")
        await db.cache_restaurant(restaurant)
        test_mcp = FastMCP("test")
        register_wishlist_tools(test_mcp)
        with patch("src.tools.wishlist.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "manage_wishlist",
                    {
                        "restaurant_name": "Fancy Place",
                        "notes": "Get the tasting menu",
                        "tags": "date night, special occasion",
                    },
                )
        text = str(result)
        assert "Added 'Fancy Place' to your wishlist" in text
        items = await db.get_wishlist()
        assert len(items) == 1
        assert items[0].notes == "Get the tasting menu"
        assert set(items[0].tags) == {"date night", "special occasion"}
        await db.close()

    async def test_add_without_notes(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        restaurant = make_restaurant(id="place_wish3", name="Simple Spot")
        await db.cache_restaurant(restaurant)
        test_mcp = FastMCP("test")
        register_wishlist_tools(test_mcp)
        with patch("src.tools.wishlist.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "manage_wishlist",
                    {"restaurant_name": "Simple Spot"},
                )
        text = str(result)
        assert "Added 'Simple Spot' to your wishlist" in text
        items = await db.get_wishlist()
        assert len(items) == 1
        assert items[0].notes is None
        assert items[0].tags == []
        await db.close()

    async def test_add_not_in_cache(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        test_mcp = FastMCP("test")
        register_wishlist_tools(test_mcp)
        with patch("src.tools.wishlist.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "manage_wishlist",
                    {"restaurant_name": "Unknown Place"},
                )
        text = str(result)
        assert "not found in cache" in text
        assert "search" in text.lower()
        await db.close()

    async def test_add_already_on_wishlist_updates(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        restaurant = make_restaurant(id="place_wish4", name="Update Me")
        await db.cache_restaurant(restaurant)
        await db.add_to_wishlist("place_wish4", "Update Me", "old notes", ["old"])
        test_mcp = FastMCP("test")
        register_wishlist_tools(test_mcp)
        with patch("src.tools.wishlist.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "manage_wishlist",
                    {
                        "restaurant_name": "Update Me",
                        "notes": "new notes",
                        "tags": "brunch",
                    },
                )
        text = str(result)
        assert "Updated 'Update Me' on your wishlist" in text
        items = await db.get_wishlist()
        assert len(items) == 1
        assert items[0].notes == "new notes"
        assert items[0].tags == ["brunch"]
        await db.close()

    async def test_add_tag_normalization(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        restaurant = make_restaurant(id="place_wish5", name="Tag Test")
        await db.cache_restaurant(restaurant)
        test_mcp = FastMCP("test")
        register_wishlist_tools(test_mcp)
        with patch("src.tools.wishlist.get_db", return_value=db):
            async with Client(test_mcp) as client:
                await client.call_tool(
                    "manage_wishlist",
                    {
                        "restaurant_name": "Tag Test",
                        "tags": "Date Night, BRUNCH",
                    },
                )
        items = await db.get_wishlist()
        assert set(items[0].tags) == {"date night", "brunch"}
        await db.close()

    async def test_remove_cached_found(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        restaurant = make_restaurant(id="place_wish6", name="Remove Me")
        await db.cache_restaurant(restaurant)
        await db.add_to_wishlist("place_wish6", "Remove Me", None, [])
        test_mcp = FastMCP("test")
        register_wishlist_tools(test_mcp)
        with patch("src.tools.wishlist.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "manage_wishlist",
                    {"restaurant_name": "Remove Me", "action": "remove"},
                )
        text = str(result)
        assert "Removed 'Remove Me' from your wishlist" in text
        assert not await db.is_on_wishlist("place_wish6")
        await db.close()

    async def test_remove_cached_not_on_wishlist(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        restaurant = make_restaurant(id="place_wish7", name="Not Listed")
        await db.cache_restaurant(restaurant)
        test_mcp = FastMCP("test")
        register_wishlist_tools(test_mcp)
        with patch("src.tools.wishlist.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "manage_wishlist",
                    {"restaurant_name": "Not Listed", "action": "remove"},
                )
        text = str(result)
        assert "was not on your wishlist" in text
        await db.close()

    async def test_remove_not_cached(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        test_mcp = FastMCP("test")
        register_wishlist_tools(test_mcp)
        with patch("src.tools.wishlist.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "manage_wishlist",
                    {"restaurant_name": "Ghost Place", "action": "remove"},
                )
        text = str(result)
        assert "was not on your wishlist" in text
        await db.close()

    async def test_remove_not_cached_but_on_wishlist(self):
        """Restaurant added by name (not cached) can be removed by name."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        # Add directly with restaurant_name as the restaurant_id
        await db.add_to_wishlist("Uncached Spot", "Uncached Spot", None, [])
        test_mcp = FastMCP("test")
        register_wishlist_tools(test_mcp)
        with patch("src.tools.wishlist.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "manage_wishlist",
                    {"restaurant_name": "Uncached Spot", "action": "remove"},
                )
        text = str(result)
        assert "Removed 'Uncached Spot' from your wishlist" in text
        assert not await db.is_on_wishlist("Uncached Spot")
        await db.close()

    async def test_unknown_action(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        test_mcp = FastMCP("test")
        register_wishlist_tools(test_mcp)
        with patch("src.tools.wishlist.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "manage_wishlist",
                    {"restaurant_name": "Whatever", "action": "destroy"},
                )
        text = str(result)
        assert "Unknown action 'destroy'" in text
        assert "add" in text
        assert "remove" in text
        await db.close()


class TestMyWishlist:
    """Test the my_wishlist tool."""

    async def test_empty_wishlist(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        test_mcp = FastMCP("test")
        register_wishlist_tools(test_mcp)
        with patch("src.tools.wishlist.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool("my_wishlist", {})
        text = str(result)
        assert "empty" in text.lower()
        await db.close()

    async def test_empty_with_tag_filter(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        test_mcp = FastMCP("test")
        register_wishlist_tools(test_mcp)
        with patch("src.tools.wishlist.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "my_wishlist", {"tag": "brunch"}
                )
        text = str(result)
        assert "brunch" in text
        await db.close()

    async def test_single_item(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        restaurant = make_restaurant(
            id="place_wl1", name="Solo Spot", rating=4.3, cuisine=["thai"]
        )
        await db.cache_restaurant(restaurant)
        await db.add_to_wishlist("place_wl1", "Solo Spot", None, [])
        test_mcp = FastMCP("test")
        register_wishlist_tools(test_mcp)
        with patch("src.tools.wishlist.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool("my_wishlist", {})
        text = str(result)
        assert "Solo Spot" in text
        assert "Your wishlist:" in text
        await db.close()

    async def test_multiple_items(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        r1 = make_restaurant(id="place_wl2", name="Place A", rating=4.5)
        r2 = make_restaurant(id="place_wl3", name="Place B", rating=4.2)
        await db.cache_restaurant(r1)
        await db.cache_restaurant(r2)
        await db.add_to_wishlist("place_wl2", "Place A", None, [])
        await db.add_to_wishlist("place_wl3", "Place B", None, [])
        test_mcp = FastMCP("test")
        register_wishlist_tools(test_mcp)
        with patch("src.tools.wishlist.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool("my_wishlist", {})
        text = str(result)
        assert "Place A" in text
        assert "Place B" in text
        await db.close()

    async def test_tag_filter(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        r1 = make_restaurant(id="place_wl4", name="Brunch Spot")
        r2 = make_restaurant(id="place_wl5", name="Dinner Spot")
        await db.cache_restaurant(r1)
        await db.cache_restaurant(r2)
        await db.add_to_wishlist("place_wl4", "Brunch Spot", None, ["brunch"])
        await db.add_to_wishlist("place_wl5", "Dinner Spot", None, ["date night"])
        test_mcp = FastMCP("test")
        register_wishlist_tools(test_mcp)
        with patch("src.tools.wishlist.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "my_wishlist", {"tag": "brunch"}
                )
        text = str(result)
        assert "Brunch Spot" in text
        assert "Dinner Spot" not in text
        assert "tag: brunch" in text
        await db.close()

    async def test_enriched_with_cache(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        restaurant = make_restaurant(
            id="place_wl6", name="Enriched", rating=4.7, cuisine=["french"]
        )
        await db.cache_restaurant(restaurant)
        await db.add_to_wishlist("place_wl6", "Enriched", None, [])
        test_mcp = FastMCP("test")
        register_wishlist_tools(test_mcp)
        with patch("src.tools.wishlist.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool("my_wishlist", {})
        text = str(result)
        assert "4.7" in text
        assert "french" in text
        await db.close()

    async def test_no_cache_data(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        # Add directly without caching restaurant
        await db.add_to_wishlist("place_nocache", "No Cache Restaurant", None, [])
        test_mcp = FastMCP("test")
        register_wishlist_tools(test_mcp)
        with patch("src.tools.wishlist.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool("my_wishlist", {})
        text = str(result)
        assert "No Cache Restaurant" in text
        # Should not have rating/cuisine enrichment
        assert "\u2605" not in text
        await db.close()

    async def test_notes_and_tags_displayed(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        restaurant = make_restaurant(id="place_wl7", name="Detailed Spot")
        await db.cache_restaurant(restaurant)
        await db.add_to_wishlist(
            "place_wl7", "Detailed Spot", "Try the pasta", ["date night", "italian"]
        )
        test_mcp = FastMCP("test")
        register_wishlist_tools(test_mcp)
        with patch("src.tools.wishlist.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool("my_wishlist", {})
        text = str(result)
        assert "Try the pasta" in text
        assert "date night" in text
        assert "italian" in text
        assert "Added:" in text
        await db.close()

    async def test_no_added_date_omits_added_line(self):
        """When added_date is NULL, no 'Added:' line is shown."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        restaurant = make_restaurant(id="place_wl8", name="No Date Spot")
        await db.cache_restaurant(restaurant)
        await db.add_to_wishlist("place_wl8", "No Date Spot", None, [])
        # Clear the added_date to NULL
        await db.execute(
            "UPDATE wishlist SET added_date = NULL WHERE restaurant_id = ?",
            ("place_wl8",),
        )
        test_mcp = FastMCP("test")
        register_wishlist_tools(test_mcp)
        with patch("src.tools.wishlist.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool("my_wishlist", {})
        text = str(result)
        assert "No Date Spot" in text
        assert "Added:" not in text
        await db.close()
