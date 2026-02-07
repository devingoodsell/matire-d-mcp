import logging

import httpx

logger = logging.getLogger(__name__)

GEOCODING_URL = "https://maps.googleapis.com/maps/api/geocode/json"


async def geocode_address(
    address: str, api_key: str
) -> tuple[float, float] | None:
    """Geocode an address to (lat, lng) using Google Geocoding API.

    Returns:
        Tuple of (lat, lng) or None if geocoding failed.
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            GEOCODING_URL,
            params={"address": address, "key": api_key},
        )
        data = response.json()

    if data.get("status") != "OK" or not data.get("results"):
        logger.warning("Geocoding failed for '%s': %s", address, data.get("status"))
        return None

    location = data["results"][0]["geometry"]["location"]
    return (location["lat"], location["lng"])
