from unittest.mock import patch

from fastmcp import Client, FastMCP

from src.storage.database import DatabaseManager
from src.tools.groups import register_group_tools
from tests.factories import make_group, make_person


class TestRegisterGroupTools:
    """Test tool registration."""

    def test_registration_succeeds(self):
        test_mcp = FastMCP("test")
        register_group_tools(test_mcp)


class TestManageGroup:
    """Test the manage_group tool."""

    async def test_create_group_with_valid_members(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        await db.save_person(make_person(name="Alice"))
        await db.save_person(make_person(name="Bob"))
        test_mcp = FastMCP("test")
        register_group_tools(test_mcp)
        with patch("src.tools.groups.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "manage_group",
                    {
                        "group_name": "dinner_crew",
                        "members": ["Alice", "Bob"],
                    },
                )
        text = str(result)
        assert "dinner_crew" in text
        assert "Alice" in text
        assert "Bob" in text
        group = await db.get_group("dinner_crew")
        assert group is not None
        assert set(group.member_names) == {"Alice", "Bob"}
        await db.close()

    async def test_create_group_with_invalid_members(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        await db.save_person(make_person(name="Alice"))
        test_mcp = FastMCP("test")
        register_group_tools(test_mcp)
        with patch("src.tools.groups.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "manage_group",
                    {
                        "group_name": "broken_group",
                        "members": ["Alice", "Ghost", "Phantom"],
                    },
                )
        text = str(result)
        assert "Cannot create group" in text
        assert "Ghost" in text
        assert "Phantom" in text
        assert "manage_person" in text
        # Group should NOT have been saved
        group = await db.get_group("broken_group")
        assert group is None
        await db.close()

    async def test_create_group_with_no_members(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        test_mcp = FastMCP("test")
        register_group_tools(test_mcp)
        with patch("src.tools.groups.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "manage_group",
                    {"group_name": "empty_group"},
                )
        text = str(result)
        assert "Members list is required" in text
        await db.close()

    async def test_create_group_with_empty_members_list(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        test_mcp = FastMCP("test")
        register_group_tools(test_mcp)
        with patch("src.tools.groups.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "manage_group",
                    {
                        "group_name": "empty_group",
                        "members": [],
                    },
                )
        text = str(result)
        assert "Members list is required" in text
        await db.close()

    async def test_remove_existing_group(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        p_id = await db.save_person(make_person(name="Alice"))
        await db.save_group(
            make_group(name="old_group", member_ids=[p_id])
        )
        test_mcp = FastMCP("test")
        register_group_tools(test_mcp)
        with patch("src.tools.groups.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "manage_group",
                    {"group_name": "old_group", "action": "remove"},
                )
        text = str(result)
        assert "Removed group 'old_group'" in text
        group = await db.get_group("old_group")
        assert group is None
        await db.close()

    async def test_remove_nonexistent_group(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        test_mcp = FastMCP("test")
        register_group_tools(test_mcp)
        with patch("src.tools.groups.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "manage_group",
                    {"group_name": "nope", "action": "remove"},
                )
        text = str(result)
        assert "No group named 'nope' found" in text
        await db.close()

    async def test_unknown_action(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        test_mcp = FastMCP("test")
        register_group_tools(test_mcp)
        with patch("src.tools.groups.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "manage_group",
                    {"group_name": "g", "action": "destroy"},
                )
        text = str(result)
        assert "Unknown action 'destroy'" in text
        assert "add" in text
        assert "remove" in text
        await db.close()

    async def test_create_group_shows_dietary_restrictions(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        await db.save_person(
            make_person(
                name="Alice",
                dietary_restrictions=["vegan", "nut-free"],
            )
        )
        await db.save_person(
            make_person(
                name="Bob",
                dietary_restrictions=["gluten-free"],
            )
        )
        test_mcp = FastMCP("test")
        register_group_tools(test_mcp)
        with patch("src.tools.groups.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "manage_group",
                    {
                        "group_name": "diet_group",
                        "members": ["Alice", "Bob"],
                    },
                )
        text = str(result)
        assert "diet_group" in text
        assert "Merged dietary restrictions" in text
        assert "vegan" in text
        assert "nut-free" in text
        assert "gluten-free" in text
        await db.close()

    async def test_create_group_no_dietary_restrictions(self):
        """Members with no restrictions -> no merged dietary line."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        await db.save_person(make_person(name="Alice"))
        await db.save_person(make_person(name="Bob"))
        test_mcp = FastMCP("test")
        register_group_tools(test_mcp)
        with patch("src.tools.groups.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "manage_group",
                    {
                        "group_name": "plain_group",
                        "members": ["Alice", "Bob"],
                    },
                )
        text = str(result)
        assert "plain_group" in text
        assert "Merged dietary" not in text
        await db.close()


class TestListGroups:
    """Test the list_groups tool."""

    async def test_list_empty(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        test_mcp = FastMCP("test")
        register_group_tools(test_mcp)
        with patch("src.tools.groups.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool("list_groups", {})
        text = str(result)
        assert "No groups saved yet" in text
        await db.close()

    async def test_list_with_groups_and_dietary(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        p1_id = await db.save_person(
            make_person(
                name="Alice",
                dietary_restrictions=["vegan"],
            )
        )
        p2_id = await db.save_person(
            make_person(
                name="Bob",
                dietary_restrictions=["gluten-free"],
            )
        )
        await db.save_group(
            make_group(name="Dinner Club", member_ids=[p1_id, p2_id])
        )
        test_mcp = FastMCP("test")
        register_group_tools(test_mcp)
        with patch("src.tools.groups.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool("list_groups", {})
        text = str(result)
        assert "Dinner Club" in text
        assert "Alice" in text
        assert "Bob" in text
        assert "Dietary:" in text
        assert "vegan" in text
        assert "gluten-free" in text
        await db.close()

    async def test_list_group_without_dietary(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        p_id = await db.save_person(make_person(name="Alice"))
        await db.save_group(
            make_group(name="Simple", member_ids=[p_id])
        )
        test_mcp = FastMCP("test")
        register_group_tools(test_mcp)
        with patch("src.tools.groups.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool("list_groups", {})
        text = str(result)
        assert "Simple" in text
        assert "Alice" in text
        assert "Dietary:" not in text
        await db.close()

    async def test_list_multiple_groups(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        p1_id = await db.save_person(make_person(name="Alice"))
        p2_id = await db.save_person(make_person(name="Bob"))
        await db.save_group(
            make_group(name="Team A", member_ids=[p1_id])
        )
        await db.save_group(
            make_group(name="Team B", member_ids=[p2_id])
        )
        test_mcp = FastMCP("test")
        register_group_tools(test_mcp)
        with patch("src.tools.groups.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool("list_groups", {})
        text = str(result)
        assert "Team A" in text
        assert "Team B" in text
        assert "Alice" in text
        assert "Bob" in text
        await db.close()
