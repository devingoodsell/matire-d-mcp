from unittest.mock import patch

from fastmcp import Client, FastMCP

from src.storage.database import DatabaseManager
from src.tools.blacklist import register_blacklist_tools
from tests.factories import make_restaurant


class TestRegisterBlacklistTools:
    """Test tool registration."""

    def test_registration_succeeds(self):
        test_mcp = FastMCP("test")
        register_blacklist_tools(test_mcp)


class TestManageBlacklist:
    """Test the manage_blacklist tool."""

    async def test_add_with_cached_restaurant(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        restaurant = make_restaurant(
            id="place_abc", name="Bad Place"
        )
        await db.cache_restaurant(restaurant)
        test_mcp = FastMCP("test")
        register_blacklist_tools(test_mcp)
        with patch("src.tools.blacklist.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "manage_blacklist",
                    {
                        "restaurant_name": "Bad Place",
                        "action": "add",
                        "reason": "Terrible food",
                    },
                )
        text = str(result)
        assert "Blacklisted 'Bad Place'" in text
        is_bl = await db.is_blacklisted("place_abc")
        assert is_bl is True
        await db.close()

    async def test_add_without_cached_restaurant(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        test_mcp = FastMCP("test")
        register_blacklist_tools(test_mcp)
        with patch("src.tools.blacklist.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "manage_blacklist",
                    {
                        "restaurant_name": "Unknown Place",
                        "action": "add",
                        "reason": "Bad vibes",
                    },
                )
        text = str(result)
        assert "Blacklisted 'Unknown Place'" in text
        # Stored with name as ID
        is_bl = await db.is_blacklisted("Unknown Place")
        assert is_bl is True
        await db.close()

    async def test_add_without_reason(self):
        """Reason defaults to empty string when not provided."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        test_mcp = FastMCP("test")
        register_blacklist_tools(test_mcp)
        with patch("src.tools.blacklist.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "manage_blacklist",
                    {"restaurant_name": "No Reason Place"},
                )
        text = str(result)
        assert "Blacklisted 'No Reason Place'" in text
        blacklist = await db.get_blacklist()
        assert len(blacklist) == 1
        assert blacklist[0]["reason"] == ""
        await db.close()

    async def test_remove_with_cached_restaurant(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        restaurant = make_restaurant(
            id="place_xyz", name="Redeemed Place"
        )
        await db.cache_restaurant(restaurant)
        await db.add_to_blacklist(
            "place_xyz", "Redeemed Place", "Was bad"
        )
        test_mcp = FastMCP("test")
        register_blacklist_tools(test_mcp)
        with patch("src.tools.blacklist.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "manage_blacklist",
                    {
                        "restaurant_name": "Redeemed Place",
                        "action": "remove",
                    },
                )
        text = str(result)
        assert "Removed 'Redeemed Place' from blacklist" in text
        is_bl = await db.is_blacklisted("place_xyz")
        assert is_bl is False
        await db.close()

    async def test_remove_without_cached_restaurant(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        # Add with name as ID (no cache)
        await db.add_to_blacklist(
            "Uncached Place", "Uncached Place", "reason"
        )
        test_mcp = FastMCP("test")
        register_blacklist_tools(test_mcp)
        with patch("src.tools.blacklist.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "manage_blacklist",
                    {
                        "restaurant_name": "Uncached Place",
                        "action": "remove",
                    },
                )
        text = str(result)
        assert "Removed 'Uncached Place' from blacklist" in text
        is_bl = await db.is_blacklisted("Uncached Place")
        assert is_bl is False
        await db.close()

    async def test_unknown_action(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        test_mcp = FastMCP("test")
        register_blacklist_tools(test_mcp)
        with patch("src.tools.blacklist.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "manage_blacklist",
                    {
                        "restaurant_name": "Whatever",
                        "action": "destroy",
                    },
                )
        text = str(result)
        assert "Unknown action 'destroy'" in text
        assert "add" in text
        assert "remove" in text
        await db.close()

    async def test_add_cached_restaurant_no_reason(self):
        """Cached restaurant path with no reason provided."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        restaurant = make_restaurant(
            id="place_nr", name="No Reason Cached"
        )
        await db.cache_restaurant(restaurant)
        test_mcp = FastMCP("test")
        register_blacklist_tools(test_mcp)
        with patch("src.tools.blacklist.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "manage_blacklist",
                    {
                        "restaurant_name": "No Reason Cached",
                        "action": "add",
                    },
                )
        text = str(result)
        assert "Blacklisted 'No Reason Cached'" in text
        blacklist = await db.get_blacklist()
        assert len(blacklist) == 1
        assert blacklist[0]["reason"] == ""
        await db.close()
