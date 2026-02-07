from unittest.mock import patch

from fastmcp import Client, FastMCP

from src.storage.database import DatabaseManager
from src.tools.people import register_people_tools
from tests.factories import make_person


class TestRegisterPeopleTools:
    """Test tool registration."""

    def test_registration_succeeds(self):
        test_mcp = FastMCP("test")
        register_people_tools(test_mcp)


class TestManagePerson:
    """Test the manage_person tool."""

    async def test_add_basic_person(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        test_mcp = FastMCP("test")
        register_people_tools(test_mcp)
        with patch("src.tools.people.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "manage_person", {"name": "Alice"}
                )
        text = str(result)
        assert "Saved 'Alice'" in text
        # Verify persisted
        person = await db.get_person("Alice")
        assert person is not None
        assert person.name == "Alice"
        assert person.dietary_restrictions == []
        assert person.no_alcohol is False
        assert person.notes is None
        await db.close()

    async def test_add_person_with_all_attributes(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        test_mcp = FastMCP("test")
        register_people_tools(test_mcp)
        with patch("src.tools.people.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "manage_person",
                    {
                        "name": "Bob",
                        "dietary_restrictions": ["vegan", "nut_allergy"],
                        "no_alcohol": True,
                        "notes": "Prefers window seats",
                    },
                )
        text = str(result)
        assert "Saved 'Bob'" in text
        assert "vegan" in text
        assert "nut_allergy" in text
        assert "No alcohol" in text
        assert "Prefers window seats" in text
        person = await db.get_person("Bob")
        assert person is not None
        assert set(person.dietary_restrictions) == {"vegan", "nut_allergy"}
        assert person.no_alcohol is True
        assert person.notes == "Prefers window seats"
        await db.close()

    async def test_update_existing_person_upsert(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        # Pre-save a person
        await db.save_person(
            make_person(name="Alice", notes="original")
        )
        test_mcp = FastMCP("test")
        register_people_tools(test_mcp)
        with patch("src.tools.people.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "manage_person",
                    {
                        "name": "Alice",
                        "action": "add",
                        "notes": "updated",
                    },
                )
        text = str(result)
        assert "Saved 'Alice'" in text
        person = await db.get_person("Alice")
        assert person is not None
        assert person.notes == "updated"
        # Only one person in DB
        people = await db.get_people()
        assert len(people) == 1
        await db.close()

    async def test_remove_existing_person(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        await db.save_person(make_person(name="Alice"))
        test_mcp = FastMCP("test")
        register_people_tools(test_mcp)
        with patch("src.tools.people.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "manage_person",
                    {"name": "Alice", "action": "remove"},
                )
        text = str(result)
        assert "Removed 'Alice'" in text
        person = await db.get_person("Alice")
        assert person is None
        await db.close()

    async def test_remove_nonexistent_person(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        test_mcp = FastMCP("test")
        register_people_tools(test_mcp)
        with patch("src.tools.people.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "manage_person",
                    {"name": "Ghost", "action": "remove"},
                )
        text = str(result)
        assert "No person named 'Ghost' found" in text
        await db.close()

    async def test_unknown_action(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        test_mcp = FastMCP("test")
        register_people_tools(test_mcp)
        with patch("src.tools.people.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "manage_person",
                    {"name": "Alice", "action": "destroy"},
                )
        text = str(result)
        assert "Unknown action 'destroy'" in text
        assert "add" in text
        assert "remove" in text
        await db.close()

    async def test_add_with_dietary_but_no_alcohol_false_no_notes(self):
        """Branch: dietary truthy, no_alcohol false, notes None."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        test_mcp = FastMCP("test")
        register_people_tools(test_mcp)
        with patch("src.tools.people.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "manage_person",
                    {
                        "name": "Carol",
                        "dietary_restrictions": ["gluten-free"],
                    },
                )
        text = str(result)
        assert "Saved 'Carol'" in text
        assert "gluten-free" in text
        assert "No alcohol" not in text
        assert "Notes:" not in text
        await db.close()

    async def test_add_with_no_alcohol_only(self):
        """Branch: no dietary, no_alcohol true, no notes."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        test_mcp = FastMCP("test")
        register_people_tools(test_mcp)
        with patch("src.tools.people.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "manage_person",
                    {
                        "name": "Dave",
                        "no_alcohol": True,
                    },
                )
        text = str(result)
        assert "Saved 'Dave'" in text
        assert "No alcohol" in text
        assert "Dietary:" not in text
        await db.close()

    async def test_add_with_notes_only(self):
        """Branch: no dietary, no_alcohol false, notes present."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        test_mcp = FastMCP("test")
        register_people_tools(test_mcp)
        with patch("src.tools.people.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool(
                    "manage_person",
                    {
                        "name": "Eve",
                        "notes": "Likes quiet spots",
                    },
                )
        text = str(result)
        assert "Saved 'Eve'" in text
        assert "Notes: Likes quiet spots" in text
        assert "Dietary:" not in text
        assert "No alcohol" not in text
        await db.close()


class TestListPeople:
    """Test the list_people tool."""

    async def test_list_empty(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        test_mcp = FastMCP("test")
        register_people_tools(test_mcp)
        with patch("src.tools.people.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool("list_people", {})
        text = str(result)
        assert "No dining companions saved yet" in text
        await db.close()

    async def test_list_with_people(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        await db.save_person(
            make_person(
                name="Alice",
                dietary_restrictions=["vegan"],
                no_alcohol=True,
                notes="Prefers quiet",
            )
        )
        await db.save_person(make_person(name="Bob"))
        test_mcp = FastMCP("test")
        register_people_tools(test_mcp)
        with patch("src.tools.people.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool("list_people", {})
        text = str(result)
        assert "Alice" in text
        assert "vegan" in text
        assert "no alcohol" in text
        assert "Prefers quiet" in text
        assert "Bob" in text
        await db.close()

    async def test_list_person_no_dietary_no_alcohol_no_notes(self):
        """Person with no optional fields set."""
        db = DatabaseManager(":memory:")
        await db.initialize()
        await db.save_person(make_person(name="Plain"))
        test_mcp = FastMCP("test")
        register_people_tools(test_mcp)
        with patch("src.tools.people.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool("list_people", {})
        text = str(result)
        assert "- Plain" in text
        assert "dietary" not in text.lower().replace("- plain", "")
        await db.close()

    async def test_list_person_with_dietary_only(self):
        db = DatabaseManager(":memory:")
        await db.initialize()
        await db.save_person(
            make_person(name="Dieter", dietary_restrictions=["keto"])
        )
        test_mcp = FastMCP("test")
        register_people_tools(test_mcp)
        with patch("src.tools.people.get_db", return_value=db):
            async with Client(test_mcp) as client:
                result = await client.call_tool("list_people", {})
        text = str(result)
        assert "Dieter" in text
        assert "keto" in text
        await db.close()
