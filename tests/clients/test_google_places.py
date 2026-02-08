"""Tests for the Google Places API client."""

from unittest.mock import AsyncMock, MagicMock, patch

from src.clients.cache import InMemoryCache
from src.clients.google_places import (
    COST_PLACE_DETAILS_CENTS,
    COST_SEARCH_TEXT_CENTS,
    DETAILS_FIELD_MASK,
    SEARCH_FIELD_MASK,
    GooglePlacesClient,
    parse_place,
)
from src.models.restaurant import Restaurant

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _full_place() -> dict:
    """Return a fully-populated place dict as the Google API would return."""
    return {
        "id": "ChIJabc123",
        "displayName": {"text": "Joe's Pizza"},
        "formattedAddress": "123 Broadway, New York, NY 10001",
        "location": {"latitude": 40.7128, "longitude": -74.0060},
        "rating": 4.5,
        "userRatingCount": 320,
        "priceLevel": "PRICE_LEVEL_MODERATE",
        "types": ["pizza_restaurant", "restaurant"],
        "primaryType": "pizza_restaurant",
        "regularOpeningHours": {
            "weekdayDescriptions": [
                "Monday: 11:00 AM - 10:00 PM",
                "Tuesday: 11:00 AM - 10:00 PM",
            ],
        },
        "websiteUri": "https://joespizza.example.com",
        "nationalPhoneNumber": "(212) 555-1234",
    }


def _mock_httpx_client(*, response: MagicMock) -> MagicMock:
    """Build a mock httpx.AsyncClient context manager wired to *response*."""
    mock_client = AsyncMock()
    mock_client.post.return_value = response
    mock_client.get.return_value = response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


def _make_response(*, status_code: int = 200, json_data: dict | None = None,
                   text: str = "") -> MagicMock:
    """Build a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    return resp


# ===================================================================
# parse_place tests
# ===================================================================

class TestParsePlaceFullPlace:
    """Full place dict with all fields produces a correct Restaurant."""

    async def test_all_fields_mapped(self):
        place = _full_place()
        result = parse_place(place)

        assert isinstance(result, Restaurant)
        assert result.id == "ChIJabc123"
        assert result.name == "Joe's Pizza"
        assert result.address == "123 Broadway, New York, NY 10001"
        assert result.lat == 40.7128
        assert result.lng == -74.0060
        assert result.rating == 4.5
        assert result.review_count == 320
        assert result.price_level == 2
        assert "pizza" in result.cuisine
        assert result.website == "https://joespizza.example.com"
        assert result.phone == "(212) 555-1234"
        assert result.hours == {
            "weekday_text": [
                "Monday: 11:00 AM - 10:00 PM",
                "Tuesday: 11:00 AM - 10:00 PM",
            ],
        }


class TestParsePlaceMissingLocation:
    """Missing location field defaults latitude/longitude to 0.0."""

    async def test_defaults_to_zero(self):
        place = _full_place()
        del place["location"]
        result = parse_place(place)

        assert result.lat == 0.0
        assert result.lng == 0.0


class TestParsePlaceMissingDisplayName:
    """Missing displayName defaults name to 'Unknown'."""

    async def test_defaults_to_unknown(self):
        place = _full_place()
        del place["displayName"]
        result = parse_place(place)

        assert result.name == "Unknown"


class TestParsePlaceMissingPriceLevel:
    """Missing priceLevel results in None."""

    async def test_price_level_is_none(self):
        place = _full_place()
        del place["priceLevel"]
        result = parse_place(place)

        assert result.price_level is None


class TestParsePlaceKnownPriceLevel:
    """Known priceLevel string maps to correct integer."""

    async def test_moderate_maps_to_2(self):
        place = _full_place()
        place["priceLevel"] = "PRICE_LEVEL_MODERATE"
        result = parse_place(place)

        assert result.price_level == 2

    async def test_expensive_maps_to_3(self):
        place = _full_place()
        place["priceLevel"] = "PRICE_LEVEL_EXPENSIVE"
        result = parse_place(place)

        assert result.price_level == 3


class TestParsePlaceOpeningHours:
    """Opening hours parsing."""

    async def test_weekday_descriptions_mapped(self):
        place = _full_place()
        result = parse_place(place)

        assert result.hours is not None
        assert "weekday_text" in result.hours
        assert len(result.hours["weekday_text"]) == 2

    async def test_no_opening_hours_returns_none(self):
        place = _full_place()
        del place["regularOpeningHours"]
        result = parse_place(place)

        assert result.hours is None

    async def test_opening_hours_without_weekday_descriptions(self):
        """regularOpeningHours present but missing weekdayDescriptions key."""
        place = _full_place()
        place["regularOpeningHours"] = {"openNow": True}
        result = parse_place(place)

        assert result.hours is None


class TestParsePlaceNoMatchingCuisine:
    """Types that don't match any known cuisine fall back to ['other']."""

    async def test_unknown_types_return_other(self):
        place = _full_place()
        place["primaryType"] = "gas_station"
        place["types"] = ["gas_station", "establishment"]
        result = parse_place(place)

        assert result.cuisine == ["other"]


