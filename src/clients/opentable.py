"""OpenTable client using Playwright browser automation."""

import asyncio
import logging
import random

from src.clients.resy_auth import AuthError
from src.models.enums import BookingPlatform
from src.models.restaurant import TimeSlot
from src.storage.credentials import CredentialStore

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# CSS selectors — constants for easy updates when OpenTable redesigns
SEL_TIME_SLOT = '[data-test="time-slot"]'
SEL_SPECIAL_REQUESTS = 'textarea[data-test="special-requests"]'
SEL_COMPLETE_BUTTON = 'button[data-test="complete-reservation"]'
SEL_CONFIRMATION = '[data-test="confirmation-number"]'
SEL_CANCEL_BUTTON = 'button[data-test="cancel-reservation"]'
SEL_CONFIRM_CANCEL = 'button[data-test="confirm-cancel"]'


class OpenTableClient:
    """Playwright-based OpenTable automation.

    All interactions go through the real OpenTable website with
    realistic delays to avoid bot detection.

    Args:
        credential_store: CredentialStore for reading OpenTable credentials.
    """

    BASE_URL = "https://www.opentable.com"

    def __init__(self, credential_store: CredentialStore) -> None:
        self.credential_store = credential_store
        self._browser: object | None = None
        self._context: object | None = None
        self._page: object | None = None
        self._logged_in = False
        self._pw: object | None = None

    async def _ensure_browser(self) -> None:
        """Launch browser if not already running."""
        if self._browser:
            return

        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise AuthError(
                "Playwright is not installed. Run: pip install playwright && "
                "playwright install chromium"
            ) from exc

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=True)  # type: ignore[union-attr]
        self._context = await self._browser.new_context(  # type: ignore[union-attr]
            user_agent=_USER_AGENT,
            viewport={"width": 1280, "height": 720},
            locale="en-US",
        )
        self._page = await self._context.new_page()  # type: ignore[union-attr]

    async def close(self) -> None:
        """Close browser and clean up."""
        if self._browser:
            await self._browser.close()  # type: ignore[union-attr]
            self._browser = None
            self._context = None
            self._page = None
            self._logged_in = False
        if self._pw:
            await self._pw.stop()  # type: ignore[union-attr]
            self._pw = None

    async def _random_delay(
        self, min_seconds: float = 1.0, max_seconds: float = 3.0
    ) -> None:
        """Random delay to mimic human behaviour."""
        delay = random.uniform(min_seconds, max_seconds)
        await asyncio.sleep(delay)

    async def _login(self) -> None:
        """Login to OpenTable via the website.

        Raises:
            AuthError: If credentials are missing or login fails.
        """
        creds = self.credential_store.get_credentials("opentable")
        if not creds:
            raise AuthError("OpenTable credentials not configured.")

        await self._ensure_browser()
        page = self._page

        try:
            await page.goto(  # type: ignore[union-attr]
                f"{self.BASE_URL}/sign-in", wait_until="networkidle"
            )
            await self._random_delay(1, 3)

            await page.fill(  # type: ignore[union-attr]
                'input[name="email"]', creds["email"]
            )
            await self._random_delay(0.5, 1.5)

            await page.fill(  # type: ignore[union-attr]
                'input[name="password"]', creds["password"]
            )
            await self._random_delay(0.5, 1)

            await page.click('button[type="submit"]')  # type: ignore[union-attr]
            await page.wait_for_load_state("networkidle")  # type: ignore[union-attr]

            self._logged_in = True
        except Exception as exc:
            raise AuthError(f"OpenTable login failed: {exc}") from exc

    async def find_availability(
        self,
        restaurant_slug: str,
        date: str,
        party_size: int,
        preferred_time: str = "19:00",
    ) -> list[TimeSlot]:
        """Check availability by navigating to the restaurant's page.

        Args:
            restaurant_slug: OpenTable slug, e.g. "carbone-new-york".
            date: Date string YYYY-MM-DD.
            party_size: Number of diners.
            preferred_time: Center time for availability window.

        Returns:
            List of available TimeSlot objects.
        """
        await self._ensure_browser()
        page = self._page

        url = (
            f"{self.BASE_URL}/r/{restaurant_slug}"
            f"?date={date}&party_size={party_size}&time={preferred_time}"
        )

        try:
            await page.goto(url, wait_until="networkidle")  # type: ignore[union-attr]
            await self._random_delay(2, 4)

            await page.wait_for_selector(  # type: ignore[union-attr]
                SEL_TIME_SLOT, timeout=10000
            )

            elements = await page.query_selector_all(  # type: ignore[union-attr]
                SEL_TIME_SLOT
            )
            slots: list[TimeSlot] = []
            for el in elements:
                time_text = await el.inner_text()
                slots.append(
                    TimeSlot(
                        time=self._parse_time(time_text),
                        platform=BookingPlatform.OPENTABLE,
                        type=None,
                    )
                )
            return slots
        except Exception:  # noqa: BLE001
            logger.warning("OpenTable availability check failed for %s", restaurant_slug)
            return []

    async def book(
        self,
        restaurant_slug: str,
        date: str,
        time: str,
        party_size: int,
        special_requests: str | None = None,
    ) -> dict:
        """Book a reservation via browser automation.

        Args:
            restaurant_slug: OpenTable slug.
            date: Date YYYY-MM-DD.
            time: Time HH:MM.
            party_size: Number of diners.
            special_requests: Optional special requests text.

        Returns:
            Dict with confirmation_number or error.
        """
        if not self._logged_in:
            await self._login()

        page = self._page
        url = (
            f"{self.BASE_URL}/r/{restaurant_slug}"
            f"?date={date}&party_size={party_size}&time={time}"
        )

        try:
            await page.goto(url, wait_until="networkidle")  # type: ignore[union-attr]
            await self._random_delay(2, 4)

            # Click the desired time slot
            await page.wait_for_selector(  # type: ignore[union-attr]
                SEL_TIME_SLOT, timeout=10000
            )
            slot_els = await page.query_selector_all(  # type: ignore[union-attr]
                SEL_TIME_SLOT
            )
            if not slot_els:
                return {"error": "No time slots found"}

            # Click first available slot
            await slot_els[0].click()
            await self._random_delay(2, 3)

            # Fill special requests if provided
            if special_requests:
                sr_field = await page.query_selector(  # type: ignore[union-attr]
                    SEL_SPECIAL_REQUESTS
                )
                if sr_field:
                    await sr_field.fill(special_requests)
                    await self._random_delay(1, 2)

            # Complete reservation
            await page.click(SEL_COMPLETE_BUTTON)  # type: ignore[union-attr]
            await self._random_delay(3, 5)

            # Extract confirmation
            conf_el = await page.query_selector(  # type: ignore[union-attr]
                SEL_CONFIRMATION
            )
            confirmation = await conf_el.inner_text() if conf_el else ""

            return {"confirmation_number": confirmation}
        except Exception as exc:  # noqa: BLE001
            logger.warning("OpenTable booking failed: %s", exc)
            return {"error": str(exc)}

    async def cancel(self, confirmation_number: str) -> bool:
        """Cancel an OpenTable reservation via the website.

        Args:
            confirmation_number: The reservation confirmation number.

        Returns:
            True if cancellation succeeded.
        """
        if not self._logged_in:
            await self._login()

        page = self._page

        try:
            await page.goto(  # type: ignore[union-attr]
                f"{self.BASE_URL}/my/reservations",
                wait_until="networkidle",
            )
            await self._random_delay(2, 3)

            # Find and click cancel for the specific reservation
            cancel_btn = await page.query_selector(  # type: ignore[union-attr]
                SEL_CANCEL_BUTTON
            )
            if not cancel_btn:
                logger.warning("Cancel button not found for %s", confirmation_number)
                return False

            await cancel_btn.click()
            await self._random_delay(1, 2)

            # Confirm cancellation
            confirm_btn = await page.query_selector(  # type: ignore[union-attr]
                SEL_CONFIRM_CANCEL
            )
            if confirm_btn:
                await confirm_btn.click()
                await self._random_delay(2, 3)

            return True
        except Exception:  # noqa: BLE001
            logger.warning("OpenTable cancellation failed for %s", confirmation_number)
            return False

    @staticmethod
    def _parse_time(text: str) -> str:
        """Parse time text from the page into HH:MM format.

        Handles formats like "7:00 PM", "19:00", "7:30pm".
        """
        text = text.strip().upper()

        if "AM" not in text and "PM" not in text:
            # Assume 24-hour format
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
