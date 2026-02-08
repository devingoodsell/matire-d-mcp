"""Resy API client for availability checking and reservation booking."""

import logging

import httpx

from src.models.enums import BookingPlatform
from src.models.restaurant import TimeSlot

logger = logging.getLogger(__name__)

# Application-level API key (same for all users, extracted from resy.com frontend)
DEFAULT_API_KEY = "VbWk7s3L4KiK5fzlO7JD3Q5EYolJI7n5"

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class ResyClient:
    """Async client for the Resy API.

    Args:
        api_key: Resy application-level API key.
        auth_token: User-specific JWT auth token.
    """

    BASE_URL = "https://api.resy.com"

    def __init__(self, api_key: str = DEFAULT_API_KEY, auth_token: str = "") -> None:
        self.api_key = api_key
        self.auth_token = auth_token

    def _headers(self) -> dict[str, str]:
        """Build request headers."""
        return {
            "Authorization": f'ResyAPI api_key="{self.api_key}"',
            "X-Resy-Auth-Token": self.auth_token,
            "X-Resy-Universal-Auth": self.auth_token,
            "User-Agent": _USER_AGENT,
            "Accept": "application/json",
            "Origin": "https://resy.com",
            "Referer": "https://resy.com/",
        }

    async def authenticate(self, email: str, password: str) -> dict:
        """Authenticate via Resy's password endpoint.

        Returns:
            Dict with auth_token, payment_methods, and api_key.

        Raises:
            httpx.HTTPStatusError: On non-2xx response.
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.BASE_URL}/3/auth/password",
                headers={
                    "Authorization": f'ResyAPI api_key="{self.api_key}"',
                    "User-Agent": _USER_AGENT,
                    "Accept": "application/json",
                    "Origin": "https://resy.com",
                },
                data={"email": email, "password": password},
            )
            response.raise_for_status()

        data = response.json()
        token = data.get("token", "")
        payment_methods = data.get("payment_method_id") or data.get(
            "payment_methods", []
        )
        return {
            "auth_token": token,
            "payment_methods": payment_methods,
            "api_key": self.api_key,
        }

    async def find_availability(
        self,
        venue_id: str,
        date: str,
        party_size: int,
    ) -> list[TimeSlot]:
        """Find available time slots at a venue.

        Args:
            venue_id: Resy venue ID.
            date: Date string YYYY-MM-DD.
            party_size: Number of diners.

        Returns:
            List of available TimeSlot objects.
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self.BASE_URL}/4/find",
                headers=self._headers(),
                params={
                    "venue_id": venue_id,
                    "day": date,
                    "party_size": party_size,
                    "lat": 0,
                    "long": 0,
                },
            )

        if response.status_code != 200:
            logger.warning(
                "Resy find_availability failed (HTTP %d): %s",
                response.status_code, response.text,
            )
            return []

        return self._parse_slots(response.json())

    def _parse_slots(self, data: dict) -> list[TimeSlot]:
        """Parse slot data from the /4/find response."""
        slots: list[TimeSlot] = []
        venues = data.get("results", {}).get("venues", [])
        if not venues:
            return slots

        for slot in venues[0].get("slots", []):
            config = slot.get("config", {})
            date_info = slot.get("date", {})
            time_str = date_info.get("start", "")
            # Extract just the time portion (HH:MM) from datetime string
            if " " in time_str:
                time_str = time_str.split(" ")[-1]
            # Normalise to HH:MM (strip seconds if present)
            time_parts = time_str.split(":")
            if len(time_parts) >= 2:
                time_str = f"{time_parts[0]}:{time_parts[1]}"

            slots.append(
                TimeSlot(
                    time=time_str,
                    type=config.get("type", ""),
                    platform=BookingPlatform.RESY,
                    config_id=config.get("token", ""),
                )
            )
        return slots

    async def get_booking_details(
        self,
        config_id: str,
        date: str,
        party_size: int,
    ) -> dict:
        """Get booking token for a specific time slot.

        Args:
            config_id: Config token from find_availability.
            date: Date string YYYY-MM-DD.
            party_size: Number of diners.

        Returns:
            Response dict containing book_token.
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self.BASE_URL}/3/details",
                headers=self._headers(),
                params={
                    "config_id": config_id,
                    "day": date,
                    "party_size": party_size,
                },
            )

        if response.status_code != 200:
            logger.warning(
                "Resy get_booking_details failed (HTTP %d): %s",
                response.status_code, response.text,
            )
            return {}

        return response.json()

    async def book(
        self,
        book_token: str,
        payment_method: dict | None = None,
    ) -> dict:
        """Complete a reservation.

        Args:
            book_token: Token from get_booking_details.
            payment_method: Optional struct_payment_method dict.

        Returns:
            Confirmation response dict.
        """
        payload: dict = {
            "book_token": book_token,
            "source_id": "resy.com-venue-details",
        }
        if payment_method:
            payload["struct_payment_method"] = payment_method

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.BASE_URL}/3/book",
                headers=self._headers(),
                json=payload,
            )

        if response.status_code != 200:
            logger.warning(
                "Resy book failed (HTTP %d): %s",
                response.status_code, response.text,
            )
            return {"error": response.text}

        return response.json()

    async def cancel(self, resy_token: str) -> bool:
        """Cancel a reservation.

        Args:
            resy_token: The reservation's resy_token / confirmation ID.

        Returns:
            True if cancellation succeeded.
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.BASE_URL}/3/cancel",
                headers=self._headers(),
                data={"resy_token": resy_token},
            )

        if response.status_code != 200:
            logger.warning(
                "Resy cancel failed (HTTP %d): %s",
                response.status_code, response.text,
            )
            return False
        return True

    async def get_user_reservations(self) -> list[dict]:
        """List the user's upcoming reservations."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self.BASE_URL}/3/user/reservations",
                headers=self._headers(),
            )

        if response.status_code != 200:
            logger.warning(
                "Resy get_user_reservations failed (HTTP %d): %s",
                response.status_code, response.text,
            )
            return []

        data = response.json()
        return data if isinstance(data, list) else data.get("reservations", [])

    async def search_venue(self, query: str) -> list[dict]:
        """Search for a Resy venue by name.

        Args:
            query: Restaurant name.

        Returns:
            List of venue dicts with id, name, location info.
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.BASE_URL}/3/venuesearch/search",
                headers=self._headers(),
                json={"query": query},
            )

        if response.status_code != 200:
            logger.warning(
                "Resy search_venue failed (HTTP %d): %s",
                response.status_code, response.text,
            )
            return []

        data = response.json()
        hits = data.get("search", {}).get("hits", [])
        return [self._parse_venue_hit(h) for h in hits]

    @staticmethod
    def _parse_venue_hit(hit: dict) -> dict:
        """Normalise a venue search hit into {id, name, location}."""
        # Try nested id.resy first, fall back to objectID / top-level id
        raw_id = hit.get("id", "")
        if isinstance(raw_id, dict):
            venue_id = str(raw_id.get("resy") or "")
        else:
            venue_id = str(
                hit.get("objectID", raw_id) or ""
            )
        return {
            "id": venue_id,
            "name": hit.get("name", ""),
            "location": hit.get("location", {}),
        }