# ===================================================================
# GooglePlacesClient.search_nearby tests
# ===================================================================

class TestSearchNearbySuccess:
    """Successful search returns parsed restaurants."""

    async def test_returns_parsed_restaurants(self, db):
        client = GooglePlacesClient(api_key="test-key", db=db)
        json_data = {"places": [_full_place()]}
        response = _make_response(json_data=json_data)
        mock_client = _mock_httpx_client(response=response)

        with patch("src.clients.google_places.httpx.AsyncClient",
                   return_value=mock_client):
            results = await client.search_nearby(
                "pizza", lat=40.7128, lng=-74.0060,
            )

        assert len(results) == 1
        assert isinstance(results[0], Restaurant)
        assert results[0].name == "Joe's Pizza"


class TestSearchNearbyEmptyResults:
    """Response with no 'places' key returns empty list."""

    async def test_no_places_key(self, db):
        client = GooglePlacesClient(api_key="test-key", db=db)
        response = _make_response(json_data={})
        mock_client = _mock_httpx_client(response=response)

        with patch("src.clients.google_places.httpx.AsyncClient",
                   return_value=mock_client):
            results = await client.search_nearby(
                "pizza", lat=40.7128, lng=-74.0060,
            )

        assert results == []


class TestSearchNearbyNon200:
    """Non-200 status code returns empty list."""

    async def test_500_returns_empty(self, db):
        client = GooglePlacesClient(api_key="test-key", db=db)
        response = _make_response(status_code=500, text="Internal Server Error")
        mock_client = _mock_httpx_client(response=response)

        with patch("src.clients.google_places.httpx.AsyncClient",
                   return_value=mock_client):
            results = await client.search_nearby(
                "pizza", lat=40.7128, lng=-74.0060,
            )

        assert results == []

    async def test_403_returns_empty(self, db):
        client = GooglePlacesClient(api_key="test-key", db=db)
        response = _make_response(status_code=403, text="Forbidden")
        mock_client = _mock_httpx_client(response=response)

        with patch("src.clients.google_places.httpx.AsyncClient",
                   return_value=mock_client):
            results = await client.search_nearby(
                "pizza", lat=40.7128, lng=-74.0060,
            )

        assert results == []


class TestSearchNearbyFieldMaskAndHeaders:
    """Verify the correct field mask and headers are sent."""

    async def test_headers_and_body(self, db):
        client = GooglePlacesClient(api_key="my-api-key", db=db)
        json_data = {"places": []}
        response = _make_response(json_data=json_data)
        mock_client = _mock_httpx_client(response=response)

        with patch("src.clients.google_places.httpx.AsyncClient",
                   return_value=mock_client):
            await client.search_nearby(
                "Italian restaurant",
                lat=40.75,
                lng=-73.99,
                radius_meters=2000,
                max_results=5,
            )

        mock_client.post.assert_awaited_once()
        call_args = mock_client.post.call_args

        # Check URL
        assert "places:searchText" in call_args.args[0]

        # Check headers
        headers = call_args.kwargs["headers"]
        assert headers["X-Goog-Api-Key"] == "my-api-key"
        assert headers["X-Goog-FieldMask"] == SEARCH_FIELD_MASK
        assert headers["Content-Type"] == "application/json"

        # Check body
        body = call_args.kwargs["json"]
        assert body["textQuery"] == "Italian restaurant"
        assert body["maxResultCount"] == 5
        assert body["languageCode"] == "en"
        assert body["locationBias"]["circle"]["center"]["latitude"] == 40.75
        assert body["locationBias"]["circle"]["center"]["longitude"] == -73.99
        assert body["locationBias"]["circle"]["radius"] == 2000.0


