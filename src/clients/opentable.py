"""OpenTable client using DAPI (frontend HTTP API) — no browser automation."""

import json
import logging
import re
import urllib.parse

import httpx

from src.models.enums import BookingPlatform
from src.models.restaurant import TimeSlot
from src.storage.credentials import CredentialStore

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# GraphQL operation for availability
_AVAILABILITY_QUERY = """
query RestaurantsAvailability($onlyPop: Boolean, $requestedDate: String!,
  $requestedTime: String!, $covers: Int!, $restaurantIds: [Int!]!) {
  availability(
    onlyPop: $onlyPop
    requestedDate: $requestedDate
    requestedTime: $requestedTime
    covers: $covers
    restaurantIds: $restaurantIds
  ) {
    restaurantId
    availabilityDays {
      date
      slots {
        dateTime
        timeString
        slotAvailabilityToken
        slotHash
      }
    }
  }
}
"""


def _build_restaurant_url(
    base: str, slug: str, date: str, party_size: int, time: str,
) -> str:
    """Build an OpenTable restaurant URL with correct query params.

    OpenTable expects: ``/r/{slug}?covers=N&dateTime=YYYY-MM-DDTHH:MM``
    """
    date_time = f"{date}T{time}"
    params = urllib.parse.urlencode({"covers": party_size, "dateTime": date_time})
    return f"{base}/r/{slug}?{params}"


