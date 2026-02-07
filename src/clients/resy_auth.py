"""Resy authentication manager with API-first, Playwright-fallback strategy."""

import logging

import httpx

from src.clients.resy import ResyClient
from src.storage.credentials import CredentialStore

logger = logging.getLogger(__name__)


class AuthError(Exception):
    """Raised when authentication fails on both API and Playwright paths."""


class ResyAuthManager:
    """Manages Resy auth with automatic token refresh.

    Args:
        credential_store: CredentialStore for reading/saving credentials.
    """

    def __init__(self, credential_store: CredentialStore) -> None:
        self.credential_store = credential_store

    async def authenticate(self, email: str, password: str) -> dict:
        """Authenticate with API first, Playwright fallback.

        Returns:
            Dict with auth_token, api_key, payment_methods.

        Raises:
            AuthError: If both methods fail.
        """
        try:
            return await self._auth_via_api(email, password)
        except (httpx.HTTPStatusError, httpx.HTTPError):
            logger.info("API auth failed, trying Playwright fallback")
            return await self._auth_via_playwright(email, password)

    async def _auth_via_api(self, email: str, password: str) -> dict:
        """Authenticate using Resy's password endpoint."""
        client = ResyClient()
        return await client.authenticate(email, password)

    async def _auth_via_playwright(self, email: str, password: str) -> dict:
        """Authenticate by driving a headless browser.

        Launches Chromium, navigates to resy.com, intercepts
        network requests to capture the auth token.

        Raises:
            AuthError: If browser auth fails.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise AuthError(
                "Playwright is not installed. Run: pip install playwright && "
                "playwright install chromium"
            ) from exc

        auth_token: str | None = None
        api_key: str | None = None

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()

            # Intercept responses to capture auth token
            async def _handle_response(response):  # type: ignore[no-untyped-def]
                nonlocal auth_token, api_key
                if "/auth/password" in response.url or "/auth" in response.url:
                    try:
                        body = await response.json()
                        if "token" in body:
                            auth_token = body["token"]
                        if "api_key" in body:
                            api_key = body["api_key"]
                    except Exception:  # noqa: BLE001
                        pass

            page.on("response", _handle_response)

            try:
                await page.goto("https://resy.com", wait_until="networkidle")

                # Click login and fill credentials
                login_btn = page.locator('button:text("Log in")')
                if await login_btn.count() > 0:
                    await login_btn.first.click()

                await page.fill('input[name="email"]', email)
                await page.fill('input[name="password"]', password)
                await page.click('button[type="submit"]')

                # Wait for auth response
                await page.wait_for_timeout(5000)
            except Exception as exc:
                await browser.close()
                raise AuthError(f"Playwright auth failed: {exc}") from exc

            await browser.close()

        if not auth_token:
            raise AuthError("Could not capture auth token from browser session")

        from src.clients.resy import DEFAULT_API_KEY

        return {
            "auth_token": auth_token,
            "api_key": api_key or DEFAULT_API_KEY,
            "payment_methods": [],
        }

    async def ensure_valid_token(self) -> str:
        """Check token validity and refresh if needed.

        Returns:
            A valid auth token string.

        Raises:
            AuthError: If no credentials are stored or refresh fails.
        """
        creds = self.credential_store.get_credentials("resy")
        if not creds:
            raise AuthError("No Resy credentials stored. Use store_resy_credentials first.")

        auth_token = creds.get("auth_token", "")

        # Quick validity check — try a lightweight API call
        if auth_token and await self._is_token_valid(auth_token, creds.get("api_key", "")):
            return auth_token

        # Token expired or invalid — re-authenticate
        logger.info("Resy token expired, re-authenticating")
        email = creds.get("email", "")
        password = creds.get("password", "")
        if not email or not password:
            raise AuthError("Stored credentials missing email or password.")

        new_creds = await self.authenticate(email, password)
        merged = {**creds, **new_creds}
        self.credential_store.save_credentials("resy", merged)
        return new_creds["auth_token"]

    async def _is_token_valid(self, auth_token: str, api_key: str) -> bool:
        """Check if the auth token is still valid via a lightweight API call."""
        client = ResyClient(api_key=api_key, auth_token=auth_token)
        try:
            reservations = await client.get_user_reservations()
            # If we got a list back (even empty), the token works
            return isinstance(reservations, list)
        except (httpx.HTTPError, Exception):  # noqa: BLE001
            return False