class TestSearchNearbyApiCostLogged:
    """API cost is logged to the database."""

    async def test_cost_logged_on_success(self, db):
        client = GooglePlacesClient(api_key="test-key", db=db)
        json_data = {"places": []}
        response = _make_response(json_data=json_data)
        mock_client = _mock_httpx_client(response=response)

        with patch("src.clients.google_places.httpx.AsyncClient",
                   return_value=mock_client):
            await client.search_nearby("pizza", lat=40.7, lng=-74.0)

        # Verify the db.log_api_call was invoked with the correct arguments
        rows = await db.fetch_all(
            "SELECT provider, endpoint, cost_cents, status_code, cached "
            "FROM api_calls ORDER BY id DESC LIMIT 1"
        )
        assert len(rows) == 1
        row = rows[0]
        assert row["provider"] == "google_places"
        assert row["endpoint"] == "searchText"
        assert float(row["cost_cents"]) == COST_SEARCH_TEXT_CENTS
        assert row["status_code"] == 200
        assert row["cached"] == 0  # False stored as 0

    async def test_cost_logged_on_failure(self, db):
        client = GooglePlacesClient(api_key="test-key", db=db)
        response = _make_response(status_code=500, text="error")
        mock_client = _mock_httpx_client(response=response)

        with patch("src.clients.google_places.httpx.AsyncClient",
                   return_value=mock_client):
            await client.search_nearby("pizza", lat=40.7, lng=-74.0)

        rows = await db.fetch_all(
            "SELECT status_code FROM api_calls ORDER BY id DESC LIMIT 1"
        )
        assert len(rows) == 1
        assert rows[0]["status_code"] == 500


# ===================================================================
# GooglePlacesClient.get_place_details tests
# ===================================================================

class TestGetPlaceDetailsSuccess:
    """Successful details request returns a Restaurant."""

    async def test_returns_restaurant(self, db):
        client = GooglePlacesClient(api_key="test-key", db=db)
        response = _make_response(json_data=_full_place())
        mock_client = _mock_httpx_client(response=response)

        with patch("src.clients.google_places.httpx.AsyncClient",
                   return_value=mock_client):
            result = await client.get_place_details("ChIJabc123")

        assert isinstance(result, Restaurant)
        assert result.id == "ChIJabc123"
        assert result.name == "Joe's Pizza"

        # Verify GET was called with the right URL and headers
        mock_client.get.assert_awaited_once()
        call_args = mock_client.get.call_args
        assert "places/ChIJabc123" in call_args.args[0]
        headers = call_args.kwargs["headers"]
        assert headers["X-Goog-Api-Key"] == "test-key"
        assert headers["X-Goog-FieldMask"] == DETAILS_FIELD_MASK


class TestGetPlaceDetailsNon200:
    """Non-200 status code returns None."""

    async def test_404_returns_none(self, db):
        client = GooglePlacesClient(api_key="test-key", db=db)
        response = _make_response(status_code=404, text="Not Found")
        mock_client = _mock_httpx_client(response=response)

        with patch("src.clients.google_places.httpx.AsyncClient",
                   return_value=mock_client):
            result = await client.get_place_details("ChIJbad")

        assert result is None


class TestGetPlaceDetailsApiCostLogged:
    """API cost for get_place_details is logged."""

    async def test_cost_logged(self, db):
        client = GooglePlacesClient(api_key="test-key", db=db)
        response = _make_response(json_data=_full_place())
        mock_client = _mock_httpx_client(response=response)

        with patch("src.clients.google_places.httpx.AsyncClient",
                   return_value=mock_client):
            await client.get_place_details("ChIJabc123")

        rows = await db.fetch_all(
            "SELECT provider, endpoint, cost_cents, status_code, cached "
            "FROM api_calls ORDER BY id DESC LIMIT 1"
        )
        assert len(rows) == 1
        row = rows[0]
        assert row["provider"] == "google_places"
        assert row["endpoint"] == "getPlaceDetails"
        assert float(row["cost_cents"]) == COST_PLACE_DETAILS_CENTS
        assert row["status_code"] == 200
        assert row["cached"] == 0


class TestLogApiCallWithNoDb:
    """When db is None, _log_api_call does nothing (no error)."""

    async def test_no_db_does_not_raise(self):
        client = GooglePlacesClient(api_key="test-key", db=None)
        response = _make_response(json_data={"places": []})
        mock_client = _mock_httpx_client(response=response)

        with patch("src.clients.google_places.httpx.AsyncClient",
                   return_value=mock_client):
            # search_nearby calls _log_api_call internally
            results = await client.search_nearby("pizza", lat=40.7, lng=-74.0)

        assert results == []

    async def test_no_db_details_does_not_raise(self):
        client = GooglePlacesClient(api_key="test-key", db=None)
        response = _make_response(json_data=_full_place())
        mock_client = _mock_httpx_client(response=response)

        with patch("src.clients.google_places.httpx.AsyncClient",
                   return_value=mock_client):
            result = await client.get_place_details("ChIJabc123")

        assert isinstance(result, Restaurant)


