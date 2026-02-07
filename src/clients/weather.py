"""OpenWeatherMap client for weather-aware dining recommendations."""

import logging
from datetime import UTC, datetime

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class WeatherInfo(BaseModel):
    """Weather conditions at a location."""

    temperature_f: float
    condition: str  # "clear", "clouds", "rain", "snow"
    description: str  # "light rain", "overcast clouds"
    outdoor_suitable: bool  # True if temp 55-95°F, no rain/snow, wind < 20
    wind_mph: float
    humidity: int


# Conditions that make outdoor dining unsuitable
_BAD_CONDITIONS = {"rain", "snow", "thunderstorm", "drizzle"}


def _is_outdoor_suitable(data: dict) -> bool:
    """Determine if weather is suitable for outdoor dining."""
    temp = data.get("main", {}).get("temp", 0)
    weather_list = data.get("weather", [{}])
    weather_entry = weather_list[0] if weather_list else {}
    condition = weather_entry.get("main", "").lower()
    wind = data.get("wind", {}).get("speed", 0)

    return (
        55 <= temp <= 95
        and condition not in _BAD_CONDITIONS
        and wind < 20
    )


def _parse_weather(data: dict) -> WeatherInfo:
    """Parse OpenWeatherMap API response into WeatherInfo."""
    weather_list = data.get("weather", [{}])
    weather_block = weather_list[0] if weather_list else {}
    return WeatherInfo(
        temperature_f=data.get("main", {}).get("temp", 0),
        condition=weather_block.get("main", "unknown").lower(),
        description=weather_block.get("description", ""),
        outdoor_suitable=_is_outdoor_suitable(data),
        wind_mph=data.get("wind", {}).get("speed", 0),
        humidity=data.get("main", {}).get("humidity", 0),
    )


class WeatherClient:
    """OpenWeatherMap client with in-memory caching.

    Args:
        api_key: OpenWeatherMap API key.
    """

    BASE_URL = "https://api.openweathermap.org/data/2.5"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self._cache: dict[str, tuple[WeatherInfo, datetime]] = {}

    def _cache_key(self, lat: float, lng: float, date: str | None) -> str:
        """Create a cache key from location + date."""
        return f"{lat:.2f},{lng:.2f},{date or 'now'}"

    def _get_cached(self, key: str) -> WeatherInfo | None:
        """Return cached result if < 1 hour old."""
        if key not in self._cache:
            return None
        info, cached_at = self._cache[key]
        age = (datetime.now(tz=UTC) - cached_at).total_seconds()
        if age > 3600:
            del self._cache[key]
            return None
        return info

    async def get_weather(
        self, lat: float, lng: float, date: str | None = None
    ) -> WeatherInfo:
        """Get weather for a location and optional date.

        Uses current weather for today/None, forecast for future dates (up to 5 days).
        Caches results for 1 hour.

        Args:
            lat: Latitude.
            lng: Longitude.
            date: Optional date string YYYY-MM-DD. None or today → current weather.

        Returns:
            WeatherInfo with conditions and outdoor_suitable flag.
        """
        cache_key = self._cache_key(lat, lng, date)
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        # Determine if we need current or forecast
        today_str = datetime.now(tz=UTC).strftime("%Y-%m-%d")
        use_forecast = date is not None and date != today_str

        if use_forecast:
            info = await self._fetch_forecast(lat, lng, date)
        else:
            info = await self._fetch_current(lat, lng)

        self._cache[cache_key] = (info, datetime.now(tz=UTC))
        return info

    async def _fetch_current(self, lat: float, lng: float) -> WeatherInfo:
        """Fetch current weather from OpenWeatherMap."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{self.BASE_URL}/weather",
                params={
                    "lat": lat,
                    "lon": lng,
                    "units": "imperial",
                    "appid": self.api_key,
                },
            )
            response.raise_for_status()
            return _parse_weather(response.json())

    async def _fetch_forecast(
        self, lat: float, lng: float, date: str
    ) -> WeatherInfo:
        """Fetch forecast weather for a future date.

        Uses the 5-day/3-hour forecast endpoint, picking the noon entry
        closest to the target date.
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{self.BASE_URL}/forecast",
                params={
                    "lat": lat,
                    "lon": lng,
                    "units": "imperial",
                    "appid": self.api_key,
                },
            )
            response.raise_for_status()

        data = response.json()
        entries = data.get("list", [])
        if not entries:
            return _parse_weather({})

        # Find entry closest to noon on the target date
        target = f"{date} 12:00:00"
        best = entries[0]
        best_diff = abs(
            datetime.strptime(best.get("dt_txt", ""), "%Y-%m-%d %H:%M:%S").timestamp()
            - datetime.strptime(target, "%Y-%m-%d %H:%M:%S").timestamp()
        )
        for entry in entries[1:]:
            dt_txt = entry.get("dt_txt", "")
            try:
                diff = abs(
                    datetime.strptime(dt_txt, "%Y-%m-%d %H:%M:%S").timestamp()
                    - datetime.strptime(target, "%Y-%m-%d %H:%M:%S").timestamp()
                )
                if diff < best_diff:
                    best = entry
                    best_diff = diff
            except ValueError:
                continue

        return _parse_weather(best)
