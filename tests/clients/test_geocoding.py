from unittest.mock import AsyncMock, MagicMock, patch

from src.clients.geocoding import GEOCODING_URL, geocode_address


def _make_response(data: dict) -> MagicMock:
    """Build a mock httpx.Response whose .json() returns *data*."""
    response = MagicMock()
    response.json.return_value = data
    return response


class TestGeocodeAddressSuccess:
    """Happy-path: the API returns a valid location."""

    async def test_returns_lat_lng_tuple(self):
        api_data = {
            "status": "OK",
            "results": [
                {
                    "geometry": {
                        "location": {"lat": 40.7128, "lng": -74.0060},
                    },
                },
            ],
        }
        mock_client = AsyncMock()
        mock_client.get.return_value = _make_response(api_data)

        with patch("src.clients.geocoding.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client,
            )
            mock_cls.return_value.__aexit__ = AsyncMock(
                return_value=False,
            )

            result = await geocode_address(
                "123 Main St, New York, NY", "fake-key"
            )

        assert result == (40.7128, -74.0060)
        mock_client.get.assert_awaited_once_with(
            GEOCODING_URL,
            params={
                "address": "123 Main St, New York, NY",
                "key": "fake-key",
            },
        )


class TestGeocodeAddressFailedStatus:
    """The API returns a non-OK status."""

    async def test_non_ok_status_returns_none(self):
        api_data = {"status": "ZERO_RESULTS", "results": []}
        mock_client = AsyncMock()
        mock_client.get.return_value = _make_response(api_data)

        with patch("src.clients.geocoding.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client,
            )
            mock_cls.return_value.__aexit__ = AsyncMock(
                return_value=False,
            )

            result = await geocode_address("nowhere", "fake-key")

        assert result is None

    async def test_request_denied_returns_none(self):
        api_data = {"status": "REQUEST_DENIED"}
        mock_client = AsyncMock()
        mock_client.get.return_value = _make_response(api_data)

        with patch("src.clients.geocoding.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client,
            )
            mock_cls.return_value.__aexit__ = AsyncMock(
                return_value=False,
            )

            result = await geocode_address("bad request", "invalid-key")

        assert result is None


class TestGeocodeAddressMissingResults:
    """The API returns OK status but the results list is empty."""

    async def test_ok_status_empty_results_returns_none(self):
        api_data = {"status": "OK", "results": []}
        mock_client = AsyncMock()
        mock_client.get.return_value = _make_response(api_data)

        with patch("src.clients.geocoding.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client,
            )
            mock_cls.return_value.__aexit__ = AsyncMock(
                return_value=False,
            )

            result = await geocode_address("empty place", "fake-key")

        assert result is None

    async def test_ok_status_no_results_key_returns_none(self):
        api_data = {"status": "OK"}
        mock_client = AsyncMock()
        mock_client.get.return_value = _make_response(api_data)

        with patch("src.clients.geocoding.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client,
            )
            mock_cls.return_value.__aexit__ = AsyncMock(
                return_value=False,
            )

            result = await geocode_address("missing key", "fake-key")

        assert result is None


class TestGeocodeAddressLogging:
    """Verify the warning log on failure."""

    async def test_logs_warning_on_failure(self, caplog):
        api_data = {"status": "OVER_QUERY_LIMIT", "results": []}
        mock_client = AsyncMock()
        mock_client.get.return_value = _make_response(api_data)

        with patch("src.clients.geocoding.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client,
            )
            mock_cls.return_value.__aexit__ = AsyncMock(
                return_value=False,
            )

            with caplog.at_level("WARNING", logger="src.clients.geocoding"):
                result = await geocode_address("test addr", "fake-key")

        assert result is None
        assert "Geocoding failed for 'test addr'" in caplog.text
        assert "OVER_QUERY_LIMIT" in caplog.text
