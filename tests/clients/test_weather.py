from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.clients.weather import (
    WeatherClient,
    WeatherInfo,
    _is_outdoor_suitable,
    _parse_weather,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_api_entry(
    temp: float = 72.0,
    condition: str = "Clear",
    description: str = "clear sky",
    wind_speed: float = 5.0,
    humidity: int = 45,
    dt_txt: str | None = None,
) -> dict:
    """Build a dict that mimics one item from OpenWeatherMap."""
    entry: dict = {
        "main": {"temp": temp, "humidity": humidity},
        "weather": [{"main": condition, "description": description}],
        "wind": {"speed": wind_speed},
    }
    if dt_txt is not None:
        entry["dt_txt"] = dt_txt
    return entry


def _make_response(data: dict, status_code: int = 200) -> MagicMock:
    """Build a mock httpx.Response."""
    response = MagicMock()
    response.json.return_value = data
    response.status_code = status_code
    response.raise_for_status = MagicMock()
    if status_code >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=response,
        )
    return response


def _patch_httpx(mock_client: AsyncMock):
    """Return a context-manager that patches httpx.AsyncClient for weather module."""
    patcher = patch("src.clients.weather.httpx.AsyncClient")
    mock_cls = patcher.start()
    mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
    return patcher, mock_cls


# ---------------------------------------------------------------------------
# _is_outdoor_suitable
# ---------------------------------------------------------------------------

class TestIsOutdoorSuitable:
    """Unit tests for the _is_outdoor_suitable helper."""

    def test_ideal_conditions(self):
        data = _make_api_entry(temp=72, condition="Clear", wind_speed=5)
        assert _is_outdoor_suitable(data) is True

    def test_boundary_low_temp_55_is_suitable(self):
        data = _make_api_entry(temp=55)
        assert _is_outdoor_suitable(data) is True

    def test_boundary_high_temp_95_is_suitable(self):
        data = _make_api_entry(temp=95)
        assert _is_outdoor_suitable(data) is True

    def test_too_cold_below_55(self):
        data = _make_api_entry(temp=54.9)
        assert _is_outdoor_suitable(data) is False

    def test_too_hot_above_95(self):
        data = _make_api_entry(temp=95.1)
        assert _is_outdoor_suitable(data) is False

    def test_rain_is_unsuitable(self):
        data = _make_api_entry(condition="Rain")
        assert _is_outdoor_suitable(data) is False

    def test_snow_is_unsuitable(self):
        data = _make_api_entry(condition="Snow")
        assert _is_outdoor_suitable(data) is False

    def test_thunderstorm_is_unsuitable(self):
        data = _make_api_entry(condition="Thunderstorm")
        assert _is_outdoor_suitable(data) is False

    def test_drizzle_is_unsuitable(self):
        data = _make_api_entry(condition="Drizzle")
        assert _is_outdoor_suitable(data) is False

    def test_wind_at_19_9_is_suitable(self):
        data = _make_api_entry(wind_speed=19.9)
        assert _is_outdoor_suitable(data) is True

    def test_wind_at_20_is_unsuitable(self):
        data = _make_api_entry(wind_speed=20)
        assert _is_outdoor_suitable(data) is False

    def test_wind_above_20_is_unsuitable(self):
        data = _make_api_entry(wind_speed=25)
        assert _is_outdoor_suitable(data) is False

    def test_clouds_are_suitable(self):
        data = _make_api_entry(condition="Clouds")
        assert _is_outdoor_suitable(data) is True

    def test_empty_data_defaults_not_suitable(self):
        """Empty dict: temp=0, condition='', wind=0 -> temp < 55 => False."""
        assert _is_outdoor_suitable({}) is False

    def test_missing_weather_list(self):
        data = {"main": {"temp": 72}, "wind": {"speed": 5}}
        assert _is_outdoor_suitable(data) is True

    def test_missing_wind_key(self):
        data = {"main": {"temp": 72}, "weather": [{"main": "Clear"}]}
        assert _is_outdoor_suitable(data) is True

    def test_missing_main_key(self):
        """No 'main' -> temp defaults to 0, too cold."""
        data = {"weather": [{"main": "Clear"}], "wind": {"speed": 5}}
        assert _is_outdoor_suitable(data) is False


