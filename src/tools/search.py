import logging

from fastmcp import FastMCP

from src.clients.distance import walking_minutes
from src.clients.geocoding import geocode_address
from src.clients.google_places import GooglePlacesClient
from src.models.restaurant import Restaurant
from src.server import get_db

logger = logging.getLogger(__name__)

# Price level display symbols
_PRICE_SYMBOLS = {1: "$", 2: "$$", 3: "$$$", 4: "$$$$"}


def _format_result(
    idx: int,
    r: Restaurant,
    walk_min: int | None,
) -> str:
    """Format a single restaurant for display."""
    price = _PRICE_SYMBOLS.get(r.price_level or 0, "?")
    rating_str = f"{r.rating:.1f}" if r.rating else "?"
    walk_str = f" - ~{walk_min} min walk" if walk_min is not None else ""

    lines = [f"{idx}. {r.name} ({rating_str}\u2605, {price}){walk_str}"]
    lines.append(f"   {r.address}")

    parts: list[str] = []
    if r.cuisine:
        parts.append(f"Cuisine: {', '.join(r.cuisine)}")
    platforms: list[str] = []
    if r.resy_venue_id:
        platforms.append("Resy")
    if r.opentable_id:
        platforms.append("OpenTable")
    if platforms:
        parts.append(f"Available on: {', '.join(platforms)}")
    if parts:
        lines.append(f"   {' | '.join(parts)}")

    return "\n".join(lines)


