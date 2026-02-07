from fastmcp import Client, FastMCP

from src.tools.search import register_search_tools


class TestRegisterSearchTools:
    """Test tool registration."""

    def test_registration_succeeds(self):
        test_mcp = FastMCP("test")
        register_search_tools(test_mcp)


class TestSearchRestaurants:
    """Test the placeholder search tool."""

    async def test_returns_placeholder_with_query(self):
        test_mcp = FastMCP("test")
        register_search_tools(test_mcp)
        async with Client(test_mcp) as client:
            result = await client.call_tool(
                "search_restaurants", {"query": "Italian near home"}
            )
        assert "Italian near home" in str(result)

    async def test_includes_not_implemented_message(self):
        test_mcp = FastMCP("test")
        register_search_tools(test_mcp)
        async with Client(test_mcp) as client:
            result = await client.call_tool("search_restaurants", {"query": "sushi"})
        assert "not yet implemented" in str(result).lower()