# ---------------------------------------------------------------------------
# _parse_weather
# ---------------------------------------------------------------------------

class TestParseWeather:
    """Unit tests for _parse_weather."""

    def test_parses_full_response(self):
        data = _make_api_entry(
            temp=68.5, condition="Clouds", description="overcast clouds",
            wind_speed=12.3, humidity=60,
        )
        info = _parse_weather(data)
        assert isinstance(info, WeatherInfo)
        assert info.temperature_f == 68.5
        assert info.condition == "clouds"
        assert info.description == "overcast clouds"
        assert info.wind_mph == 12.3
        assert info.humidity == 60
        assert info.outdoor_suitable is True

    def test_condition_is_lowered(self):
        data = _make_api_entry(condition="RAIN")
        info = _parse_weather(data)
        assert info.condition == "rain"
        assert info.outdoor_suitable is False

    def test_empty_data_returns_defaults(self):
        info = _parse_weather({})
        assert info.temperature_f == 0
        assert info.condition == "unknown"
        assert info.description == ""
        assert info.wind_mph == 0
        assert info.humidity == 0
        assert info.outdoor_suitable is False

    def test_empty_weather_list(self):
        data = {"weather": [], "main": {"temp": 72, "humidity": 50}, "wind": {"speed": 3}}
        info = _parse_weather(data)
        assert info.condition == "unknown"
        assert info.description == ""

    def test_outdoor_suitable_flag_matches_helper(self):
        data = _make_api_entry(temp=50, condition="Clear", wind_speed=5)
        info = _parse_weather(data)
        assert info.outdoor_suitable is False  # too cold


# ---------------------------------------------------------------------------
# WeatherClient._cache_key
# ---------------------------------------------------------------------------

class TestCacheKey:
    """Tests for cache key generation."""

    def test_no_date_uses_now_label(self):
        client = WeatherClient(api_key="k")
        assert client._cache_key(40.71, -74.01, None) == "40.71,-74.01,now"

    def test_with_date(self):
        client = WeatherClient(api_key="k")
        assert client._cache_key(40.71, -74.01, "2026-02-10") == "40.71,-74.01,2026-02-10"

    def test_rounds_to_two_decimals(self):
        client = WeatherClient(api_key="k")
        key = client._cache_key(40.7189999, -74.0060001, None)
        assert key == "40.72,-74.01,now"


# ---------------------------------------------------------------------------
# WeatherClient._get_cached
# ---------------------------------------------------------------------------

class TestGetCached:
    """Tests for the 1-hour cache."""

    def test_cache_miss_returns_none(self):
        client = WeatherClient(api_key="k")
        assert client._get_cached("nonexistent") is None

    def test_cache_hit_within_one_hour(self):
        client = WeatherClient(api_key="k")
        info = _parse_weather(_make_api_entry())
        client._cache["key"] = (info, datetime.now(tz=UTC))
        assert client._get_cached("key") is info

    def test_cache_expired_after_one_hour(self):
        client = WeatherClient(api_key="k")
        info = _parse_weather(_make_api_entry())
        old_time = datetime.now(tz=UTC) - timedelta(seconds=3601)
        client._cache["key"] = (info, old_time)
        assert client._get_cached("key") is None
        assert "key" not in client._cache  # entry is deleted

    def test_cache_expired_at_exactly_3600_seconds(self):
        client = WeatherClient(api_key="k")
        info = _parse_weather(_make_api_entry())
        boundary_time = datetime.now(tz=UTC) - timedelta(seconds=3600, milliseconds=1)
        client._cache["key"] = (info, boundary_time)
        assert client._get_cached("key") is None

    def test_cache_valid_just_before_3600_seconds(self):
        client = WeatherClient(api_key="k")
        info = _parse_weather(_make_api_entry())
        boundary_time = datetime.now(tz=UTC) - timedelta(seconds=3599)
        client._cache["key"] = (info, boundary_time)
        assert client._get_cached("key") is info