def register_search_tools(mcp: FastMCP) -> None:
    """Register restaurant search tools on the MCP server."""

    @mcp.tool
    async def search_restaurants(
        cuisine: str | None = None,
        location: str = "home",
        party_size: int = 2,
        price_max: int | None = None,
        outdoor_seating: bool = False,
        query: str | None = None,
        max_results: int = 5,
    ) -> str:
        """Search for restaurants matching your criteria near a location.
        Automatically applies your dietary restrictions, cuisine preferences,
        minimum rating threshold, and blacklist.

        Args:
            cuisine: Type of food, e.g. "italian", "mexican", "sushi".
                     Leave empty to search all cuisines.
            location: Where to search near. Use "home", "work", or a
                      specific NYC address.
            party_size: Number of diners.
            price_max: Maximum price level 1-4. Leave empty to use your
                       saved price preferences.
            outdoor_seating: True if outdoor seating is specifically desired.
            query: Free-text search for specific restaurants or features,
                   e.g. "rooftop bar", "Carbone".
            max_results: Maximum restaurants to return (default 5, max 10).

        Returns:
            Formatted list of matching restaurants with ratings,
            prices, walking distance, and cuisine info.
        """
        db = get_db()
        max_results = min(max_results, 10)

        # ── 1. Resolve location to coordinates ──────────────────────────
        from src.config import get_settings

        settings = get_settings()

        user_lat: float | None = None
        user_lng: float | None = None

        saved_loc = await db.get_location(location)
        if saved_loc:
            user_lat, user_lng = saved_loc.lat, saved_loc.lng
        else:
            coords = await geocode_address(location, settings.google_api_key)
            if coords:
                user_lat, user_lng = coords
            else:
                return (
                    f"Could not resolve location '{location}'. "
                    "Use 'home', 'work', or a valid NYC address."
                )

        # ── 2. Weather check for outdoor seating ──────────────────────
        weather_note = ""
        if outdoor_seating and settings.openweather_api_key:
            try:
                from src.clients.weather import WeatherClient

                weather_client = WeatherClient(settings.openweather_api_key)
                weather = await weather_client.get_weather(user_lat, user_lng)
                if not weather.outdoor_suitable:
                    outdoor_seating = False
                    weather_note = (
                        f"Note: {weather.description.capitalize()} "
                        f"({weather.temperature_f:.0f}°F). "
                        "Showing indoor options instead.\n\n"
                    )
            except Exception:  # noqa: BLE001
                logger.warning("Weather check failed, skipping")

        # ── 3. Build search query ───────────────────────────────────────
        if query:
            search_query = f"{query} New York"
        elif cuisine:
            search_query = f"{cuisine} restaurant"
        else:
            search_query = "restaurant"

        if outdoor_seating:
            search_query += " outdoor seating"

        # ── 4. Load user preferences for filtering ──────────────────────
        prefs = await db.get_preferences()
        cuisine_prefs = await db.get_cuisine_preferences()
        price_prefs = await db.get_price_preferences()

        rating_threshold = prefs.rating_threshold if prefs else 4.0
        walk_limit = prefs.max_walk_minutes if prefs else 15

        avoided_cuisines: set[str] = set()
        for cp in cuisine_prefs:
            if cp.category.value == "avoid":
                avoided_cuisines.add(cp.cuisine.lower())

        acceptable_prices: set[int] | None = None
        if price_max:
            acceptable_prices = set(range(1, price_max + 1))
        elif price_prefs:
            acceptable_prices = {
                p.price_level.value for p in price_prefs if p.acceptable
            }

        # ── 5. Search via Google Places ─────────────────────────────────
        # Convert walk limit to radius: 83 m/min × walk_limit / 1.3 manhattan factor
        radius_m = int(walk_limit * 83 / 1.3)
        client = GooglePlacesClient(
            api_key=settings.google_api_key, db=db
        )
        results = await client.search_nearby(
            query=search_query,
            lat=user_lat,
            lng=user_lng,
            radius_meters=radius_m,
            max_results=20,
        )

        # Cache results
        for r in results:
            await db.cache_restaurant(r)

        # ── 6. Filter results ───────────────────────────────────────────
        filtered: list[Restaurant] = []
        for r in results:
            # Blacklist check
            if await db.is_blacklisted(r.id):
                continue

            # Rating threshold
            if r.rating is not None and r.rating < rating_threshold:
                continue

            # Price filter
            if acceptable_prices and r.price_level is not None:
                if r.price_level not in acceptable_prices:
                    continue

            # Avoided cuisines
            if r.cuisine and avoided_cuisines:
                if any(c.lower() in avoided_cuisines for c in r.cuisine):
                    continue

            filtered.append(r)

        # ── 7. Recency-aware sorting ────────────────────────────────────
        recency_penalties = await db.get_recency_penalties(days=14)
        recency_notes: list[str] = []

        def sort_key(r: Restaurant) -> tuple[float, float]:
            rating = -(r.rating or 0.0)
            dist = walking_minutes(user_lat, user_lng, r.lat, r.lng)  # type: ignore[arg-type]

            # Apply recency penalty to deprioritize recently-visited cuisines
            penalty = 0.0
            if r.cuisine:
                for c in r.cuisine:
                    p = recency_penalties.get(c.lower(), 0.0)
                    if p > penalty:
                        penalty = p
            # Penalty shifts rating: 0.8 penalty → effectively -0.8 rating
            adjusted_rating = rating + penalty

            return (adjusted_rating, dist)

        filtered.sort(key=sort_key)
        filtered = filtered[:max_results]

        # Check which results have recency penalties to note
        for r in filtered:
            if r.cuisine:
                for c in r.cuisine:
                    penalty = recency_penalties.get(c.lower(), 0.0)
                    if penalty >= 0.5:
                        days_approx = int((1.0 - penalty) * 14)
                        note = (
                            f"You had {c} ~{days_approx} days ago — "
                            "showing other options first"
                        )
                        if note not in recency_notes:
                            recency_notes.append(note)

        if not filtered:
            return "No restaurants found matching your criteria. Try broadening your search."

        # ── 8. Format output ────────────────────────────────────────────
        cuisine_label = f" {cuisine}" if cuisine else ""
        header = f"Found {len(filtered)}{cuisine_label} restaurant"
        if len(filtered) != 1:
            header += "s"
        header += f" near {location}:\n"

        formatted: list[str] = []
        if weather_note:
            formatted.append(weather_note)
        formatted.append(header)

        for i, r in enumerate(filtered, 1):
            walk = walking_minutes(user_lat, user_lng, r.lat, r.lng)  # type: ignore[arg-type]
            formatted.append(_format_result(i, r, walk))

        if recency_notes:
            formatted.append("")
            for note in recency_notes:
                formatted.append(f"({note})")

        return "\n\n".join(formatted)
