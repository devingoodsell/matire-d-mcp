"""MCP tools for personalized recommendations and group dining search."""

import logging

from fastmcp import FastMCP

from src.clients.cache import InMemoryCache
from src.clients.distance import walking_minutes
from src.clients.geocoding import geocode_address
from src.clients.google_places import GooglePlacesClient
from src.models.restaurant import Restaurant
from src.server import get_db, resolve_credential

logger = logging.getLogger(__name__)

_recommendation_cache = InMemoryCache(max_size=100)

# Price level display symbols
_PRICE_SYMBOLS = {1: "$", 2: "$$", 3: "$$$", 4: "$$$$"}

# Occasion → attribute preferences
_OCCASION_FILTERS: dict[str, dict] = {
    "date_night": {"min_rating": 4.3, "min_price": 3, "noise": "quiet"},
    "casual": {"min_rating": 3.8, "max_price": 3, "noise": "moderate"},
    "group_dinner": {"min_rating": 4.0, "noise": "lively"},
    "special": {"min_rating": 4.5, "min_price": 4},
    "quick": {"max_price": 2, "min_rating": 3.5},
}


async def _score_restaurant(
    restaurant: Restaurant,
    user_lat: float,
    user_lng: float,
    occasion: str | None,
    favorite_cuisines: set[str],
    liked_cuisines: set[str],
    avoided_cuisines: set[str],
    recency_penalties: dict[str, float],
    review_map: dict[str, dict],
) -> tuple[float, str]:
    """Score a restaurant and return (score, reason).

    Returns:
        Tuple of (numeric score, human-readable reason string).
    """
    score = 0.0
    reasons: list[str] = []

    # Base: Google rating (0-5 → 0-50 points)
    if restaurant.rating:
        score += restaurant.rating * 10

    # Cuisine preference bonus
    restaurant_cuisines = {c.lower() for c in restaurant.cuisine} if restaurant.cuisine else set()
    if restaurant_cuisines & favorite_cuisines:
        score += 20
        reasons.append("Matches your favorite cuisines")
    elif restaurant_cuisines & liked_cuisines:
        score += 10
        reasons.append("A cuisine you enjoy")
    elif restaurant_cuisines & avoided_cuisines:
        score -= 100

    # Recency penalty
    max_penalty = 0.0
    for c in restaurant_cuisines:
        p = recency_penalties.get(c, 0.0)
        if p > max_penalty:
            max_penalty = p
    score -= max_penalty * 30

    # "Would return" bonus from past visits
    review_info = review_map.get(restaurant.id)
    if review_info:
        if review_info.get("would_return"):
            score += 25
            rating = review_info.get("overall_rating")
            if rating:
                reasons.append(f"You rated it {rating}/5 last time")
            else:
                reasons.append("You'd return based on your last visit")
        else:
            score -= 50
            reasons.append("You wouldn't return — skipping")

    # Occasion matching
    if occasion:
        occ = _OCCASION_FILTERS.get(occasion, {})
        min_price = occ.get("min_price")
        if min_price and restaurant.price_level and restaurant.price_level >= min_price:
            score += 10
        max_price = occ.get("max_price")
        if max_price and restaurant.price_level and restaurant.price_level <= max_price:
            score += 10

    # Distance penalty (closer is better)
    walk = walking_minutes(user_lat, user_lng, restaurant.lat, restaurant.lng)
    score -= walk * 0.5

    if not reasons:
        if restaurant.rating and restaurant.rating >= 4.5:
            reasons.append("Highly rated, you haven't tried it yet")
        elif restaurant_cuisines:
            reasons.append(f"{', '.join(restaurant.cuisine)} restaurant nearby")

    return score, "; ".join(reasons) if reasons else "Nearby option"


