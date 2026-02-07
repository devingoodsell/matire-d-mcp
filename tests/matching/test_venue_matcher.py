"""Tests for venue_matcher: name normalisation, street extraction, Resy matching."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from src.matching.venue_matcher import (
    VenueMatcher,
    _extract_street_number,
    _normalise_name,
    _slugify,
    generate_opentable_deep_link,
    generate_resy_deep_link,
)
from tests.factories import make_restaurant

# ── _normalise_name ──────────────────────────────────────────────────────────


class TestNormaliseName:
    """_normalise_name: lowercase, strip whitespace and common words."""

    def test_lowercase_and_strip(self):
        assert _normalise_name("  Carbone  ") == "carbone"

    def test_removes_the(self):
        assert _normalise_name("The Smith") == "smith"

    def test_removes_restaurant(self):
        assert _normalise_name("Balthazar Restaurant") == "balthazar"

    def test_removes_nyc(self):
        assert _normalise_name("Le Bernardin NYC") == "le bernardin"

    def test_removes_ny(self):
        assert _normalise_name("Peter Luger NY") == "peter luger"

    def test_does_not_remove_multiword_entry_new_york(self):
        # "new york" is a single entry in _STRIP_WORDS but words are checked
        # individually, so "new" and "york" are NOT stripped.
        assert _normalise_name("Katz Deli New York") == "katz deli new york"

    def test_removes_possessive_apostrophe_s(self):
        assert _normalise_name("Joe's Pizza") == "joe pizza"

    def test_removes_possessive_curly_apostrophe(self):
        assert _normalise_name("Joe\u2019s Pizza") == "joe pizza"

    def test_removes_multiple_strip_words(self):
        assert _normalise_name("The Restaurant NYC") == ""

    def test_preserves_non_strip_words(self):
        assert _normalise_name("Grand Central Oyster Bar") == "grand central oyster bar"


# ── _extract_street_number ───────────────────────────────────────────────────


class TestExtractStreetNumber:
    """_extract_street_number: leading digits from address."""

    def test_extracts_leading_number(self):
        assert _extract_street_number("123 Main St") == "123"

    def test_returns_none_when_no_leading_number(self):
        assert _extract_street_number("Main St") is None

    def test_extracts_from_padded_address(self):
        assert _extract_street_number("  456 Broadway") == "456"

    def test_only_first_number_group(self):
        assert _extract_street_number("7 East 20th Street") == "7"


# ── _slugify ─────────────────────────────────────────────────────────────────


class TestSlugify:
    """_slugify: convert name to URL-safe slug."""

    def test_basic_name_to_slug(self):
        assert _slugify("Carbone") == "carbone"

    def test_special_characters_stripped(self):
        assert _slugify("Joe's Bar & Grill!") == "joes-bar-grill"

    def test_spaces_become_hyphens(self):
        assert _slugify("Le Bernardin") == "le-bernardin"


# ── generate_resy_deep_link ──────────────────────────────────────────────────


class TestGenerateResyDeepLink:
    """generate_resy_deep_link: correct Resy booking URL format."""

    def test_returns_correct_url_format(self):
        result = generate_resy_deep_link("carbone-new-york", "2026-02-14", 2)
        assert result == (
            "https://resy.com/cities/ny/carbone-new-york"
            "?date=2026-02-14&seats=2"
        )


# ── generate_opentable_deep_link ─────────────────────────────────────────────


class TestGenerateOpentableDeepLink:
    """generate_opentable_deep_link: correct OpenTable booking URL format."""

    def test_returns_correct_url_format(self):
        result = generate_opentable_deep_link(
            "carbone-new-york", "2026-02-14", "19:00", 4
        )
        assert result == (
            "https://www.opentable.com/r/carbone-new-york"
            "?date=2026-02-14&time=19:00&party_size=4"
        )


# ── VenueMatcher.find_resy_venue ─────────────────────────────────────────────


class TestFindResyVenueResyClientNone:
    """find_resy_venue returns None immediately when resy_client is None."""

    async def test_returns_none_when_resy_client_is_none(self, db):
        restaurant = make_restaurant()
        matcher = VenueMatcher(db, resy_client=None)
        result = await matcher.find_resy_venue(restaurant)

        assert result is None


class TestFindResyVenueCacheHit:
    """Cache scenarios: hit with resy_venue_id, hit without, miss."""

    async def test_cache_hit_with_resy_venue_id(self, db):
        """Cached restaurant already has resy_venue_id -- return immediately."""
        restaurant = make_restaurant(resy_venue_id="cached_123")
        await db.cache_restaurant(restaurant)

        mock_resy = AsyncMock()
        matcher = VenueMatcher(db, mock_resy)
        result = await matcher.find_resy_venue(restaurant)

        assert result == "cached_123"
        mock_resy.search_venue.assert_not_awaited()

    async def test_cache_hit_without_resy_venue_id_searches_resy(self, db):
        """Cached restaurant without resy_venue_id triggers a Resy search."""
        restaurant = make_restaurant(resy_venue_id=None)
        await db.cache_restaurant(restaurant)

        mock_resy = AsyncMock()
        mock_resy.search_venue.return_value = [
            {
                "id": "resy_456",
                "name": restaurant.name,
                "location": {"street_address": restaurant.address},
            },
        ]
        matcher = VenueMatcher(db, mock_resy)
        result = await matcher.find_resy_venue(restaurant)

        assert result == "resy_456"
        mock_resy.search_venue.assert_awaited_once()

    async def test_no_cache_searches_resy(self, db):
        """Restaurant not in cache at all -- search Resy."""
        restaurant = make_restaurant(id="uncached_id")

        mock_resy = AsyncMock()
        mock_resy.search_venue.return_value = [
            {
                "id": "resy_789",
                "name": restaurant.name,
                "location": {"street_address": "123 Test St"},
            },
        ]
        matcher = VenueMatcher(db, mock_resy)
        result = await matcher.find_resy_venue(restaurant)

        assert result == "resy_789"


class TestFindResyVenueSearchResults:
    """Search result matching: names, addresses, edge cases."""

    async def test_resy_returns_no_hits(self, db):
        restaurant = make_restaurant()
        mock_resy = AsyncMock()
        mock_resy.search_venue.return_value = []

        matcher = VenueMatcher(db, mock_resy)
        result = await matcher.find_resy_venue(restaurant)

        assert result is None

    async def test_name_match_returns_venue_id(self, db):
        restaurant = make_restaurant(name="Carbone")
        mock_resy = AsyncMock()
        mock_resy.search_venue.return_value = [
            {"id": "v1", "name": "Carbone", "location": {}},
        ]
        matcher = VenueMatcher(db, mock_resy)
        result = await matcher.find_resy_venue(restaurant)

        assert result == "v1"

    async def test_name_mismatch_returns_none(self, db):
        restaurant = make_restaurant(name="Carbone")
        mock_resy = AsyncMock()
        mock_resy.search_venue.return_value = [
            {"id": "v2", "name": "Totally Different", "location": {}},
        ]
        matcher = VenueMatcher(db, mock_resy)
        result = await matcher.find_resy_venue(restaurant)

        assert result is None

    async def test_street_number_mismatch_skips_hit(self, db):
        restaurant = make_restaurant(
            name="Carbone", address="181 Thompson St, New York"
        )
        mock_resy = AsyncMock()
        mock_resy.search_venue.return_value = [
            {
                "id": "v3",
                "name": "Carbone",
                "location": {"street_address": "999 Thompson St"},
            },
        ]
        matcher = VenueMatcher(db, mock_resy)
        result = await matcher.find_resy_venue(restaurant)

        assert result is None

    async def test_street_number_match_returns_venue_id(self, db):
        restaurant = make_restaurant(
            name="Carbone", address="181 Thompson St, New York"
        )
        mock_resy = AsyncMock()
        mock_resy.search_venue.return_value = [
            {
                "id": "v4",
                "name": "Carbone",
                "location": {"street_address": "181 Thompson St"},
            },
        ]
        matcher = VenueMatcher(db, mock_resy)
        result = await matcher.find_resy_venue(restaurant)

        assert result == "v4"

    async def test_empty_venue_id_skips_hit(self, db):
        restaurant = make_restaurant(name="Carbone")
        mock_resy = AsyncMock()
        mock_resy.search_venue.return_value = [
            {"id": "", "name": "Carbone", "location": {}},
        ]
        matcher = VenueMatcher(db, mock_resy)
        result = await matcher.find_resy_venue(restaurant)

        assert result is None

    async def test_multiple_hits_first_mismatches_second_matches(self, db):
        restaurant = make_restaurant(name="Carbone")
        mock_resy = AsyncMock()
        mock_resy.search_venue.return_value = [
            {"id": "wrong", "name": "Other Place", "location": {}},
            {"id": "right", "name": "Carbone", "location": {}},
        ]
        matcher = VenueMatcher(db, mock_resy)
        result = await matcher.find_resy_venue(restaurant)

        assert result == "right"

    async def test_normalised_name_substring_source_in_hit(self, db):
        """Source normalised name is a substring of hit normalised name."""
        restaurant = make_restaurant(name="Balthazar")
        mock_resy = AsyncMock()
        mock_resy.search_venue.return_value = [
            {"id": "v5", "name": "Balthazar Restaurant NYC", "location": {}},
        ]
        matcher = VenueMatcher(db, mock_resy)
        result = await matcher.find_resy_venue(restaurant)

        assert result == "v5"

    async def test_normalised_name_substring_hit_in_source(self, db):
        """Hit normalised name is a substring of source normalised name."""
        restaurant = make_restaurant(name="The Balthazar Restaurant NYC")
        mock_resy = AsyncMock()
        mock_resy.search_venue.return_value = [
            {"id": "v6", "name": "Balthazar", "location": {}},
        ]
        matcher = VenueMatcher(db, mock_resy)
        result = await matcher.find_resy_venue(restaurant)

        assert result == "v6"


class TestFindResyVenueCacheUpdate:
    """Verify the cache is updated after a successful match."""

    async def test_match_updates_cache(self, db):
        restaurant = make_restaurant(name="Carbone", resy_venue_id=None)
        await db.cache_restaurant(restaurant)

        mock_resy = AsyncMock()
        mock_resy.search_venue.return_value = [
            {"id": "matched_id", "name": "Carbone", "location": {}},
        ]
        matcher = VenueMatcher(db, mock_resy)
        result = await matcher.find_resy_venue(restaurant)

        assert result == "matched_id"

        # Verify the database was updated
        cached = await db.get_cached_restaurant(restaurant.id)
        assert cached.resy_venue_id == "matched_id"


class TestFindResyVenueAddressEdgeCases:
    """Address-related edge cases in matching."""

    async def test_no_source_street_number_skips_address_check(self, db):
        """When source address has no leading number, address check is skipped."""
        restaurant = make_restaurant(
            name="Carbone", address="Thompson St, New York"
        )
        mock_resy = AsyncMock()
        mock_resy.search_venue.return_value = [
            {
                "id": "v7",
                "name": "Carbone",
                "location": {"street_address": "181 Thompson St"},
            },
        ]
        matcher = VenueMatcher(db, mock_resy)
        result = await matcher.find_resy_venue(restaurant)

        assert result == "v7"

    async def test_no_hit_address_skips_address_check(self, db):
        """When hit has no street_address, address check is skipped."""
        restaurant = make_restaurant(
            name="Carbone", address="181 Thompson St, New York"
        )
        mock_resy = AsyncMock()
        mock_resy.search_venue.return_value = [
            {"id": "v8", "name": "Carbone", "location": {}},
        ]
        matcher = VenueMatcher(db, mock_resy)
        result = await matcher.find_resy_venue(restaurant)

        assert result == "v8"

    async def test_hit_address_no_leading_number_passes(self, db):
        """Hit address without a leading number passes the street check."""
        restaurant = make_restaurant(
            name="Carbone", address="181 Thompson St, New York"
        )
        mock_resy = AsyncMock()
        mock_resy.search_venue.return_value = [
            {
                "id": "v9",
                "name": "Carbone",
                "location": {"street_address": "Thompson St"},
            },
        ]
        matcher = VenueMatcher(db, mock_resy)
        result = await matcher.find_resy_venue(restaurant)

        assert result == "v9"

    async def test_missing_location_key_in_hit(self, db):
        """Hit with no 'location' key at all -- treated as empty address."""
        restaurant = make_restaurant(name="Carbone", address="181 Thompson St")
        mock_resy = AsyncMock()
        mock_resy.search_venue.return_value = [
            {"id": "v10", "name": "Carbone"},
        ]
        matcher = VenueMatcher(db, mock_resy)
        result = await matcher.find_resy_venue(restaurant)

        assert result == "v10"

    async def test_missing_name_key_in_hit_matches_via_empty_substring(self, db):
        """Hit with no 'name' key normalises to empty string.

        An empty string is a substring of any string, so the hit passes the
        name check and the venue_id is returned.
        """
        restaurant = make_restaurant(name="Carbone")
        mock_resy = AsyncMock()
        mock_resy.search_venue.return_value = [
            {"id": "v11", "location": {}},
        ]
        matcher = VenueMatcher(db, mock_resy)
        result = await matcher.find_resy_venue(restaurant)

        assert result == "v11"


# ── VenueMatcher.find_opentable_slug ─────────────────────────────────────────


def _make_mock_http_client(side_effect=None, return_value=None):
    """Build a mock httpx.AsyncClient suitable for use as an async context manager."""
    mock_client = AsyncMock()
    if side_effect is not None:
        mock_client.head = AsyncMock(side_effect=side_effect)
    elif return_value is not None:
        mock_client.head = AsyncMock(return_value=return_value)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


def _mock_response(status_code: int) -> MagicMock:
    """Build a mock HTTP response with the given status code."""
    resp = MagicMock()
    resp.status_code = status_code
    return resp


class TestFindOpentableSlugCacheHit:
    """Cache scenarios for find_opentable_slug."""

    async def test_cache_hit_with_opentable_id(self, db):
        """Cached restaurant with opentable_id returns it immediately."""
        restaurant = make_restaurant(opentable_id="carbone-new-york")
        await db.cache_restaurant(restaurant)

        matcher = VenueMatcher(db)
        result = await matcher.find_opentable_slug(restaurant)

        assert result == "carbone-new-york"

    async def test_cache_hit_without_opentable_id_tries_head(self, db):
        """Cached restaurant without opentable_id falls through to HEAD requests."""
        restaurant = make_restaurant(name="Carbone", opentable_id=None)
        await db.cache_restaurant(restaurant)

        mock_resp_200 = _mock_response(200)
        mock_client = _make_mock_http_client(return_value=mock_resp_200)

        with patch(
            "src.matching.venue_matcher.httpx.AsyncClient",
            return_value=mock_client,
        ):
            matcher = VenueMatcher(db)
            result = await matcher.find_opentable_slug(restaurant)

        assert result == "carbone-new-york"


class TestFindOpentableSlugHeadRequests:
    """HEAD request slug resolution scenarios."""

    async def test_first_slug_candidate_returns_200(self, db):
        """First candidate (name-new-york) returns 200 -- cached and returned."""
        restaurant = make_restaurant(name="Carbone")
        await db.cache_restaurant(restaurant)

        mock_resp_200 = _mock_response(200)
        mock_client = _make_mock_http_client(return_value=mock_resp_200)

        with patch(
            "src.matching.venue_matcher.httpx.AsyncClient",
            return_value=mock_client,
        ):
            matcher = VenueMatcher(db)
            result = await matcher.find_opentable_slug(restaurant)

        assert result == "carbone-new-york"
        mock_client.head.assert_awaited_once_with(
            "https://www.opentable.com/r/carbone-new-york"
        )

        # Verify cache was updated
        cached = await db.get_cached_restaurant(restaurant.id)
        assert cached.opentable_id == "carbone-new-york"

    async def test_first_slug_404_second_returns_200(self, db):
        """First slug returns non-200, second slug returns 200."""
        restaurant = make_restaurant(name="Carbone")

        mock_resp_404 = _mock_response(404)
        mock_resp_200 = _mock_response(200)
        mock_client = _make_mock_http_client(
            side_effect=[mock_resp_404, mock_resp_200]
        )

        with patch(
            "src.matching.venue_matcher.httpx.AsyncClient",
            return_value=mock_client,
        ):
            matcher = VenueMatcher(db)
            result = await matcher.find_opentable_slug(restaurant)

        assert result == "carbone"
        assert mock_client.head.await_count == 2

    async def test_both_candidates_non_200_returns_none(self, db):
        """Both slug candidates return non-200 -- returns None."""
        restaurant = make_restaurant(name="Carbone")

        mock_resp_404 = _mock_response(404)
        mock_client = _make_mock_http_client(return_value=mock_resp_404)

        with patch(
            "src.matching.venue_matcher.httpx.AsyncClient",
            return_value=mock_client,
        ):
            matcher = VenueMatcher(db)
            result = await matcher.find_opentable_slug(restaurant)

        assert result is None
        assert mock_client.head.await_count == 2

    async def test_http_error_continues_to_next_candidate(self, db):
        """httpx.HTTPError on first candidate continues to second."""
        restaurant = make_restaurant(name="Carbone")

        mock_resp_200 = _mock_response(200)
        mock_client = _make_mock_http_client(
            side_effect=[httpx.HTTPError("connection failed"), mock_resp_200]
        )

        with patch(
            "src.matching.venue_matcher.httpx.AsyncClient",
            return_value=mock_client,
        ):
            matcher = VenueMatcher(db)
            result = await matcher.find_opentable_slug(restaurant)

        assert result == "carbone"
        assert mock_client.head.await_count == 2

    async def test_no_cache_tries_head_requests(self, db):
        """Restaurant not in cache at all -- tries HEAD requests."""
        restaurant = make_restaurant(id="uncached_ot", name="Le Bernardin")

        mock_resp_200 = _mock_response(200)
        mock_client = _make_mock_http_client(return_value=mock_resp_200)

        with patch(
            "src.matching.venue_matcher.httpx.AsyncClient",
            return_value=mock_client,
        ):
            matcher = VenueMatcher(db)
            result = await matcher.find_opentable_slug(restaurant)

        assert result == "le-bernardin-new-york"
        mock_client.head.assert_awaited_once_with(
            "https://www.opentable.com/r/le-bernardin-new-york"
        )