class TestSearchNearbyLogging:
    """Verify warning log on non-200 response."""

    async def test_logs_warning_on_failure(self, caplog):
        client = GooglePlacesClient(api_key="test-key", db=None)
        response = _make_response(status_code=429, text="Rate limit exceeded")
        mock_client = _mock_httpx_client(response=response)

        with patch("src.clients.google_places.httpx.AsyncClient",
                   return_value=mock_client):
            with caplog.at_level("WARNING",
                                 logger="src.clients.google_places"):
                results = await client.search_nearby(
                    "pizza", lat=40.7, lng=-74.0,
                )

        assert results == []
        assert "Places search failed" in caplog.text
        assert "429" in caplog.text


class TestGetPlaceDetailsLogging:
    """Verify warning log on non-200 details response."""

    async def test_logs_warning_on_failure(self, caplog):
        client = GooglePlacesClient(api_key="test-key", db=None)
        response = _make_response(status_code=403, text="Forbidden")
        mock_client = _mock_httpx_client(response=response)

        with patch("src.clients.google_places.httpx.AsyncClient",
                   return_value=mock_client):
            with caplog.at_level("WARNING",
                                 logger="src.clients.google_places"):
                result = await client.get_place_details("ChIJbad")

        assert result is None
        assert "Place details failed" in caplog.text
        assert "403" in caplog.text


class TestSearchNearbyMaxResultsCapped:
    """max_results is capped at 20 by the min() call."""

    async def test_max_results_capped_at_20(self, db):
        client = GooglePlacesClient(api_key="test-key", db=db)
        response = _make_response(json_data={"places": []})
        mock_client = _mock_httpx_client(response=response)

        with patch("src.clients.google_places.httpx.AsyncClient",
                   return_value=mock_client):
            await client.search_nearby(
                "pizza", lat=40.7, lng=-74.0, max_results=50,
            )

        body = mock_client.post.call_args.kwargs["json"]
        assert body["maxResultCount"] == 20


class TestSearchNearbyCacheHit:
    """Cache hit returns cached results without API call."""

    async def test_returns_cached_results(self, db):
        cache = InMemoryCache(max_size=10)
        client = GooglePlacesClient(api_key="test-key", db=db, cache=cache)

        # Populate cache by doing a real API call first
        json_data = {"places": [_full_place()]}
        response = _make_response(json_data=json_data)
        mock_client = _mock_httpx_client(response=response)

        with patch("src.clients.google_places.httpx.AsyncClient",
                   return_value=mock_client):
            first = await client.search_nearby("pizza", lat=40.7128, lng=-74.0060)

        assert len(first) == 1

        # Second call should use cache (no HTTP call)
        mock_client2 = _mock_httpx_client(
            response=_make_response(json_data={"places": []})
        )
        with patch("src.clients.google_places.httpx.AsyncClient",
                   return_value=mock_client2):
            second = await client.search_nearby("pizza", lat=40.7128, lng=-74.0060)

        assert len(second) == 1
        assert second[0].name == "Joe's Pizza"
        # HTTP client should NOT have been called for the cache hit
        mock_client2.post.assert_not_awaited()

    async def test_cache_miss_calls_api(self, db):
        cache = InMemoryCache(max_size=10)
        client = GooglePlacesClient(api_key="test-key", db=db, cache=cache)

        json_data = {"places": [_full_place()]}
        response = _make_response(json_data=json_data)
        mock_client = _mock_httpx_client(response=response)

        with patch("src.clients.google_places.httpx.AsyncClient",
                   return_value=mock_client):
            results = await client.search_nearby("sushi", lat=40.7, lng=-74.0)

        assert len(results) == 1
        mock_client.post.assert_awaited_once()

    async def test_cache_stores_results(self, db):
        cache = InMemoryCache(max_size=10)
        client = GooglePlacesClient(api_key="test-key", db=db, cache=cache)

        json_data = {"places": [_full_place()]}
        response = _make_response(json_data=json_data)
        mock_client = _mock_httpx_client(response=response)

        with patch("src.clients.google_places.httpx.AsyncClient",
                   return_value=mock_client):
            await client.search_nearby("pizza", lat=40.7128, lng=-74.0060)

        assert cache.size == 1
