from fastmcp import FastMCP


def register_search_tools(mcp: FastMCP) -> None:
    """Register restaurant search tools on the MCP server.

    Dependencies (google_client, db) will be added in EPIC-04 when
    the full search implementation is built.
    """

    @mcp.tool
    async def search_restaurants(query: str) -> str:
        """Search for restaurants matching your criteria.

        This is a placeholder — full implementation with Google Places
        integration, preference filtering, and location awareness
        is coming in EPIC-04.

        Args:
            query: What you're looking for, e.g. "Italian near home"
                   or "quiet sushi place for date night".

        Returns:
            Search results with restaurant names, ratings, and details.

        Example:
            search_restaurants("Italian restaurants near home")
        """
        return f"Search not yet implemented. Query: {query}"
