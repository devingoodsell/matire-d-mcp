"""Tests for ResyAuthManager: API auth, Playwright fallback, token management."""

import sys
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.clients.resy_auth import AuthError, ResyAuthManager
from src.storage.credentials import CredentialStore


def _make_credential_store(tmp_path) -> CredentialStore:
    """Build a real CredentialStore backed by a temp directory."""
    return CredentialStore(tmp_path / "creds")


def _build_playwright_mocks(*, login_btn_count=1):
    """Build the full mock chain for playwright objects.

    Returns (mock_page, mock_browser, mock_async_pw, fake_pw_module).

    ``page.locator`` is a synchronous MagicMock (Playwright's real API), so
    that ``await login_btn.count()`` works correctly.
    """
    mock_login_btn = MagicMock()
    mock_login_btn.count = AsyncMock(return_value=login_btn_count)
    mock_login_btn.first = MagicMock()
    mock_login_btn.first.click = AsyncMock()

    mock_page = AsyncMock()
    # page.locator() is synchronous in Playwright -- must be a MagicMock
    mock_page.locator = MagicMock(return_value=mock_login_btn)

    mock_context = AsyncMock()
    mock_context.new_page.return_value = mock_page
    mock_browser = AsyncMock()
    mock_browser.new_context.return_value = mock_context

    mock_pw_instance = MagicMock()
    mock_pw_instance.chromium.launch = AsyncMock(return_value=mock_browser)

    mock_async_pw = AsyncMock()
    mock_async_pw.__aenter__.return_value = mock_pw_instance
    mock_async_pw.__aexit__.return_value = False

    fake_pw_module = ModuleType("playwright.async_api")
    fake_pw_module.async_playwright = MagicMock(return_value=mock_async_pw)

    return mock_page, mock_browser, mock_async_pw, fake_pw_module


def _fake_modules(fake_pw_module):
    """Return the sys.modules dict for patch.dict."""
    return {
        "playwright": ModuleType("playwright"),
        "playwright.async_api": fake_pw_module,
    }


# ── authenticate ─────────────────────────────────────────────────────────────


