import logging

from fastmcp import FastMCP

from src.server import get_db

logger = logging.getLogger(__name__)


def register_wishlist_tools(mcp: FastMCP) -> None:
    """Register wishlist management tools on the MCP server."""

    @mcp.tool
    async def manage_wishlist(
        restaurant_name: str,
        action: str = "add",
        notes: str | None = None,
        tags: str | None = None,
    ) -> str:
        """Add or remove restaurants from your wishlist — places you want
        to try in the future.  Wishlisted restaurants get a boost in
        recommendations when you're nearby.

        The restaurant must already appear in search results (search first).

        Args:
            restaurant_name: Name of the restaurant.
            action: "add" to wishlist, "remove" to un-wishlist.
            notes: Free-text notes (e.g. "get the tasting menu").
            tags: Comma-separated tags for filtering, e.g.
                  "date night, special occasion".  Common tags:
                  date night, group dinner, special occasion, brunch,
                  solo, outdoor, weeknight.

        Returns:
            Confirmation of the action.
        """
        db = get_db()
        parsed_tags = (
            [t.strip().lower() for t in tags.split(",") if t.strip()]
            if tags
            else []
        )

        if action == "add":
            cached = await db.search_cached_restaurants(restaurant_name)
            if not cached:
                return (
                    f"Restaurant '{restaurant_name}' not found in cache. "
                    "Please search for it first using search_restaurants."
                )
            restaurant = cached[0]
            already = await db.is_on_wishlist(restaurant.id)
            await db.add_to_wishlist(
                restaurant.id, restaurant.name, notes, parsed_tags
            )
            if already:
                return f"Updated '{restaurant.name}' on your wishlist."
            return f"Added '{restaurant.name}' to your wishlist."

        if action == "remove":
            cached = await db.search_cached_restaurants(restaurant_name)
            if cached:
                removed = await db.remove_from_wishlist(cached[0].id)
                if removed:
                    return f"Removed '{cached[0].name}' from your wishlist."
                return f"'{cached[0].name}' was not on your wishlist."
            removed = await db.remove_from_wishlist(restaurant_name)
            if removed:
                return f"Removed '{restaurant_name}' from your wishlist."
            return f"'{restaurant_name}' was not on your wishlist."

        return f"Unknown action '{action}'. Use 'add' or 'remove'."

    @mcp.tool
    async def my_wishlist(tag: str | None = None) -> str:
        """Show your restaurant wishlist, optionally filtered by tag.

        Args:
            tag: Filter by a single tag (e.g. "date night").

        Returns:
            Numbered list of wishlisted restaurants with details.
        """
        db = get_db()
        items = await db.get_wishlist(tag=tag)

        if not items:
            if tag:
                return f"Your wishlist has no restaurants tagged '{tag}'."
            return "Your wishlist is empty."

        lines: list[str] = []
        header = f"Your wishlist (tag: {tag}):" if tag else "Your wishlist:"
        lines.append(header)

        for i, item in enumerate(items, 1):
            # Try to enrich with cached data
            cached = await db.get_cached_restaurant(item.restaurant_id)
            if cached:
                rating_str = f"{cached.rating:.1f}" if cached.rating else "?"
                cuisine_str = (
                    ", ".join(cached.cuisine) if cached.cuisine else "Various"
                )
                line = f"{i}. {item.restaurant_name} ({rating_str}\u2605, {cuisine_str})"
            else:
                line = f"{i}. {item.restaurant_name}"

            if item.notes:
                line += f"\n   Notes: {item.notes}"
            if item.tags:
                line += f"\n   Tags: {', '.join(item.tags)}"
            if item.added_date:
                line += f"\n   Added: {item.added_date}"

            lines.append(line)

        return "\n\n".join(lines)
