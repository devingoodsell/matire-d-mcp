"""OpenTable client using DAPI (frontend HTTP API).

Page fetches use the system ``curl`` binary (via subprocess) to bypass
Cloudflare TLS fingerprinting.  API calls (GraphQL, booking, cancel)
use ``httpx`` with stored browser session cookies.
"""

import asyncio
import json
import logging
import re
import subprocess
import urllib.parse

import httpx

from src.models.enums import BookingPlatform
from src.models.restaurant import TimeSlot
from src.storage.credentials import CredentialStore

logger = logging.getLogger(__name__)

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
        default header so that API requests carry the authenticated
        session cookies.
        """
        if self._http is None:
            headers: dict[str, str] = {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            }
            creds = self.credential_store.get_credentials("opentable")
            if creds and creds.get("cookies"):
                headers["Cookie"] = creds["cookies"]
            self._http = httpx.AsyncClient(
                timeout=30.0,
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

        url = f"{self.BASE_URL}/r/{slug}"
        try:
            html = await asyncio.to_thread(
                self._curl_fetch, url,
            )
            if html is None:
                return None
            rid = _extract_rid(html)
            if rid is not None:
                self._rid_cache[slug] = rid
            return rid
        except Exception as exc:  # noqa: BLE001
            logger.warning("OT page fetch error for %s: %s", slug, exc)
            return None

    @staticmethod
    def _curl_fetch(url: str, timeout: int = 15) -> str | None:
        """Fetch a URL using the system curl binary.

        System curl uses the OS TLS stack, which has a natural
        fingerprint that passes Cloudflare bot detection — unlike
        Python HTTP libraries (httpx, aiohttp, curl_cffi) which get
        blocked on OpenTable's ``/r/`` restaurant pages.
        """
        try:
            result = subprocess.run(
                ["curl", "-s", "--max-time", str(timeout), url],
                capture_output=True,
                text=True,
                timeout=timeout + 5,
            )
            if result.returncode != 0:
                logger.warning(
                    "curl fetch failed for %s (exit %d)", url, result.returncode,
                )
                return None
            return result.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            logger.warning("curl fetch error for %s: %s", url, exc)
            return None

    async def find_availability(
        self,
        restaurant_slug: str,
        date: str,
        party_size: int,
        preferred_time: str = "19:00",
    ) -> list[TimeSlot]:
        """Check availability via OpenTable DAPI GraphQL.

        Attempts the direct DAPI call first.  If that fails (Cloudflare
        bot protection), falls back to loading the restaurant page in
        Playwright and intercepting the GraphQL response.

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

        # Try direct DAPI call first
        slots = await self._dapi_availability(
            rid, date, party_size, preferred_time, restaurant_slug,
        )
        if slots:
            return slots

        # Fall back to Playwright browser
        return await self._playwright_availability(
            restaurant_slug, date, party_size, preferred_time,
        )

    async def _dapi_availability(
        self,
        rid: int,
        date: str,
        party_size: int,
        preferred_time: str,
        slug: str,
    ) -> list[TimeSlot]:
        """Direct DAPI GraphQL call (may be blocked by Cloudflare)."""
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
                logger.warning(
                    "OT DAPI availability returned %s", resp.status_code,
                )
                return []
            return _parse_availability_response(resp.json(), preferred_time)
        except (httpx.HTTPError, json.JSONDecodeError, KeyError) as exc:
            logger.warning(
                "OT DAPI availability failed for %s: %s", slug, exc,
            )
            return []

    async def _playwright_availability(
        self,
        slug: str,
        date: str,
        party_size: int,
        preferred_time: str,
    ) -> list[TimeSlot]:
        """Load restaurant page in Playwright, intercept GQL response."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.warning("Playwright not installed — cannot fetch OT availability")
            return []

        captured: list[dict] = []

        async def _on_response(response):
            if "RestaurantsAvailability" in response.url:
                try:
                    data = await response.json()
                    captured.append(data)
                except Exception:  # noqa: BLE001
                    pass

        url = _build_restaurant_url(
            self.BASE_URL, slug, date, party_size, preferred_time,
        )
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=False)
                page = await browser.new_page()
                page.on("response", _on_response)
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(8000)
                await browser.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Playwright availability failed for %s: %s", slug, exc)
            return []

        for data in captured:
            slots = _parse_availability_response(data, preferred_time)
            if slots:
                return slots
        return []

    async def _playwright_post(
        self,
        path: str,
        payload: dict,
        csrf_token: str,
        label: str,
    ) -> dict:
        """Make a DAPI POST via Playwright browser (bypasses Cloudflare).

        Loads the OpenTable homepage to establish a valid browser session,
        then uses ``page.evaluate`` to call ``fetch()`` from within the
        browser context where Akamai bot cookies are valid.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.warning("Playwright not installed — cannot POST %s", path)
            return {"error": "Playwright not installed"}

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=False)
                page = await browser.new_page()
                await page.goto(
                    self.BASE_URL, wait_until="domcontentloaded", timeout=30000,
                )
                await page.wait_for_timeout(3000)

                result = await page.evaluate(
                    """async ([url, body, csrf]) => {
                        const resp = await fetch(url, {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                                'x-csrf-token': csrf,
                            },
                            body: JSON.stringify(body),
                            credentials: 'include',
                        });
                        const text = await resp.text();
                        return {status: resp.status, body: text};
                    }""",
                    [f"{self.BASE_URL}{path}", payload, csrf_token],
                )
                await browser.close()

            status = result.get("status", 0)
            body_text = result.get("body", "")
            if status != 200:
                logger.warning(
                    "Playwright POST %s returned %s: %s",
                    path, status, body_text[:200],
                )
                return {"error": f"Playwright POST {path} returned {status}"}
            try:
                data = json.loads(body_text)
            except json.JSONDecodeError:
                return {"error": f"Invalid JSON from {path}"}
            conf = data.get(
                "confirmationNumber", data.get("reservationId", ""),
            )
            if conf:
                result = {"confirmation_number": str(conf)}
                if data.get("securityToken"):
                    result["security_token"] = data["securityToken"]
                return result
            return data
        except Exception as exc:  # noqa: BLE001
            logger.warning("Playwright POST %s failed: %s", label, exc)
            return {"error": str(exc)}

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
            "partySize": party_size,
            "reservationDateTime": f"{date}T{time}",
            "reservationType": "Standard",
            "reservationAttribute": "default",
            "pointsType": "Standard",
            "country": creds.get("country", "US"),
            "firstName": creds.get("first_name", ""),
            "lastName": creds.get("last_name", ""),
            "email": creds.get("email", ""),
            "phoneNumber": creds.get("phone", ""),
            "phoneNumberCountryId": creds.get("phone_country_id", "US"),
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
            result = {"confirmation_number": str(conf_number)}
            if data.get("securityToken"):
                result["security_token"] = data["securityToken"]
            return result
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            logger.warning("OT DAPI booking failed, trying Playwright: %s", exc)

        return await self._playwright_post(
            "/dapi/booking/make-reservation",
            booking_payload,
            creds["csrf_token"],
            restaurant_slug,
        )

    async def cancel(
        self, confirmation_number: str, *, rid: int | None = None,
    ) -> bool:
        """Cancel an OpenTable reservation via the mobile API.

        Uses ``DELETE`` on the mobile API endpoint, which requires the
        numeric restaurant ID and a bearer token extracted from the
        ``authCke`` session cookie.

        Args:
            confirmation_number: The reservation confirmation number.
            rid: Numeric restaurant ID.  When ``None`` the method tries
                 to find a cached rid from a prior ``_resolve_restaurant_id``
                 call.

        Returns:
            True if cancellation succeeded, False otherwise.
        """
        creds = self.credential_store.get_credentials("opentable")
        if not creds:
            logger.warning("Cannot cancel: no OpenTable credentials configured")
            return False

        bearer = _extract_bearer_token(creds.get("cookies", ""))
        if not bearer:
            logger.warning("Cannot cancel: no bearer token in OpenTable cookies")
            return False

        # Use supplied rid, or fall back to any cached value
        if rid is None:
            cached = list(self._rid_cache.values())
            if cached:
                rid = cached[0]
            else:
                logger.warning(
                    "Cannot cancel %s: no restaurant ID available",
                    confirmation_number,
                )
                return False

        url = (
            f"https://mobile-api.opentable.com"
            f"/api/v3/reservation/{rid}/{confirmation_number}"
        )
        result = await asyncio.to_thread(
            self._curl_delete, url, bearer,
        )
        if result is None:
            logger.warning(
                "OT mobile cancel failed for %s", confirmation_number,
            )
            return False
        return True

    @staticmethod
    def _curl_delete(url: str, bearer: str, timeout: int = 15) -> str | None:
        """DELETE via system curl with Bearer auth.

        Uses the system curl binary to bypass TLS fingerprinting, same
        as ``_curl_fetch`` for GET requests.
        """
        try:
            result = subprocess.run(
                [
                    "curl", "-s", "-X", "DELETE",
                    "--max-time", str(timeout),
                    "-H", f"Authorization: Bearer {bearer}",
                    "-H", "Content-Type: application/json",
                    url,
                ],
                capture_output=True,
                text=True,
                timeout=timeout + 5,
            )
            if result.returncode != 0:
                logger.warning(
                    "curl DELETE failed for %s (exit %d)",
                    url, result.returncode,
                )
                return None
            return result.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            logger.warning("curl DELETE error for %s: %s", url, exc)
            return None


