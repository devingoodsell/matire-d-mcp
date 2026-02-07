"""MCP tools for visit history and restaurant reviews."""

import logging
from datetime import date

from fastmcp import FastMCP

from src.server import get_db

logger = logging.getLogger(__name__)


def register_history_tools(mcp: FastMCP) -> None:  # noqa: C901
    """Register visit history and review tools on the MCP server."""

    @mcp.tool
    async def log_visit(
        restaurant_name: str,
        date_str: str | None = None,
        party_size: int = 2,
        companions: list[str] | None = None,
        cuisine: str | None = None,
    ) -> str:
        """Log a restaurant visit (for places booked outside the system).
        Visits booked through this assistant are logged automatically.

        Args:
            restaurant_name: Name of the restaurant you visited.
            date_str: Date of visit, e.g. "2026-02-10" or "last Tuesday"
                      (default: today).
            party_size: Number of diners.
            companions: Names of who you dined with, e.g. ["Alice", "Bob"].
            cuisine: Type of cuisine, e.g. "italian", "mexican".

        Returns:
            Confirmation with visit ID for adding a review.
        """
        from src.models.review import Visit
        from src.tools.date_utils import parse_date

        db = get_db()

        # Parse date
        if date_str:
            try:
                parsed_date = parse_date(date_str)
            except ValueError:
                parsed_date = date.today().isoformat()
        else:
            parsed_date = date.today().isoformat()

        # Try to match restaurant to cache
        cached = await db.search_cached_restaurants(restaurant_name)
        if cached:
            restaurant = cached[0]
            restaurant_id = restaurant.id
            display_name = restaurant.name
            # Get cuisine from cached restaurant if not provided
            if not cuisine and restaurant.cuisine:
                cuisine = restaurant.cuisine[0]
        else:
            restaurant_id = ""
            display_name = restaurant_name

        visit = Visit(
            restaurant_id=restaurant_id,
            restaurant_name=display_name,
            date=parsed_date,
            party_size=party_size,
            companions=companions or [],
            cuisine=cuisine,
            source="manual",
        )
        visit_id = await db.log_visit(visit)

        companion_note = ""
        if companions:
            companion_note = f" with {', '.join(companions)}"

        return (
            f"Visit logged! {display_name} on {parsed_date}, "
            f"party of {party_size}{companion_note}.\n"
            f"Visit ID: {visit_id} — use rate_visit to add a review."
        )

    @mcp.tool
    async def rate_visit(
        restaurant_name: str,
        would_return: bool,
        overall_rating: int | None = None,
        noise_level: str | None = None,
        dishes: list[dict] | None = None,
        notes: str | None = None,
    ) -> str:
        """Rate a restaurant you recently visited. Used to improve
        future recommendations.

        Args:
            restaurant_name: Name of the restaurant.
            would_return: True if you'd go back, False if not.
            overall_rating: 1-5 stars (optional).
            noise_level: "quiet", "moderate", or "loud" — helps calibrate
                         future recs.
            dishes: List of dishes with ratings, e.g.
                    [{"name": "cacio e pepe", "rating": 5, "order_again": true}].
            notes: Any additional notes, e.g. "Great for date night".

        Returns:
            Confirmation that the review was saved.
        """
        from src.models.enums import NoiseLevel
        from src.models.review import DishReview, VisitReview

        db = get_db()

        # Find the most recent visit for this restaurant
        visit = await db.get_visit_by_restaurant_name(restaurant_name)
        if not visit or visit.id is None:
            return (
                f"No recent visit found for '{restaurant_name}'. "
                "Log a visit first with log_visit."
            )

        # Check if already reviewed
        existing = await db.get_visit_review(visit.id)
        if existing:
            return (
                f"Visit to {visit.restaurant_name} on {visit.date} "
                "already has a review."
            )

        # Parse noise level
        parsed_noise = None
        if noise_level:
            try:
                parsed_noise = NoiseLevel(noise_level.lower())
            except ValueError:
                pass

        # Save visit review
        review = VisitReview(
            visit_id=visit.id,
            would_return=would_return,
            overall_rating=overall_rating,
            noise_level=parsed_noise,
            notes=notes,
        )
        await db.save_visit_review(review)

        # Save dish reviews
        dish_count = 0
        if dishes:
            for dish in dishes:
                dish_review = DishReview(
                    visit_id=visit.id,
                    dish_name=dish.get("name", "Unknown"),
                    rating=dish.get("rating", 3),
                    would_order_again=dish.get("order_again", True),
                    notes=dish.get("notes"),
                )
                await db.save_dish_review(dish_review)
                dish_count += 1

        # Format response
        rating_str = f" ({overall_rating}/5)" if overall_rating else ""
        return_str = "would return" if would_return else "would not return"
        dish_str = f" {dish_count} dish reviews saved." if dish_count else ""
        return (
            f"Review saved for {visit.restaurant_name}{rating_str} — "
            f"{return_str}.{dish_str}"
        )

    @mcp.tool
    async def visit_history(
        days: int = 90,
        cuisine: str | None = None,
    ) -> str:
        """Show your recent restaurant visit history.

        Args:
            days: How many days back to look (default 90).
            cuisine: Filter by cuisine type (optional).

        Returns:
            Formatted list of recent visits with dates, ratings, and notes.
        """
        db = get_db()
        visits = await db.get_recent_visits(days=days)

        if cuisine:
            cuisine_lower = cuisine.lower()
            filtered = []
            for v in visits:
                # Check visit-level cuisine
                if v.cuisine and cuisine_lower in v.cuisine.lower():
                    filtered.append(v)
                    continue
                # Check cached restaurant cuisine
                if v.restaurant_id:
                    cached = await db.get_cached_restaurant(v.restaurant_id)
                    if cached and any(
                        cuisine_lower in c.lower() for c in cached.cuisine
                    ):
                        filtered.append(v)
            visits = filtered

        if not visits:
            period = f"last {days} days"
            cuisine_note = f" for {cuisine}" if cuisine else ""
            return f"No visits recorded in the {period}{cuisine_note}."

        lines = [f"Visit history ({len(visits)} visits):"]
        for v in visits:
            companion_str = ""
            if v.companions:
                companion_str = f" with {', '.join(v.companions)}"

            cuisine_str = ""
            if v.cuisine:
                cuisine_str = f" ({v.cuisine})"

            line = (
                f"  {v.restaurant_name}{cuisine_str} — {v.date}, "
                f"party of {v.party_size}{companion_str}"
            )

            # Add review info if available
            if v.id is not None:
                review = await db.get_visit_review(v.id)
                if review:
                    rating = f" {review.overall_rating}/5" if review.overall_rating else ""
                    ret = " (would return)" if review.would_return else " (would not return)"
                    line += f"{rating}{ret}"

            lines.append(line)

        return "\n".join(lines)
