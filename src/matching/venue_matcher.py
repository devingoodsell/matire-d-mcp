"""Match restaurants across platforms using name + address fuzzy matching."""

import logging
import re

from src.clients.resy import ResyClient
from src.models.restaurant import Restaurant
from src.storage.database import DatabaseManager

logger = logging.getLogger(__name__)

# Words to strip when normalising restaurant names
_STRIP_WORDS = {"the", "restaurant", "nyc", "ny", "new york"}


def _normalise_name(name: str) -> str:
    """Lowercase, strip common suffixes and non-alpha chars."""
    name = name.lower().strip()
    # Remove possessives
    name = name.replace("'s", "").replace("\u2019s", "")
    words = re.split(r"\s+", name)
    words = [w for w in words if w not in _STRIP_WORDS]
    return " ".join(words)


def _extract_street_number(address: str) -> str | None:
    """Extract the leading street number from an address."""
    match = re.match(r"(\d+)", address.strip())
    return match.group(1) if match else None


class VenueMatcher:
    """Match Google Place restaurants to Resy venue IDs.

    Args:
        db: DatabaseManager for cache lookups.
        resy_client: Authenticated ResyClient for venue search.
    """

    def __init__(self, db: DatabaseManager, resy_client: ResyClient) -> None:
        self.db = db
        self.resy_client = resy_client

    async def find_resy_venue(self, restaurant: Restaurant) -> str | None:
        """Find the Resy venue ID for a restaurant.

        Strategy:
        1. Check cache for existing resy_venue_id
        2. Search Resy by name + location
        3. Fuzzy-match name and address
        4. Cache the result

        Returns:
            Resy venue_id string, or None if not on Resy.
        """
        # 1. Cache check
        cached = await self.db.get_cached_restaurant(restaurant.id)
        if cached and cached.resy_venue_id:
            return cached.resy_venue_id

        # 2. Search Resy
        hits = await self.resy_client.search_venue(
            restaurant.name, restaurant.lat, restaurant.lng
        )
        if not hits:
            return None

        # 3. Fuzzy match
        norm_name = _normalise_name(restaurant.name)
        src_street = _extract_street_number(restaurant.address)

        for hit in hits:
            hit_name = _normalise_name(hit.get("name", ""))
            # Name must be a substring match in either direction
            if norm_name not in hit_name and hit_name not in norm_name:
                continue

            # If we have a street number, check it matches
            hit_address = hit.get("location", {}).get("street_address", "")
            if src_street and hit_address:
                hit_street = _extract_street_number(hit_address)
                if hit_street and hit_street != src_street:
                    continue

            venue_id = hit.get("id", "")
            if venue_id:
                # 4. Cache result
                await self.db.update_platform_ids(
                    restaurant.id, resy_id=venue_id, opentable_id=None
                )
                return venue_id

        return None