def _extract_bearer_token(cookies: str) -> str | None:
    """Extract the access token from the ``authCke`` session cookie.

    The ``authCke`` cookie is URL-encoded and contains ``atk=<uuid>``
    which serves as a Bearer token for the OpenTable mobile API.
    """
    m = re.search(r"authCke=([^;]+)", cookies)
    if not m:
        return None
    decoded = urllib.parse.unquote(m.group(1))
    m2 = re.search(r"atk=([^&]+)", decoded)
    return m2.group(1) if m2 else None


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


def _parse_availability_response(
    data: dict, preferred_time: str = "19:00",
) -> list[TimeSlot]:
    """Parse the GraphQL availability response into TimeSlot objects.

    Handles two response formats:
    - Legacy: slots have ``timeString`` (e.g. "7:00 PM")
    - Current: slots have ``timeOffsetMinutes`` (offset from requested time)
    """
    slots: list[TimeSlot] = []
    availability_list = data.get("data", {}).get("availability", [])
    if not availability_list:
        return slots

    # Pre-compute the base time in minutes for offset calculation
    parts = preferred_time.split(":")
    base_minutes = int(parts[0]) * 60 + int(parts[1])

    for restaurant_avail in availability_list:
        for day in restaurant_avail.get("availabilityDays", []):
            for slot_data in day.get("slots", []):
                token = slot_data.get("slotAvailabilityToken", "")
                slot_hash = slot_data.get("slotHash", "")

                # Try timeString first (legacy format)
                time_str = slot_data.get("timeString", "")
                if time_str:
                    parsed_time = _parse_time(time_str)
                elif "timeOffsetMinutes" in slot_data:
                    offset = slot_data["timeOffsetMinutes"]
                    total = base_minutes + offset
                    parsed_time = f"{total // 60:02d}:{total % 60:02d}"
                else:
                    continue
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