def register_recommendation_tools(mcp: FastMCP) -> None:  # noqa: C901
    """Register recommendation and group search tools on the MCP server."""

    @mcp.tool
    async def get_recommendations(
        occasion: str | None = None,
        party_size: int = 2,
        location: str = "home",
        group: str | None = None,
        exclude_recent_days: int = 14,
    ) -> str:
        """Get personalized restaurant recommendations based on your history,
        preferences, and current context (weather, recent visits).

        Args:
            occasion: The type of dining occasion. Options:
                      "date_night" - romantic, quieter spots
                      "casual" - relaxed, neighborhood places
                      "group_dinner" - accommodates larger parties
                      "special" - high-end, celebration-worthy
                      "quick" - fast, nearby options
                      Leave empty for general recommendations.
            party_size: Number of diners.
            location: "home", "work", or an address.
            group: Name of a saved group — their restrictions will be applied.
            exclude_recent_days: Don't recommend places visited in the last N days.

        Returns:
            Curated list of 3-5 restaurants with reasons for each recommendation.
        """
        db = get_db()
        google_key = await resolve_credential("google_api_key") or ""

        # Resolve location
        user_lat: float | None = None
        user_lng: float | None = None

        saved_loc = await db.get_location(location)
        if saved_loc:
            user_lat, user_lng = saved_loc.lat, saved_loc.lng
        else:
            coords = await geocode_address(location, google_key)
            if coords:
                user_lat, user_lng = coords
            else:
                return (
                    f"Could not resolve location '{location}'. "
                    "Use 'home', 'work', or a valid address."
                )

        # Load preferences
        prefs = await db.get_preferences()
        cuisine_prefs = await db.get_cuisine_preferences()
        walk_limit = prefs.max_walk_minutes if prefs else 15

        favorite_cuisines: set[str] = set()
        liked_cuisines: set[str] = set()
        avoided_cuisines: set[str] = set()
        for cp in cuisine_prefs:
            c = cp.cuisine.lower()
            if cp.category.value == "favorite":
                favorite_cuisines.add(c)
            elif cp.category.value == "like":
                liked_cuisines.add(c)
            elif cp.category.value == "avoid":
                avoided_cuisines.add(c)

        # Merge group dietary restrictions
        dietary_restrictions: set[str] = set()
        if group:
            group_restrictions = await db.get_group_dietary_restrictions(group)
            dietary_restrictions.update(group_restrictions)
        user_dietary = await db.get_dietary_restrictions()
        dietary_restrictions.update(user_dietary)

        # Recency data
        recency_penalties = await db.get_recency_penalties(days=exclude_recent_days)
        recent_visits = await db.get_recent_visits(days=exclude_recent_days)
        recently_visited_ids = {v.restaurant_id for v in recent_visits if v.restaurant_id}

        # Build review map for scoring
        review_map: dict[str, dict] = {}
        for v in recent_visits:
            if v.restaurant_id and v.id is not None:
                review = await db.get_visit_review(v.id)
                if review:
                    review_map[v.restaurant_id] = {
                        "would_return": review.would_return,
                        "overall_rating": review.overall_rating,
                    }

        # Get occasion filters
        occ_filters = _OCCASION_FILTERS.get(occasion or "", {})
        min_rating = occ_filters.get("min_rating", 4.0)

        # Search for restaurants
        search_query = "restaurant"
        if occasion == "date_night":
            search_query = "romantic restaurant"
        elif occasion == "special":
            search_query = "fine dining restaurant"
        elif occasion == "quick":
            search_query = "casual restaurant"

        # Weather check for outdoor recommendation
        weather_key = await resolve_credential("openweather_api_key")
        weather_note = ""
        if weather_key:
            try:
                from src.clients.weather import WeatherClient

                weather_client = WeatherClient(weather_key)
                weather = await weather_client.get_weather(user_lat, user_lng)
                if weather.outdoor_suitable:
                    temp = weather.temperature_f
                    weather_note = f"Great weather for outdoor dining ({temp:.0f}°F)!\n\n"
            except Exception:  # noqa: BLE001
                pass

        radius_m = int(walk_limit * 83 / 1.3)
        places_client = GooglePlacesClient(
            api_key=google_key, db=db, cache=_recommendation_cache
        )
        results = await places_client.search_nearby(
            query=search_query,
            lat=user_lat,
            lng=user_lng,
            radius_meters=radius_m,
            max_results=20,
        )

        # Cache
        for r in results:
            await db.cache_restaurant(r)

        # Filter and score
        scored: list[tuple[float, str, Restaurant]] = []
        for r in results:
            # Skip blacklisted
            if await db.is_blacklisted(r.id):
                continue

            # Skip recently visited restaurants (hard exclude)
            if r.id in recently_visited_ids:
                # Unless they got a "would return" review
                review_info = review_map.get(r.id)
                if not review_info or not review_info.get("would_return"):
                    continue

            # Rating filter
            if r.rating is not None and r.rating < min_rating:
                continue

            # Avoided cuisines
            if r.cuisine and avoided_cuisines:
                if any(c.lower() in avoided_cuisines for c in r.cuisine):
                    continue

            # Occasion-based price filter
            min_price = occ_filters.get("min_price")
            if min_price and r.price_level and r.price_level < min_price:
                continue
            max_price = occ_filters.get("max_price")
            if max_price and r.price_level and r.price_level > max_price:
                continue

            s, reason = await _score_restaurant(
                r, user_lat, user_lng, occasion,
                favorite_cuisines, liked_cuisines, avoided_cuisines,
                recency_penalties, review_map,
            )
            scored.append((s, reason, r))

        # Sort by score descending
        scored.sort(key=lambda x: -x[0])
        top = scored[:5]

        if not top:
            return "No recommendations found. Try adjusting your preferences or location."

        # Format
        occasion_label = f" for {occasion.replace('_', ' ')}" if occasion else ""
        lines: list[str] = []
        if weather_note:
            lines.append(weather_note)
        lines.append(f"My picks{occasion_label}:\n")

        for i, (_, reason, r) in enumerate(top, 1):
            price = _PRICE_SYMBOLS.get(r.price_level or 0, "?")
            rating_str = f"{r.rating:.1f}" if r.rating else "?"
            walk = walking_minutes(user_lat, user_lng, r.lat, r.lng)
            cuisine_str = ", ".join(r.cuisine) if r.cuisine else "Various"

            lines.append(
                f"{i}. {r.name} ({rating_str}\u2605, {price}) - ~{walk} min walk\n"
                f"   {cuisine_str}\n"
                f"   \u21b3 {reason}"
            )

        if dietary_restrictions:
            lines.append(
                f"\nDietary restrictions applied: {', '.join(sorted(dietary_restrictions))}"
            )

        return "\n\n".join(lines)

    @mcp.tool
    async def search_for_group(
        group_name: str,
        location: str = "work",
        date: str = "today",
        time: str = "18:00",
        cuisine: str | None = None,
    ) -> str:
        """Search for restaurants suitable for a saved group.
        Automatically merges all members' dietary restrictions and
        finds restaurants that work for everyone.

        Args:
            group_name: Name of the saved group (e.g., "work_team", "family").
            location: Where to search near.
            date: Date for the dinner.
            time: Preferred time.
            cuisine: Specific cuisine (optional).

        Returns:
            Restaurant recommendations with notes on dietary compatibility.
        """
        db = get_db()
        google_key = await resolve_credential("google_api_key") or ""

        # Load group
        grp = await db.get_group(group_name)
        if not grp:
            return f"Group '{group_name}' not found. Create it first with save_group."

        # Get all members with their details
        members: list[dict] = []
        all_restrictions: set[str] = set()
        has_no_alcohol = False

        for member_name in grp.member_names:
            person = await db.get_person(member_name)
            if person:
                members.append({
                    "name": person.name,
                    "restrictions": person.dietary_restrictions,
                    "no_alcohol": person.no_alcohol,
                })
                all_restrictions.update(person.dietary_restrictions)
                if person.no_alcohol:
                    has_no_alcohol = True

        # Add user's own restrictions
        user_dietary = await db.get_dietary_restrictions()
        all_restrictions.update(user_dietary)

        # Resolve party size (members + user)
        total_party = len(members) + 1

        # Resolve location
        user_lat: float | None = None
        user_lng: float | None = None
        saved_loc = await db.get_location(location)
        if saved_loc:
            user_lat, user_lng = saved_loc.lat, saved_loc.lng
        else:
            coords = await geocode_address(location, google_key)
            if coords:
                user_lat, user_lng = coords
            else:
                return f"Could not resolve location '{location}'."

        # Build search
        if cuisine:
            search_query = f"{cuisine} restaurant"
        else:
            search_query = "restaurant"

        prefs = await db.get_preferences()
        walk_limit = prefs.max_walk_minutes if prefs else 15
        radius_m = int(walk_limit * 83 / 1.3)

        places_client = GooglePlacesClient(
            api_key=google_key, db=db, cache=_recommendation_cache
        )
        results = await places_client.search_nearby(
            query=search_query,
            lat=user_lat,
            lng=user_lng,
            radius_meters=radius_m,
            max_results=20,
        )

        for r in results:
            await db.cache_restaurant(r)

        # Filter
        cuisine_prefs = await db.get_cuisine_preferences()
        avoided_cuisines: set[str] = set()
        for cp in cuisine_prefs:
            if cp.category.value == "avoid":
                avoided_cuisines.add(cp.cuisine.lower())

        filtered: list[Restaurant] = []
        for r in results:
            if await db.is_blacklisted(r.id):
                continue
            if r.rating is not None and r.rating < 4.0:
                continue
            if r.cuisine and avoided_cuisines:
                if any(c.lower() in avoided_cuisines for c in r.cuisine):
                    continue
            filtered.append(r)

        # Sort by rating
        filtered.sort(key=lambda r: -(r.rating or 0.0))
        filtered = filtered[:5]

        if not filtered:
            return f"No suitable restaurants found for group '{group_name}'."

        # Format
        member_list = ", ".join(m["name"] for m in members)
        lines = [
            f"Restaurants for {group_name} ({member_list} + you, party of {total_party}):\n"
        ]

        for i, r in enumerate(filtered, 1):
            price = _PRICE_SYMBOLS.get(r.price_level or 0, "?")
            rating_str = f"{r.rating:.1f}" if r.rating else "?"
            walk = walking_minutes(user_lat, user_lng, r.lat, r.lng)
            cuisine_str = ", ".join(r.cuisine) if r.cuisine else "Various"

            lines.append(
                f"{i}. {r.name} ({rating_str}\u2605, {price}) - ~{walk} min walk\n"
                f"   {cuisine_str} | {r.address}"
            )

        # Add dietary notes
        notes: list[str] = []
        if all_restrictions:
            notes.append(
                f"Dietary restrictions applied: {', '.join(sorted(all_restrictions))}"
            )
        if has_no_alcohol:
            no_alcohol_members = [m["name"] for m in members if m["no_alcohol"]]
            notes.append(
                f"{', '.join(no_alcohol_members)} doesn't drink — "
                "picked places with good non-alcoholic options"
            )
        if notes:
            lines.append("")
            lines.extend(notes)

        return "\n\n".join(lines)