class OpenTableClient:
    """HTTP-based OpenTable client using DAPI (frontend API).

    Uses the same GraphQL and booking endpoints that the OpenTable
    website frontend uses, via plain HTTP requests.

    Args:
        credential_store: CredentialStore for reading OpenTable credentials.
    """

    BASE_URL = "https://www.opentable.com"

    def __init__(self, credential_store: CredentialStore) -> None:
        self.credential_store = credential_store
        self._http: httpx.AsyncClient | None = None
        self._rid_cache: dict[str, int] = {}

    def _get_http(self) -> httpx.AsyncClient:
        """Return (and lazily create) the shared httpx client.

        If stored credentials contain a ``cookies`` string (raw Cookie
        header copied from a browser session), it is attached as a
        default header so that every request carries the authenticated
        session cookies required to bypass bot protection.
        """
        if self._http is None:
            headers: dict[str, str] = {"User-Agent": _USER_AGENT}
            creds = self.credential_store.get_credentials("opentable")
            if creds and creds.get("cookies"):
                headers["Cookie"] = creds["cookies"]
            self._http = httpx.AsyncClient(
                timeout=15.0,
                follow_redirects=True,
                headers=headers,
            )
        return self._http

    async def close(self) -> None:
        """Close the httpx client."""
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def _resolve_restaurant_id(self, slug: str) -> int | None:
        """Resolve an OpenTable slug to a numeric restaurant ID.

        Fetches the restaurant page and extracts ``rid`` from the
        embedded data (``data-rid`` attribute or JSON payload).

        Results are cached in memory.
        """
        if slug in self._rid_cache:
            return self._rid_cache[slug]

        client = self._get_http()
        url = f"{self.BASE_URL}/r/{slug}"
        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.warning("OT page fetch failed for %s: %s", slug, resp.status_code)
                return None
            rid = _extract_rid(resp.text)
            if rid is not None:
                self._rid_cache[slug] = rid
            return rid
        except httpx.HTTPError as exc:
            logger.warning("OT page fetch error for %s: %s", slug, exc)
            return None

    async def find_availability(
        self,
        restaurant_slug: str,
        date: str,
        party_size: int,
        preferred_time: str = "19:00",
    ) -> list[TimeSlot]:
        """Check availability via OpenTable DAPI GraphQL.

        Args:
            restaurant_slug: OpenTable slug, e.g. "carbone-new-york".
            date: Date string YYYY-MM-DD.
            party_size: Number of diners.
            preferred_time: Center time for availability window (HH:MM, 24h).

        Returns:
            List of available TimeSlot objects.
        """
        rid = await self._resolve_restaurant_id(restaurant_slug)
        if rid is None:
            logger.warning("Could not resolve rid for %s", restaurant_slug)
            return []

        client = self._get_http()
        payload = {
            "operationName": "RestaurantsAvailability",
            "query": _AVAILABILITY_QUERY,
            "variables": {
                "onlyPop": False,
                "requestedDate": date,
                "requestedTime": preferred_time,
                "covers": party_size,
                "restaurantIds": [rid],
            },
        }

        try:
            resp = await client.post(
                f"{self.BASE_URL}/dapi/fe/gql"
                "?optype=query&opname=RestaurantsAvailability",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code != 200:
                logger.warning("OT DAPI availability returned %s", resp.status_code)
                return []
            return _parse_availability_response(resp.json())
        except (httpx.HTTPError, json.JSONDecodeError, KeyError) as exc:
            logger.warning("OT availability check failed for %s: %s", restaurant_slug, exc)
            return []

    async def book(
        self,
        restaurant_slug: str,
        date: str,
        time: str,
        party_size: int,
        slot_availability_token: str,
        slot_hash: str,
        special_requests: str | None = None,
    ) -> dict:
        """Book a reservation via DAPI make-reservation endpoint.

        Requires an authenticated CSRF token stored in credentials.

        Args:
            restaurant_slug: OpenTable slug.
            date: Date YYYY-MM-DD.
            time: Time HH:MM (24h).
            party_size: Number of diners.
            slot_availability_token: Token from availability response.
            slot_hash: Hash from availability response.
            special_requests: Optional special requests text.

        Returns:
            Dict with confirmation_number or error.
        """
        creds = self.credential_store.get_credentials("opentable")
        if not creds or not creds.get("csrf_token"):
            return {"error": "OpenTable CSRF token not configured. Store credentials first."}

        rid = await self._resolve_restaurant_id(restaurant_slug)
        if rid is None:
            return {"error": f"Could not resolve restaurant ID for {restaurant_slug}"}

        client = self._get_http()
        booking_payload = {
            "restaurantId": rid,
            "slotAvailabilityToken": slot_availability_token,
            "slotHash": slot_hash,
            "covers": party_size,
            "dateTime": f"{date}T{time}",
            "firstName": creds.get("first_name", ""),
            "lastName": creds.get("last_name", ""),
            "email": creds.get("email", ""),
            "phoneNumber": creds.get("phone", ""),
        }
        if special_requests:
            booking_payload["specialRequests"] = special_requests

        try:
            resp = await client.post(
                f"{self.BASE_URL}/dapi/booking/make-reservation",
                json=booking_payload,
                headers={
                    "Content-Type": "application/json",
                    "x-csrf-token": creds["csrf_token"],
                },
            )
            if resp.status_code != 200:
                return {"error": f"Booking failed with status {resp.status_code}"}
            data = resp.json()
            conf_number = data.get("confirmationNumber", data.get("reservationId", ""))
            return {"confirmation_number": str(conf_number)}
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            logger.warning("OT booking failed: %s", exc)
            return {"error": str(exc)}

    async def cancel(self, confirmation_number: str) -> bool:
        """Cancel an OpenTable reservation via DAPI.

        Sends a POST to the DAPI cancel-reservation endpoint with the
        confirmation number and CSRF token.

        Args:
            confirmation_number: The reservation confirmation number.

        Returns:
            True if cancellation succeeded, False otherwise.
        """
        creds = self.credential_store.get_credentials("opentable")
        if not creds or not creds.get("csrf_token"):
            logger.warning("Cannot cancel: OpenTable CSRF token not configured")
            return False

        client = self._get_http()
        try:
            resp = await client.post(
                f"{self.BASE_URL}/dapi/booking/cancel-reservation",
                json={"confirmationNumber": confirmation_number},
                headers={
                    "Content-Type": "application/json",
                    "x-csrf-token": creds["csrf_token"],
                },
            )
            if resp.status_code == 200:
                return True
            logger.warning(
                "OT cancel returned %s for %s", resp.status_code, confirmation_number,
            )
            return False
        except httpx.HTTPError as exc:
            logger.warning("OT cancel failed for %s: %s", confirmation_number, exc)
            return False


def _extract_rid(html: str) -> int | None:
    """Extract the numeric restaurant ID from an OpenTable page.

    Tries multiple patterns:
    1. ``data-rid="12345"`` attribute
    2. ``"rid":12345`` in embedded JSON
    3. ``"restaurantId":12345`` in embedded JSON
    """
    # Pattern 1: data attribute
    m = re.search(r'data-rid="(\d+)"', html)
    if m:
        return int(m.group(1))

    # Pattern 2: "rid":N in JSON
    m = re.search(r'"rid"\s*:\s*(\d+)', html)
    if m:
        return int(m.group(1))

    # Pattern 3: "restaurantId":N in JSON
    m = re.search(r'"restaurantId"\s*:\s*(\d+)', html)
    if m:
        return int(m.group(1))

    return None


def _parse_availability_response(data: dict) -> list[TimeSlot]:
    """Parse the GraphQL availability response into TimeSlot objects."""
    slots: list[TimeSlot] = []
    availability_list = data.get("data", {}).get("availability", [])
    if not availability_list:
        return slots

    for restaurant_avail in availability_list:
        for day in restaurant_avail.get("availabilityDays", []):
            for slot_data in day.get("slots", []):
                time_str = slot_data.get("timeString", "")
                token = slot_data.get("slotAvailabilityToken", "")
                slot_hash = slot_data.get("slotHash", "")
                if not time_str:
                    continue
                parsed_time = _parse_time(time_str)
                slots.append(
                    TimeSlot(
                        time=parsed_time,
                        platform=BookingPlatform.OPENTABLE,
                        type=None,
                        config_id=f"{token}|{slot_hash}",
                    )
                )
    return slots


def _parse_time(text: str) -> str:
    """Parse time text into HH:MM format.

    Handles formats like "7:00 PM", "19:00", "7:30pm".
    """
    text = text.strip().upper()

    if "AM" not in text and "PM" not in text:
        return text.replace(" ", "")

    is_pm = "PM" in text
    text = text.replace("AM", "").replace("PM", "").strip()
    parts = text.split(":")
    hour = int(parts[0])
    minute = parts[1] if len(parts) > 1 else "00"

    if is_pm and hour != 12:
        hour += 12
    elif not is_pm and hour == 12:
        hour = 0

    return f"{hour:02d}:{minute}"
