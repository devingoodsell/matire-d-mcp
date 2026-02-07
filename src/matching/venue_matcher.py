"""Match restaurants across platforms using name + address fuzzy matching."""

import logging
import re

import httpx

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


def _slugify(name: str) -> str:
    """Convert a restaurant name to a URL-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    return slug


def generate_resy_deep_link(
    venue_id: str, date: str, party_size: int
) -> str:
    """Generate a Resy booking deep link."""
    return f"https://resy.com/cities/ny/{venue_id}?date={date}&seats={party_size}"


def generate_opentable_deep_link(
    slug: str, date: str, time: str, party_size: int
) -> str:
    """Generate an OpenTable booking deep link."""
    return (
        f"https://www.opentable.com/r/{slug}"
        f"?date={date}&time={time}&party_size={party_size}"
    )


class VenueMatcher:
    """Match Google Place restaurants to Resy venue IDs and OpenTable slugs.

    Args:
        db: DatabaseManager for cache lookups.
        resy_client: Authenticated ResyClient for venue search.
    """

    def __init__(self, db: DatabaseManager, resy_client: ResyClient | None = None) -> None:
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
        if not self.resy_client:
            return None

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

    async def find_opentable_slug(self, restaurant: Restaurant) -> str | None:
        """Find the OpenTable slug for a restaurant.

        Strategy:
        1. Check cache for existing opentable_id
        2. Try common slug patterns with HEAD request
        3. Cache the result

        Returns:
            OpenTable slug string, or None if not on OpenTable.
        """
        # 1. Cache check
        cached = await self.db.get_cached_restaurant(restaurant.id)
        if cached and cached.opentable_id:
            return cached.opentable_id

        # 2. Try slug patterns
        base_slug = _slugify(restaurant.name)
        candidates = [
            f"{base_slug}-new-york",
            base_slug,
        ]

        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            for slug in candidates:
                url = f"https://www.opentable.com/r/{slug}"
                try:
                    response = await client.head(url)
                    if response.status_code == 200:
                        # 3. Cache result
                        await self.db.update_platform_ids(
                            restaurant.id, resy_id=None, opentable_id=slug
                        )
                        return slug
                except httpx.HTTPError:
                    continue

        return None
