import logging

from fastmcp import FastMCP

from src.server import get_db

logger = logging.getLogger(__name__)


def register_blacklist_tools(mcp: FastMCP) -> None:
    """Register blacklist management tools on the MCP server."""

    @mcp.tool
    async def manage_blacklist(
        restaurant_name: str,
        action: str = "add",
        reason: str | None = None,
    ) -> str:
        """Add or remove restaurants from your blacklist. Blacklisted
        restaurants will never appear in search results or recommendations.

        Args:
            restaurant_name: Name of the restaurant.
            action: "add" to blacklist, "remove" to un-blacklist.
            reason: Why you're blacklisting (for your records).

        Returns:
            Confirmation of the action.
        """
        db = get_db()

        if action == "add":
            # Try to find restaurant in cache for its ID
            cached = await db.search_cached_restaurants(restaurant_name)
            if cached:
                restaurant = cached[0]
                await db.add_to_blacklist(
                    restaurant.id, restaurant.name, reason or ""
                )
                return f"Blacklisted '{restaurant.name}'."
            # Store with name as ID if not cached
            await db.add_to_blacklist(
                restaurant_name, restaurant_name, reason or ""
            )
            return f"Blacklisted '{restaurant_name}'."

        if action == "remove":
            # Try cached first
            cached = await db.search_cached_restaurants(restaurant_name)
            if cached:
                await db.remove_from_blacklist(cached[0].id)
                return f"Removed '{cached[0].name}' from blacklist."
            await db.remove_from_blacklist(restaurant_name)
            return f"Removed '{restaurant_name}' from blacklist."

        return f"Unknown action '{action}'. Use 'add' or 'remove'."