# ---------------------------------------------------------------------------
# WeatherClient.get_weather – current weather
# ---------------------------------------------------------------------------

class TestGetWeatherCurrent:
    """get_weather with date=None or date=today fetches current weather."""

    async def test_current_weather_no_date(self):
        client = WeatherClient(api_key="test-key")
        api_data = _make_api_entry(temp=75, condition="Clear", description="clear sky")
        mock_http = AsyncMock()
        mock_http.get.return_value = _make_response(api_data)

        with patch("src.clients.weather.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            info = await client.get_weather(40.71, -74.01)

        assert info.temperature_f == 75
        assert info.condition == "clear"
        assert info.outdoor_suitable is True
        mock_http.get.assert_awaited_once()
        call_args = mock_http.get.call_args
        assert "/weather" in call_args[0][0]
        assert call_args[1]["params"]["lat"] == 40.71
        assert call_args[1]["params"]["lon"] == -74.01
        assert call_args[1]["params"]["units"] == "imperial"
        assert call_args[1]["params"]["appid"] == "test-key"

    async def test_current_weather_with_today_date(self):
        """Passing today's date string should still use current endpoint."""
        client = WeatherClient(api_key="test-key")
        today_str = datetime.now(tz=UTC).strftime("%Y-%m-%d")
        api_data = _make_api_entry(temp=80)
        mock_http = AsyncMock()
        mock_http.get.return_value = _make_response(api_data)

        with patch("src.clients.weather.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            info = await client.get_weather(40.71, -74.01, date=today_str)

        assert info.temperature_f == 80
        call_url = mock_http.get.call_args[0][0]
        assert "/weather" in call_url
        assert "/forecast" not in call_url


# ---------------------------------------------------------------------------
# WeatherClient.get_weather – forecast
# ---------------------------------------------------------------------------

class TestGetWeatherForecast:
    """get_weather with a future date fetches the forecast endpoint."""

    async def test_forecast_picks_noon_entry(self):
        client = WeatherClient(api_key="test-key")
        target_date = (datetime.now(tz=UTC) + timedelta(days=2)).strftime("%Y-%m-%d")

        entries = [
            _make_api_entry(temp=60, dt_txt=f"{target_date} 06:00:00"),
            _make_api_entry(temp=70, dt_txt=f"{target_date} 09:00:00"),
            _make_api_entry(temp=75, dt_txt=f"{target_date} 12:00:00"),  # noon
            _make_api_entry(temp=72, dt_txt=f"{target_date} 15:00:00"),
            _make_api_entry(temp=65, dt_txt=f"{target_date} 18:00:00"),
        ]
        forecast_data = {"list": entries}
        mock_http = AsyncMock()
        mock_http.get.return_value = _make_response(forecast_data)

        with patch("src.clients.weather.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            info = await client.get_weather(40.71, -74.01, date=target_date)

        assert info.temperature_f == 75
        call_url = mock_http.get.call_args[0][0]
        assert "/forecast" in call_url

    async def test_forecast_picks_closest_to_noon_when_no_exact_match(self):
        client = WeatherClient(api_key="test-key")
        target_date = (datetime.now(tz=UTC) + timedelta(days=1)).strftime("%Y-%m-%d")

        entries = [
            _make_api_entry(temp=60, dt_txt=f"{target_date} 09:00:00"),
            _make_api_entry(temp=68, dt_txt=f"{target_date} 15:00:00"),  # 3 hours away
        ]
        forecast_data = {"list": entries}
        mock_http = AsyncMock()
        mock_http.get.return_value = _make_response(forecast_data)

        with patch("src.clients.weather.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            info = await client.get_weather(40.71, -74.01, date=target_date)

        # 09:00 is 3h from noon, 15:00 is also 3h from noon -- but 09:00 comes first
        # and ties keep the current best (entries[0] at 09:00), so temp=60
        assert info.temperature_f == 60

    async def test_forecast_empty_entries_returns_defaults(self):
        client = WeatherClient(api_key="test-key")
        future_date = (datetime.now(tz=UTC) + timedelta(days=3)).strftime("%Y-%m-%d")

        forecast_data = {"list": []}
        mock_http = AsyncMock()
        mock_http.get.return_value = _make_response(forecast_data)

        with patch("src.clients.weather.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            info = await client.get_weather(40.71, -74.01, date=future_date)

        assert info.temperature_f == 0
        assert info.condition == "unknown"

    async def test_forecast_missing_list_key(self):
        client = WeatherClient(api_key="test-key")
        future_date = (datetime.now(tz=UTC) + timedelta(days=3)).strftime("%Y-%m-%d")

        forecast_data = {}
        mock_http = AsyncMock()
        mock_http.get.return_value = _make_response(forecast_data)

        with patch("src.clients.weather.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            info = await client.get_weather(40.71, -74.01, date=future_date)

        assert info.temperature_f == 0
        assert info.condition == "unknown"

    async def test_forecast_skips_entries_with_bad_dt_txt(self):
        """Entries with unparseable dt_txt are skipped via ValueError handling."""
        client = WeatherClient(api_key="test-key")
        target_date = (datetime.now(tz=UTC) + timedelta(days=2)).strftime("%Y-%m-%d")

        entries = [
            _make_api_entry(temp=60, dt_txt=f"{target_date} 06:00:00"),
            _make_api_entry(temp=99, dt_txt="not-a-date"),  # bad format
            _make_api_entry(temp=75, dt_txt=f"{target_date} 12:00:00"),
        ]
        forecast_data = {"list": entries}
        mock_http = AsyncMock()
        mock_http.get.return_value = _make_response(forecast_data)

        with patch("src.clients.weather.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            info = await client.get_weather(40.71, -74.01, date=target_date)

        # Should pick the noon entry, skipping the bad one
        assert info.temperature_f == 75

    async def test_forecast_single_entry(self):
        """A single entry in the list should be returned."""
        client = WeatherClient(api_key="test-key")
        target_date = (datetime.now(tz=UTC) + timedelta(days=1)).strftime("%Y-%m-%d")

        entries = [_make_api_entry(temp=65, dt_txt=f"{target_date} 18:00:00")]
        forecast_data = {"list": entries}
        mock_http = AsyncMock()
        mock_http.get.return_value = _make_response(forecast_data)

        with patch("src.clients.weather.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            info = await client.get_weather(40.71, -74.01, date=target_date)

        assert info.temperature_f == 65


# ---------------------------------------------------------------------------
# WeatherClient.get_weather – caching behaviour
# ---------------------------------------------------------------------------

class TestGetWeatherCaching:
    """Verify that caching prevents duplicate API calls."""

    async def test_second_call_returns_cached_result(self):
        client = WeatherClient(api_key="test-key")
        api_data = _make_api_entry(temp=70)
        mock_http = AsyncMock()
        mock_http.get.return_value = _make_response(api_data)

        with patch("src.clients.weather.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            first = await client.get_weather(40.71, -74.01)
            second = await client.get_weather(40.71, -74.01)

        assert first is second
        # Only one HTTP call should have been made
        mock_http.get.assert_awaited_once()

    async def test_different_locations_are_separate_cache_entries(self):
        client = WeatherClient(api_key="test-key")
        data_a = _make_api_entry(temp=70)
        data_b = _make_api_entry(temp=80)
        mock_http = AsyncMock()
        mock_http.get.side_effect = [_make_response(data_a), _make_response(data_b)]

        with patch("src.clients.weather.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            info_a = await client.get_weather(40.71, -74.01)
            info_b = await client.get_weather(41.00, -73.50)

        assert info_a.temperature_f == 70
        assert info_b.temperature_f == 80
        assert mock_http.get.await_count == 2

    async def test_expired_cache_triggers_new_request(self):
        client = WeatherClient(api_key="test-key")
        data_old = _make_api_entry(temp=60)
        data_new = _make_api_entry(temp=85)
        mock_http = AsyncMock()
        mock_http.get.side_effect = [_make_response(data_old), _make_response(data_new)]

        with patch("src.clients.weather.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            first = await client.get_weather(40.71, -74.01)
            assert first.temperature_f == 60

            # Manually age the cache entry beyond 1 hour
            cache_key = client._cache_key(40.71, -74.01, None)
            info, _ = client._cache[cache_key]
            client._cache[cache_key] = (
                info,
                datetime.now(tz=UTC) - timedelta(seconds=3601),
            )

            second = await client.get_weather(40.71, -74.01)
            assert second.temperature_f == 85

        assert mock_http.get.await_count == 2

    async def test_cache_with_date_and_without_date_are_separate(self):
        client = WeatherClient(api_key="test-key")
        future_date = (datetime.now(tz=UTC) + timedelta(days=2)).strftime("%Y-%m-%d")

        current_data = _make_api_entry(temp=70)
        forecast_entries = [_make_api_entry(temp=65, dt_txt=f"{future_date} 12:00:00")]
        forecast_data = {"list": forecast_entries}

        mock_http = AsyncMock()
        mock_http.get.side_effect = [
            _make_response(current_data),
            _make_response(forecast_data),
        ]

        with patch("src.clients.weather.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            current_info = await client.get_weather(40.71, -74.01)
            forecast_info = await client.get_weather(40.71, -74.01, date=future_date)

        assert current_info.temperature_f == 70
        assert forecast_info.temperature_f == 65
        assert mock_http.get.await_count == 2


# ---------------------------------------------------------------------------
# WeatherClient.get_weather – HTTP error handling
# ---------------------------------------------------------------------------

class TestGetWeatherHttpErrors:
    """Verify that HTTP errors propagate correctly."""

    async def test_current_weather_http_error_raises(self):
        client = WeatherClient(api_key="bad-key")
        mock_http = AsyncMock()
        mock_http.get.return_value = _make_response({}, status_code=401)

        with patch("src.clients.weather.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(httpx.HTTPStatusError):
                await client.get_weather(40.71, -74.01)

    async def test_forecast_http_error_raises(self):
        client = WeatherClient(api_key="bad-key")
        future_date = (datetime.now(tz=UTC) + timedelta(days=1)).strftime("%Y-%m-%d")
        mock_http = AsyncMock()
        mock_http.get.return_value = _make_response({}, status_code=500)

        with patch("src.clients.weather.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(httpx.HTTPStatusError):
                await client.get_weather(40.71, -74.01, date=future_date)

    async def test_http_error_does_not_cache(self):
        """Failed requests must not poison the cache."""
        client = WeatherClient(api_key="key")
        mock_http = AsyncMock()
        mock_http.get.return_value = _make_response({}, status_code=503)

        with patch("src.clients.weather.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(httpx.HTTPStatusError):
                await client.get_weather(40.71, -74.01)

        assert len(client._cache) == 0


# ---------------------------------------------------------------------------
# WeatherInfo model
# ---------------------------------------------------------------------------

class TestWeatherInfoModel:
    """Verify WeatherInfo Pydantic model basics."""

    def test_creates_valid_instance(self):
        info = WeatherInfo(
            temperature_f=72.0,
            condition="clear",
            description="clear sky",
            outdoor_suitable=True,
            wind_mph=5.0,
            humidity=45,
        )
        assert info.temperature_f == 72.0
        assert info.outdoor_suitable is True

    def test_model_rejects_missing_fields(self):
        with pytest.raises(Exception):
            WeatherInfo(temperature_f=72.0)  # type: ignore[call-arg]
