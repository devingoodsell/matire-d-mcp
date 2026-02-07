"""Google Places API (New) client with cost-optimized field masks."""

import logging

import httpx

from src.clients.cuisine_mapper import map_cuisine
from src.models.restaurant import Restaurant

logger = logging.getLogger(__name__)

BASE_URL = "https://places.googleapis.com/v1"

# Field masks — only request what we use to minimise cost
SEARCH_FIELD_MASK = ",".join([
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.location",
    "places.rating",
    "places.userRatingCount",
    "places.priceLevel",
    "places.types",
    "places.primaryType",
    "places.regularOpeningHours",
    "places.websiteUri",
    "places.nationalPhoneNumber",
])

DETAILS_FIELD_MASK = ",".join([
    "id",
    "displayName",
    "formattedAddress",
    "location",
    "rating",
    "userRatingCount",
    "priceLevel",
    "types",
    "primaryType",
    "regularOpeningHours",
    "websiteUri",
    "nationalPhoneNumber",
    "editorialSummary",
])

# Google Places price level enum → our 1-4 integer scale
_PRICE_MAP: dict[str, int] = {
    "PRICE_LEVEL_FREE": 1,
    "PRICE_LEVEL_INEXPENSIVE": 1,
    "PRICE_LEVEL_MODERATE": 2,
    "PRICE_LEVEL_EXPENSIVE": 3,
    "PRICE_LEVEL_VERY_EXPENSIVE": 4,
}

# Cost per API call in cents (with Basic field masks)
COST_SEARCH_TEXT_CENTS = 3.2
COST_PLACE_DETAILS_CENTS = 1.7


def parse_place(place: dict) -> Restaurant:
    """Parse a single Google Places API (New) place object into a Restaurant.

    Args:
        place: Raw place dict from the API response.

    Returns:
        A Restaurant model instance.
    """
    location = place.get("location", {})
    display_name = place.get("displayName", {})

    # Map price level
    price_str = place.get("priceLevel")
    price_level = _PRICE_MAP.get(price_str) if price_str else None

    # Map cuisine from primary type and types
    primary_type = place.get("primaryType")
    types = place.get("types", [])
    cuisine = map_cuisine(primary_type, types)

    # Parse opening hours to a simple dict
    hours_data = place.get("regularOpeningHours")
    hours = None
    if hours_data and "weekdayDescriptions" in hours_data:
        hours = {"weekday_text": hours_data["weekdayDescriptions"]}

    return Restaurant(
        id=place.get("id", ""),
        name=display_name.get("text", "Unknown"),
        address=place.get("formattedAddress", ""),
        lat=location.get("latitude", 0.0),
        lng=location.get("longitude", 0.0),
        cuisine=cuisine,
        price_level=price_level,
        rating=place.get("rating"),
        review_count=place.get("userRatingCount"),
        phone=place.get("nationalPhoneNumber"),
        website=place.get("websiteUri"),
        hours=hours,
    )


class GooglePlacesClient:
    """Async client for Google Places API (New) with cost tracking.

    Args:
        api_key: Google API key.
        db: Optional DatabaseManager for cost tracking and caching.
    """

    def __init__(self, api_key: str, db: object | None = None) -> None:
        self.api_key = api_key
        self.db = db

    async def _log_api_call(
        self, endpoint: str, cost_cents: float, status_code: int, cached: bool
    ) -> None:
        """Log an API call for cost tracking (if db is available)."""
        if self.db is not None:
            await self.db.log_api_call(  # type: ignore[union-attr]
                provider="google_places",
                endpoint=endpoint,
                cost_cents=cost_cents,
                status_code=status_code,
                cached=cached,
            )

    async def search_nearby(
        self,
        query: str,
        lat: float,
        lng: float,
        radius_meters: int = 1500,
        max_results: int = 10,
    ) -> list[Restaurant]:
        """Search for restaurants near a location using Text Search.

        Args:
            query: Search text, e.g. "Italian restaurant".
            lat: Center latitude.
            lng: Center longitude.
            radius_meters: Search radius (default ~15 min walk).
            max_results: Maximum results to return.

        Returns:
            List of Restaurant models parsed from API response.
        """
        headers = {
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": SEARCH_FIELD_MASK,
            "Content-Type": "application/json",
        }
        body: dict = {
            "textQuery": query,
            "locationBias": {
                "circle": {
                    "center": {"latitude": lat, "longitude": lng},
                    "radius": float(radius_meters),
                },
            },
            "maxResultCount": min(max_results, 20),
            "languageCode": "en",
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{BASE_URL}/places:searchText",
                headers=headers,
                json=body,
            )

        status = response.status_code
        await self._log_api_call("searchText", COST_SEARCH_TEXT_CENTS, status, False)

        if status != 200:
            logger.warning("Places search failed (HTTP %d): %s", status, response.text)
            return []

        data = response.json()
        places = data.get("places", [])
        return [parse_place(p) for p in places]

    async def get_place_details(self, place_id: str) -> Restaurant | None:
        """Get detailed info for a single place.

        Args:
            place_id: Google Places ID.

        Returns:
            Restaurant model or None if the request failed.
        """
        headers = {
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": DETAILS_FIELD_MASK,
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BASE_URL}/places/{place_id}",
                headers=headers,
            )

        status = response.status_code
        await self._log_api_call(
            "getPlaceDetails", COST_PLACE_DETAILS_CENTS, status, False
        )

        if status != 200:
            logger.warning(
                "Place details failed for %s (HTTP %d): %s",
                place_id, status, response.text,
            )
            return None

        return parse_place(response.json())
