import logging

from fastmcp import FastMCP

from src.clients.geocoding import geocode_address
from src.models.enums import Ambiance, CuisineCategory, PriceLevel, SeatingPreference
from src.models.user import CuisinePreference, Location, PricePreference, UserPreferences
from src.server import get_db

logger = logging.getLogger(__name__)


def register_preference_tools(mcp: FastMCP) -> None:
    """Register user preference management tools on the MCP server."""

    @mcp.tool
    async def setup_preferences(
        name: str,
        home_address: str | None = None,
        work_address: str | None = None,
        dietary_restrictions: list[str] | None = None,
        favorite_cuisines: list[str] | None = None,
        cuisines_to_avoid: list[str] | None = None,
        price_levels: list[int] | None = None,
        noise_preference: str = "moderate",
        seating_preference: str = "no_preference",
        max_walk_minutes: int = 15,
        default_party_size: int = 2,
        rating_threshold: float = 4.0,
    ) -> str:
        """Set up or update your restaurant preferences. Call this when the user
        first configures the assistant or wants to change their profile.

        Args:
            name: User's first name.
            home_address: Home address for "near home" searches.
            work_address: Work address for "near work" searches.
            dietary_restrictions: E.g. ["vegetarian", "nut_allergy"].
            favorite_cuisines: Cuisines you love, e.g. ["italian", "korean"].
            cuisines_to_avoid: Cuisines you dislike, e.g. ["fast_food"].
            price_levels: Acceptable price levels 1-4, e.g. [2, 3].
            noise_preference: "quiet", "moderate", or "lively".
            seating_preference: "indoor", "outdoor", or "no_preference".
            max_walk_minutes: Maximum walking time from location (default 15).
            default_party_size: Usual party size (default 2).
            rating_threshold: Minimum Google rating to show (default 4.0).

        Returns:
            Confirmation message with saved preferences summary.
        """
        db = get_db()

        # Save core preferences
        prefs = UserPreferences(
            name=name,
            rating_threshold=rating_threshold,
            noise_preference=Ambiance(noise_preference),
            seating_preference=SeatingPreference(seating_preference),
            max_walk_minutes=max_walk_minutes,
            default_party_size=default_party_size,
        )
        await db.save_preferences(prefs)

        # Save dietary restrictions
        if dietary_restrictions is not None:
            await db.set_dietary_restrictions(dietary_restrictions)

        # Save cuisine preferences
        if favorite_cuisines is not None or cuisines_to_avoid is not None:
            cuisine_prefs: list[CuisinePreference] = []
            for c in favorite_cuisines or []:
                cuisine_prefs.append(
                    CuisinePreference(cuisine=c, category=CuisineCategory.FAVORITE)
                )
            for c in cuisines_to_avoid or []:
                cuisine_prefs.append(
                    CuisinePreference(cuisine=c, category=CuisineCategory.AVOID)
                )
            await db.set_cuisine_preferences(cuisine_prefs)

        # Save price preferences
        if price_levels is not None:
            price_prefs = [
                PricePreference(price_level=PriceLevel(lvl), acceptable=True)
                for lvl in price_levels
            ]
            await db.set_price_preferences(price_prefs)

        # Geocode and save locations
        from src.config import get_settings

        api_key = get_settings().google_api_key
        saved_locations: list[str] = []

        for label, address in [("home", home_address), ("work", work_address)]:
            if address:
                coords = await geocode_address(address, api_key)
                if coords:
                    lat, lng = coords
                    loc = Location(
                        name=label, address=address, lat=lat, lng=lng,
                        walk_radius_minutes=max_walk_minutes,
                    )
                    await db.save_location(loc)
                    saved_locations.append(f"{label} ({address})")
                else:
                    saved_locations.append(
                        f"{label} (could not geocode: {address})"
                    )

        # Build confirmation
        parts = [f"Preferences saved for {name}."]
        if dietary_restrictions:
            parts.append(f"Dietary: {', '.join(dietary_restrictions)}")
        if favorite_cuisines:
            parts.append(f"Favorites: {', '.join(favorite_cuisines)}")
        if cuisines_to_avoid:
            parts.append(f"Avoid: {', '.join(cuisines_to_avoid)}")
        if price_levels:
            parts.append(f"Price levels: {', '.join(str(p) for p in price_levels)}")
        if saved_locations:
            parts.append(f"Locations: {'; '.join(saved_locations)}")
        parts.append(
            f"Noise: {noise_preference}, Seating: {seating_preference}, "
            f"Walk: {max_walk_minutes}min, Party: {default_party_size}, "
            f"Min rating: {rating_threshold}"
        )
        return "\n".join(parts)

    @mcp.tool
    async def get_my_preferences() -> str:
        """Show all your current restaurant preferences including dietary
        restrictions, favorite cuisines, saved locations, and dining defaults.

        Returns:
            A formatted summary of all preferences.
        """
        db = get_db()
        prefs = await db.get_preferences()
        if not prefs:
            return "No preferences configured yet. Use setup_preferences to get started."

        dietary = await db.get_dietary_restrictions()
        cuisines = await db.get_cuisine_preferences()
        prices = await db.get_price_preferences()
        locations = await db.get_locations()

        parts = [f"Preferences for {prefs.name}:"]
        parts.append(
            f"  Noise: {prefs.noise_preference.value}, "
            f"Seating: {prefs.seating_preference.value}"
        )
        parts.append(
            f"  Walk: {prefs.max_walk_minutes}min, "
            f"Party size: {prefs.default_party_size}, "
            f"Min rating: {prefs.rating_threshold}"
        )

        if dietary:
            parts.append(f"  Dietary: {', '.join(dietary)}")

        favorites = [c.cuisine for c in cuisines if c.category == CuisineCategory.FAVORITE]
        avoid = [c.cuisine for c in cuisines if c.category == CuisineCategory.AVOID]
        if favorites:
            parts.append(f"  Favorite cuisines: {', '.join(favorites)}")
        if avoid:
            parts.append(f"  Avoid cuisines: {', '.join(avoid)}")

        acceptable = [str(p.price_level.value) for p in prices if p.acceptable]
        if acceptable:
            parts.append(f"  Price levels: {', '.join(acceptable)}")

        for loc in locations:
            parts.append(f"  Location '{loc.name}': {loc.address}")

        return "\n".join(parts)

    @mcp.tool
    async def update_preferences(
        dietary_restrictions: list[str] | None = None,
        add_favorite_cuisine: str | None = None,
        remove_favorite_cuisine: str | None = None,
        add_avoid_cuisine: str | None = None,
        noise_preference: str | None = None,
        seating_preference: str | None = None,
        rating_threshold: float | None = None,
        default_party_size: int | None = None,
        max_walk_minutes: int | None = None,
    ) -> str:
        """Update specific preferences without resetting everything.
        Only provided fields are changed; everything else stays the same.

        Args:
            dietary_restrictions: Replace full dietary list.
            add_favorite_cuisine: Add a single cuisine to favorites.
            remove_favorite_cuisine: Remove a cuisine from favorites.
            add_avoid_cuisine: Add a cuisine to avoid list.
            noise_preference: "quiet", "moderate", or "lively".
            seating_preference: "indoor", "outdoor", or "no_preference".
            rating_threshold: Minimum Google rating.
            default_party_size: Usual party size.
            max_walk_minutes: Maximum walking time.

        Returns:
            Confirmation of what was changed.
        """
        db = get_db()
        prefs = await db.get_preferences()
        if not prefs:
            return "No preferences configured yet. Use setup_preferences first."

        changes: list[str] = []

        # Update dietary restrictions
        if dietary_restrictions is not None:
            await db.set_dietary_restrictions(dietary_restrictions)
            changes.append(f"Dietary: {', '.join(dietary_restrictions)}")

        # Update cuisine preferences
        if add_favorite_cuisine or remove_favorite_cuisine or add_avoid_cuisine:
            current = await db.get_cuisine_preferences()
            updated = list(current)

            if add_favorite_cuisine:
                updated.append(
                    CuisinePreference(
                        cuisine=add_favorite_cuisine,
                        category=CuisineCategory.FAVORITE,
                    )
                )
                changes.append(f"Added favorite: {add_favorite_cuisine}")

            if remove_favorite_cuisine:
                updated = [
                    c for c in updated
                    if not (
                        c.cuisine == remove_favorite_cuisine
                        and c.category == CuisineCategory.FAVORITE
                    )
                ]
                changes.append(f"Removed favorite: {remove_favorite_cuisine}")

            if add_avoid_cuisine:
                updated.append(
                    CuisinePreference(
                        cuisine=add_avoid_cuisine,
                        category=CuisineCategory.AVOID,
                    )
                )
                changes.append(f"Added avoid: {add_avoid_cuisine}")

            await db.set_cuisine_preferences(updated)

        # Update scalar preferences
        changed_prefs = False
        if noise_preference is not None:
            prefs.noise_preference = Ambiance(noise_preference)
            changes.append(f"Noise: {noise_preference}")
            changed_prefs = True
        if seating_preference is not None:
            prefs.seating_preference = SeatingPreference(seating_preference)
            changes.append(f"Seating: {seating_preference}")
            changed_prefs = True
        if rating_threshold is not None:
            prefs.rating_threshold = rating_threshold
            changes.append(f"Min rating: {rating_threshold}")
            changed_prefs = True
        if default_party_size is not None:
            prefs.default_party_size = default_party_size
            changes.append(f"Party size: {default_party_size}")
            changed_prefs = True
        if max_walk_minutes is not None:
            prefs.max_walk_minutes = max_walk_minutes
            changes.append(f"Walk: {max_walk_minutes}min")
            changed_prefs = True

        if changed_prefs:
            await db.save_preferences(prefs)

        if not changes:
            return "No changes specified."
        return "Updated: " + "; ".join(changes)