class TestAuthenticate:
    """authenticate() delegates to API, falls back to Playwright on error."""

    async def test_api_auth_succeeds_returns_result(self, tmp_path):
        store = _make_credential_store(tmp_path)
        manager = ResyAuthManager(store)
        expected = {"auth_token": "tok", "api_key": "key", "payment_methods": []}

        with patch.object(manager, "_auth_via_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = expected
            result = await manager.authenticate("a@b.com", "pw")

        assert result == expected
        mock_api.assert_awaited_once_with("a@b.com", "pw")

    async def test_api_http_status_error_falls_back_to_playwright(self, tmp_path):
        store = _make_credential_store(tmp_path)
        manager = ResyAuthManager(store)
        expected = {"auth_token": "pw_tok", "api_key": "k", "payment_methods": []}

        request = httpx.Request("POST", "https://api.resy.com/3/auth/password")
        response = httpx.Response(status_code=403, request=request)
        api_error = httpx.HTTPStatusError(
            "forbidden", request=request, response=response
        )

        with (
            patch.object(
                manager, "_auth_via_api", new_callable=AsyncMock
            ) as mock_api,
            patch.object(
                manager, "_auth_via_playwright", new_callable=AsyncMock
            ) as mock_pw,
        ):
            mock_api.side_effect = api_error
            mock_pw.return_value = expected
            result = await manager.authenticate("a@b.com", "pw")

        assert result == expected
        mock_pw.assert_awaited_once_with("a@b.com", "pw")

    async def test_api_http_error_falls_back_to_playwright(self, tmp_path):
        store = _make_credential_store(tmp_path)
        manager = ResyAuthManager(store)
        expected = {"auth_token": "pw_tok2", "api_key": "k2", "payment_methods": []}

        with (
            patch.object(
                manager, "_auth_via_api", new_callable=AsyncMock
            ) as mock_api,
            patch.object(
                manager, "_auth_via_playwright", new_callable=AsyncMock
            ) as mock_pw,
        ):
            mock_api.side_effect = httpx.ConnectError("connection refused")
            mock_pw.return_value = expected
            result = await manager.authenticate("a@b.com", "pw")

        assert result == expected
        mock_pw.assert_awaited_once_with("a@b.com", "pw")


# ── _auth_via_api ────────────────────────────────────────────────────────────


class TestAuthViaApi:
    """_auth_via_api delegates to ResyClient().authenticate()."""

    async def test_delegates_to_resy_client(self, tmp_path):
        store = _make_credential_store(tmp_path)
        manager = ResyAuthManager(store)
        expected = {"auth_token": "t", "api_key": "k", "payment_methods": []}

        with patch("src.clients.resy_auth.ResyClient") as mock_cls:
            instance = mock_cls.return_value
            instance.authenticate = AsyncMock(return_value=expected)
            result = await manager._auth_via_api("a@b.com", "pw")

        assert result == expected
        instance.authenticate.assert_awaited_once_with("a@b.com", "pw")


# ── _auth_via_playwright ─────────────────────────────────────────────────────


def _install_response_handler(mock_page):
    """Attach a capture_on helper to mock_page and return a mutable holder.

    The returned ``holder`` dict will contain ``"handler"`` once page.on is
    called by the source code under test.
    """
    holder: dict = {}

    def capture_on(event, handler):
        if event == "response":
            holder["handler"] = handler

    mock_page.on = capture_on
    return holder


class TestAuthViaPlaywright:
    """_auth_via_playwright: browser-based auth, ImportError, failures."""

    async def test_import_error_raises_auth_error(self, tmp_path):
        store = _make_credential_store(tmp_path)
        manager = ResyAuthManager(store)

        fake = {"playwright": None, "playwright.async_api": None}
        with patch.dict(sys.modules, fake):
            with pytest.raises(AuthError, match="Playwright is not installed"):
                await manager._auth_via_playwright("a@b.com", "pw")

    async def test_successful_browser_flow_captures_token(self, tmp_path):
        store = _make_credential_store(tmp_path)
        manager = ResyAuthManager(store)

        mock_page, _browser, _pw, fake_mod = _build_playwright_mocks(
            login_btn_count=1
        )
        holder = _install_response_handler(mock_page)
        original_wait = mock_page.wait_for_timeout

        async def trigger_response_and_wait(ms):
            mock_resp = AsyncMock()
            mock_resp.url = "https://api.resy.com/3/auth/password"
            mock_resp.json = AsyncMock(
                return_value={"token": "browser_tok", "api_key": "browser_key"}
            )
            handler = holder.get("handler")
            if handler:
                await handler(mock_resp)
            return await original_wait(ms)

        mock_page.wait_for_timeout = AsyncMock(
            side_effect=trigger_response_and_wait
        )

        with patch.dict(sys.modules, _fake_modules(fake_mod)):
            result = await manager._auth_via_playwright("a@b.com", "pw")

        assert result["auth_token"] == "browser_tok"
        assert result["api_key"] == "browser_key"
        assert result["payment_methods"] == []

    async def test_no_token_captured_raises_auth_error(self, tmp_path):
        store = _make_credential_store(tmp_path)
        manager = ResyAuthManager(store)

        mock_page, _browser, _pw, fake_mod = _build_playwright_mocks(
            login_btn_count=0
        )
        mock_page.on = MagicMock()  # no handler needed

        with patch.dict(sys.modules, _fake_modules(fake_mod)):
            with pytest.raises(AuthError, match="Could not capture auth token"):
                await manager._auth_via_playwright("a@b.com", "pw")

    async def test_browser_exception_raises_auth_error(self, tmp_path):
        store = _make_credential_store(tmp_path)
        manager = ResyAuthManager(store)

        mock_page, mock_browser, _pw, fake_mod = _build_playwright_mocks()
        mock_page.goto.side_effect = RuntimeError("browser crashed")
        mock_page.on = MagicMock()

        with patch.dict(sys.modules, _fake_modules(fake_mod)):
            with pytest.raises(AuthError, match="Playwright auth failed"):
                await manager._auth_via_playwright("a@b.com", "pw")

        mock_browser.close.assert_awaited()

    async def test_response_handler_ignores_non_auth_urls(self, tmp_path):
        """Response handler only captures tokens from auth URLs."""
        store = _make_credential_store(tmp_path)
        manager = ResyAuthManager(store)

        mock_page, _browser, _pw, fake_mod = _build_playwright_mocks(
            login_btn_count=1
        )
        holder = _install_response_handler(mock_page)
        original_wait = mock_page.wait_for_timeout

        async def trigger_non_auth_response(ms):
            mock_resp = AsyncMock()
            mock_resp.url = "https://api.resy.com/4/venue/search"
            mock_resp.json = AsyncMock(return_value={"results": []})
            handler = holder.get("handler")
            if handler:
                await handler(mock_resp)
            return await original_wait(ms)

        mock_page.wait_for_timeout = AsyncMock(
            side_effect=trigger_non_auth_response
        )

        with patch.dict(sys.modules, _fake_modules(fake_mod)):
            with pytest.raises(AuthError, match="Could not capture auth token"):
                await manager._auth_via_playwright("a@b.com", "pw")

    async def test_response_handler_survives_json_exception(self, tmp_path):
        """Response handler catches exceptions from response.json()."""
        store = _make_credential_store(tmp_path)
        manager = ResyAuthManager(store)

        mock_page, _browser, _pw, fake_mod = _build_playwright_mocks(
            login_btn_count=1
        )
        holder = _install_response_handler(mock_page)
        original_wait = mock_page.wait_for_timeout

        async def trigger_broken_response(ms):
            mock_resp = AsyncMock()
            mock_resp.url = "https://api.resy.com/3/auth/password"
            mock_resp.json = AsyncMock(side_effect=ValueError("bad json"))
            handler = holder.get("handler")
            if handler:
                await handler(mock_resp)
            return await original_wait(ms)

        mock_page.wait_for_timeout = AsyncMock(
            side_effect=trigger_broken_response
        )

        with patch.dict(sys.modules, _fake_modules(fake_mod)):
            with pytest.raises(AuthError, match="Could not capture auth token"):
                await manager._auth_via_playwright("a@b.com", "pw")

    async def test_response_with_token_but_no_api_key_uses_default(self, tmp_path):
        """When browser captures token but no api_key, DEFAULT_API_KEY is used."""
        store = _make_credential_store(tmp_path)
        manager = ResyAuthManager(store)

        mock_page, _browser, _pw, fake_mod = _build_playwright_mocks(
            login_btn_count=1
        )
        holder = _install_response_handler(mock_page)
        original_wait = mock_page.wait_for_timeout

        async def trigger_token_only_response(ms):
            mock_resp = AsyncMock()
            mock_resp.url = "https://api.resy.com/3/auth"
            mock_resp.json = AsyncMock(return_value={"token": "only_tok"})
            handler = holder.get("handler")
            if handler:
                await handler(mock_resp)
            return await original_wait(ms)

        mock_page.wait_for_timeout = AsyncMock(
            side_effect=trigger_token_only_response
        )

        with patch.dict(sys.modules, _fake_modules(fake_mod)):
            result = await manager._auth_via_playwright("a@b.com", "pw")

        from src.clients.resy import DEFAULT_API_KEY

        assert result["auth_token"] == "only_tok"
        assert result["api_key"] == DEFAULT_API_KEY
        assert result["payment_methods"] == []

    async def test_auth_response_without_token_key_does_not_set_token(self, tmp_path):
        """Auth URL response that has no 'token' key -- auth_token stays None."""
        store = _make_credential_store(tmp_path)
        manager = ResyAuthManager(store)

        mock_page, _browser, _pw, fake_mod = _build_playwright_mocks(
            login_btn_count=1
        )
        holder = _install_response_handler(mock_page)
        original_wait = mock_page.wait_for_timeout

        async def trigger_no_token_response(ms):
            mock_resp = AsyncMock()
            mock_resp.url = "https://api.resy.com/3/auth/password"
            # Body contains api_key but NOT token
            mock_resp.json = AsyncMock(
                return_value={"api_key": "some_key", "other": "data"}
            )
            handler = holder.get("handler")
            if handler:
                await handler(mock_resp)
            return await original_wait(ms)

        mock_page.wait_for_timeout = AsyncMock(
            side_effect=trigger_no_token_response
        )

        with patch.dict(sys.modules, _fake_modules(fake_mod)):
            with pytest.raises(AuthError, match="Could not capture auth token"):
                await manager._auth_via_playwright("a@b.com", "pw")


# ── ensure_valid_token ───────────────────────────────────────────────────────


class TestEnsureValidToken:
    """ensure_valid_token: credential lookup, validation, refresh."""

    async def test_no_credentials_raises_auth_error(self, tmp_path):
        store = _make_credential_store(tmp_path)
        manager = ResyAuthManager(store)

        with pytest.raises(AuthError, match="No Resy credentials stored"):
            await manager.ensure_valid_token()

    async def test_valid_token_returns_existing(self, tmp_path):
        store = _make_credential_store(tmp_path)
        store.save_credentials(
            "resy",
            {
                "auth_token": "valid_tok",
                "api_key": "key",
                "email": "a@b.com",
                "password": "pw",
            },
        )
        manager = ResyAuthManager(store)

        with patch.object(
            manager, "_is_token_valid", new_callable=AsyncMock
        ) as mock_valid:
            mock_valid.return_value = True
            result = await manager.ensure_valid_token()

        assert result == "valid_tok"

    async def test_expired_token_reauthenticates(self, tmp_path):
        store = _make_credential_store(tmp_path)
        store.save_credentials(
            "resy",
            {
                "auth_token": "old_tok",
                "api_key": "key",
                "email": "a@b.com",
                "password": "pw",
            },
        )
        manager = ResyAuthManager(store)

        new_creds = {
            "auth_token": "new_tok",
            "api_key": "new_key",
            "payment_methods": [],
        }

        with (
            patch.object(
                manager, "_is_token_valid", new_callable=AsyncMock
            ) as mock_valid,
            patch.object(
                manager, "authenticate", new_callable=AsyncMock
            ) as mock_auth,
        ):
            mock_valid.return_value = False
            mock_auth.return_value = new_creds
            result = await manager.ensure_valid_token()

        assert result == "new_tok"
        mock_auth.assert_awaited_once_with("a@b.com", "pw")

        # Verify credentials were persisted without password
        saved = store.get_credentials("resy")
        assert saved["auth_token"] == "new_tok"
        assert saved["email"] == "a@b.com"
        assert "password" not in saved

    async def test_missing_email_password_raises_auth_error(self, tmp_path):
        store = _make_credential_store(tmp_path)
        store.save_credentials(
            "resy",
            {"auth_token": "stale", "api_key": "key"},
        )
        manager = ResyAuthManager(store)

        mock_settings = MagicMock()
        mock_settings.resy_password = None
        with (
            patch.object(
                manager, "_is_token_valid", new_callable=AsyncMock
            ) as mock_valid,
            patch("src.config.get_settings", return_value=mock_settings),
        ):
            mock_valid.return_value = False
            with pytest.raises(AuthError, match="Token expired"):
                await manager.ensure_valid_token()

    async def test_empty_auth_token_triggers_refresh(self, tmp_path):
        store = _make_credential_store(tmp_path)
        store.save_credentials(
            "resy",
            {
                "auth_token": "",
                "api_key": "key",
                "email": "a@b.com",
                "password": "pw",
            },
        )
        manager = ResyAuthManager(store)

        new_creds = {
            "auth_token": "fresh_tok",
            "api_key": "k",
            "payment_methods": [],
        }

        with patch.object(
            manager, "authenticate", new_callable=AsyncMock
        ) as mock_auth:
            mock_auth.return_value = new_creds
            result = await manager.ensure_valid_token()

        assert result == "fresh_tok"
        mock_auth.assert_awaited_once_with("a@b.com", "pw")

    async def test_missing_email_with_password_raises_auth_error(self, tmp_path):
        """Credentials have password but not email."""
        store = _make_credential_store(tmp_path)
        store.save_credentials(
            "resy",
            {"auth_token": "stale", "api_key": "key", "password": "pw"},
        )
        manager = ResyAuthManager(store)

        with patch.object(
            manager, "_is_token_valid", new_callable=AsyncMock
        ) as mock_valid:
            mock_valid.return_value = False
            with pytest.raises(AuthError, match="Token expired"):
                await manager.ensure_valid_token()

    async def test_missing_password_with_email_raises_auth_error(self, tmp_path):
        """Credentials have email but not password — no env var set either."""
        store = _make_credential_store(tmp_path)
        store.save_credentials(
            "resy",
            {"auth_token": "stale", "api_key": "key", "email": "a@b.com"},
        )
        manager = ResyAuthManager(store)

        mock_settings = MagicMock()
        mock_settings.resy_password = None
        with (
            patch.object(
                manager, "_is_token_valid", new_callable=AsyncMock
            ) as mock_valid,
            patch("src.config.get_settings", return_value=mock_settings),
        ):
            mock_valid.return_value = False
            with pytest.raises(AuthError, match="Token expired"):
                await manager.ensure_valid_token()

    async def test_config_store_password_used_for_refresh(self, tmp_path):
        """When password not in stored creds, ConfigStore is checked first."""
        store = _make_credential_store(tmp_path)
        store.save_credentials(
            "resy",
            {"auth_token": "stale", "api_key": "key", "email": "a@b.com"},
        )
        manager = ResyAuthManager(store)

        new_creds = {
            "auth_token": "cs_tok",
            "api_key": "new_key",
            "payment_methods": [],
        }

        mock_cs = AsyncMock()
        mock_cs.get = AsyncMock(return_value="config-store-pw")

        with (
            patch.object(
                manager, "_is_token_valid", new_callable=AsyncMock
            ) as mock_valid,
            patch.object(
                manager, "authenticate", new_callable=AsyncMock
            ) as mock_auth,
            patch("src.server._config_store", mock_cs),
        ):
            mock_valid.return_value = False
            mock_auth.return_value = new_creds
            result = await manager.ensure_valid_token()

        assert result == "cs_tok"
        mock_auth.assert_awaited_once_with("a@b.com", "config-store-pw")

    async def test_config_store_empty_falls_through_to_env(self, tmp_path):
        """When ConfigStore returns empty, falls through to env var."""
        store = _make_credential_store(tmp_path)
        store.save_credentials(
            "resy",
            {"auth_token": "stale", "api_key": "key", "email": "a@b.com"},
        )
        manager = ResyAuthManager(store)

        new_creds = {
            "auth_token": "env_tok",
            "api_key": "new_key",
            "payment_methods": [],
        }

        mock_cs = AsyncMock()
        mock_cs.get = AsyncMock(return_value="")

        mock_settings = MagicMock()
        mock_settings.resy_password = "env-pw"

        with (
            patch.object(
                manager, "_is_token_valid", new_callable=AsyncMock
            ) as mock_valid,
            patch.object(
                manager, "authenticate", new_callable=AsyncMock
            ) as mock_auth,
            patch("src.server._config_store", mock_cs),
            patch("src.config.get_settings", return_value=mock_settings),
        ):
            mock_valid.return_value = False
            mock_auth.return_value = new_creds
            result = await manager.ensure_valid_token()

        assert result == "env_tok"
        mock_auth.assert_awaited_once_with("a@b.com", "env-pw")

    async def test_no_config_store_falls_through_to_env(self, tmp_path):
        """When _config_store is None, falls through to env var."""
        store = _make_credential_store(tmp_path)
        store.save_credentials(
            "resy",
            {"auth_token": "stale", "api_key": "key", "email": "a@b.com"},
        )
        manager = ResyAuthManager(store)

        new_creds = {
            "auth_token": "nocsenv_tok",
            "api_key": "new_key",
            "payment_methods": [],
        }
        mock_settings = MagicMock()
        mock_settings.resy_password = "env-pw"

        with (
            patch.object(
                manager, "_is_token_valid", new_callable=AsyncMock
            ) as mock_valid,
            patch.object(
                manager, "authenticate", new_callable=AsyncMock
            ) as mock_auth,
            patch("src.server._config_store", None),
            patch("src.config.get_settings", return_value=mock_settings),
        ):
            mock_valid.return_value = False
            mock_auth.return_value = new_creds
            result = await manager.ensure_valid_token()

        assert result == "nocsenv_tok"
        mock_auth.assert_awaited_once_with("a@b.com", "env-pw")

    async def test_env_var_password_used_for_refresh(self, tmp_path):
        """When password not in stored creds, env var RESY_PASSWORD is used."""
        store = _make_credential_store(tmp_path)
        store.save_credentials(
            "resy",
            {"auth_token": "stale", "api_key": "key", "email": "a@b.com"},
        )
        manager = ResyAuthManager(store)

        new_creds = {
            "auth_token": "refreshed_tok",
            "api_key": "new_key",
            "payment_methods": [],
        }
        mock_settings = MagicMock()
        mock_settings.resy_password = "env-pw"

        with (
            patch.object(
                manager, "_is_token_valid", new_callable=AsyncMock
            ) as mock_valid,
            patch.object(
                manager, "authenticate", new_callable=AsyncMock
            ) as mock_auth,
            patch("src.config.get_settings", return_value=mock_settings),
        ):
            mock_valid.return_value = False
            mock_auth.return_value = new_creds
            result = await manager.ensure_valid_token()

        assert result == "refreshed_tok"
        mock_auth.assert_awaited_once_with("a@b.com", "env-pw")

        # Verify refreshed creds do not contain password
        saved = store.get_credentials("resy")
        assert "password" not in saved
        assert saved["auth_token"] == "refreshed_tok"

    async def test_refreshed_creds_do_not_contain_password(self, tmp_path):
        """After token refresh, the saved blob must not contain a password."""
        store = _make_credential_store(tmp_path)
        store.save_credentials(
            "resy",
            {
                "auth_token": "old",
                "api_key": "key",
                "email": "a@b.com",
                "password": "legacy-pw",
            },
        )
        manager = ResyAuthManager(store)

        new_creds = {
            "auth_token": "new_tok",
            "api_key": "new_key",
            "payment_methods": [],
        }

        with (
            patch.object(
                manager, "_is_token_valid", new_callable=AsyncMock
            ) as mock_valid,
            patch.object(
                manager, "authenticate", new_callable=AsyncMock
            ) as mock_auth,
        ):
            mock_valid.return_value = False
            mock_auth.return_value = new_creds
            await manager.ensure_valid_token()

        saved = store.get_credentials("resy")
        assert "password" not in saved


# ── _is_token_valid ──────────────────────────────────────────────────────────


class TestIsTokenValid:
    """_is_token_valid: checks via lightweight API call."""

    async def test_returns_true_when_reservations_is_list(self, tmp_path):
        store = _make_credential_store(tmp_path)
        manager = ResyAuthManager(store)

        with patch("src.clients.resy_auth.ResyClient") as mock_cls:
            instance = mock_cls.return_value
            instance.get_user_reservations = AsyncMock(return_value=[])
            result = await manager._is_token_valid("tok", "key")

        assert result is True

    async def test_returns_false_when_exception_raised(self, tmp_path):
        store = _make_credential_store(tmp_path)
        manager = ResyAuthManager(store)

        with patch("src.clients.resy_auth.ResyClient") as mock_cls:
            instance = mock_cls.return_value
            instance.get_user_reservations = AsyncMock(
                side_effect=httpx.ConnectError("timeout")
            )
            result = await manager._is_token_valid("tok", "key")

        assert result is False

    async def test_returns_false_when_non_list_returned(self, tmp_path):
        """If the API returns something unexpected (not a list), invalid."""
        store = _make_credential_store(tmp_path)
        manager = ResyAuthManager(store)

        with patch("src.clients.resy_auth.ResyClient") as mock_cls:
            instance = mock_cls.return_value
            instance.get_user_reservations = AsyncMock(
                return_value="not a list"
            )
            result = await manager._is_token_valid("tok", "key")

        assert result is False
