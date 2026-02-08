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


# Phrases on OpenTable pages that indicate the restaurant is NOT bookable
_NOT_BOOKABLE_PHRASES = [
    "not on the opentable booking network",
    "not on the opentable reservation network",
    "not available on opentable",
]


def _is_bookable_page(html: str) -> bool:
    """Return True if the OpenTable page is for a bookable restaurant.

    OpenTable returns HTTP 200 for restaurants that have a listing page but
    are not actually bookable. These pages contain phrases like "not on the
    OpenTable booking network". We reject those pages so they are not
    incorrectly treated as valid OpenTable venues.
    """
    lower = html.lower()
    return not any(phrase in lower for phrase in _NOT_BOOKABLE_PHRASES)


def generate_resy_deep_link(
    restaurant_name: str, date: str, party_size: int
) -> str:
    """Generate a Resy booking deep link."""
    slug = _slugify(restaurant_name)
    return f"https://resy.com/cities/ny/{slug}?date={date}&seats={party_size}"


def generate_opentable_deep_link(
    slug: str, date: str, time: str, party_size: int
) -> str:
    """Generate an OpenTable booking deep link."""
    return (
        f"https://www.opentable.com/r/{slug}"
        f"?covers={party_size}&dateTime={date}T{time}"
    )


_NEGATIVE_CACHE_TTL_HOURS = 168  # 7 days


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
        4. Cache the result (positive or negative)

        Uses ``""`` (empty string) as a sentinel for "checked, not found"
        vs ``None`` for "never checked".

        Returns:
            Resy venue_id string, or None if not on Resy.
        """
        if not self.resy_client:
            return None

        # 1. Cache check: "" means "already checked, not on Resy"
        cached = await self.db.get_cached_restaurant(restaurant.id)
        if cached and cached.resy_venue_id is not None:
            if cached.resy_venue_id != "":
                return cached.resy_venue_id  # positive cache — always trust
            # Negative cache — check TTL
            age = await self.db.get_platform_cache_age_hours(restaurant.id)
            if age is not None and age < _NEGATIVE_CACHE_TTL_HOURS:
                return None  # still fresh, skip
            # else: expired, fall through to re-check

        # 2. Search Resy
        hits = await self.resy_client.search_venue(restaurant.name)
        if not hits:
            await self.db.update_resy_venue_id(restaurant.id, "")
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
                # 4. Cache positive result
                await self.db.update_resy_venue_id(restaurant.id, venue_id)
                return venue_id

        # Cache negative result
        await self.db.update_resy_venue_id(restaurant.id, "")
        return None

    async def find_opentable_slug(self, restaurant: Restaurant) -> str | None:
        """Find the OpenTable slug for a restaurant.

        Strategy:
        1. Check cache for existing opentable_id
        2. Try common slug patterns with GET request
        3. Verify the page is actually bookable (not just a stub page)
        4. Cache the result (positive or negative)

        Uses ``""`` (empty string) as a sentinel for "checked, not found"
        vs ``None`` for "never checked".

        Returns:
            OpenTable slug string, or None if not on OpenTable.
        """
        # 1. Cache check: "" means "already checked, not on OpenTable"
        cached = await self.db.get_cached_restaurant(restaurant.id)
        if cached and cached.opentable_id is not None:
            if cached.opentable_id != "":
                return cached.opentable_id  # positive cache — always trust
            # Negative cache — check TTL
            age = await self.db.get_platform_cache_age_hours(restaurant.id)
            if age is not None and age < _NEGATIVE_CACHE_TTL_HOURS:
                return None  # still fresh, skip
            # else: expired, fall through to re-check

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
                    response = await client.get(url)
                    if response.status_code == 200 and _is_bookable_page(
                        response.text
                    ):
                        # 3. Cache positive result
                        await self.db.update_opentable_id(restaurant.id, slug)
                        return slug
                except httpx.HTTPError:
                    continue

        # Cache negative result
        await self.db.update_opentable_id(restaurant.id, "")
        return None
