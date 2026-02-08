from pathlib import Path

import pytest

from src.config import Settings, get_settings, reset_settings


class TestSettings:
    """Test Settings class field defaults and computed properties."""

    def test_default_google_api_key_empty(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        s = Settings(_env_file=None)
        assert s.google_api_key == ""

    def test_google_api_key_from_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "my-key-123")
        s = Settings(_env_file=None)
        assert s.google_api_key == "my-key-123"

    def test_optional_fields_default_none(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("OPENWEATHER_API_KEY", raising=False)
        s = Settings(_env_file=None)
        assert s.openweather_api_key is None

    def test_optional_fields_from_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENWEATHER_API_KEY", "weather-key")
        s = Settings(_env_file=None)
        assert s.openweather_api_key == "weather-key"

    def test_credential_fields_default_none(self, monkeypatch: pytest.MonkeyPatch):
        s = Settings(_env_file=None)
        assert s.resy_email is None
        assert s.resy_password is None
        assert s.opentable_email is None
        assert s.opentable_csrf_token is None
        assert s.opentable_cookies is None

    def test_credential_fields_from_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("RESY_EMAIL", "resy@test.com")
        monkeypatch.setenv("RESY_PASSWORD", "resy-pw")
        monkeypatch.setenv("OPENTABLE_EMAIL", "ot@test.com")
        monkeypatch.setenv("OPENTABLE_CSRF_TOKEN", "csrf-abc")
        monkeypatch.setenv("OPENTABLE_COOKIES", "sid=xyz")
        s = Settings(_env_file=None)
        assert s.resy_email == "resy@test.com"
        assert s.resy_password == "resy-pw"
        assert s.opentable_email == "ot@test.com"
        assert s.opentable_csrf_token == "csrf-abc"
        assert s.opentable_cookies == "sid=xyz"

    def test_default_data_dir(self, monkeypatch: pytest.MonkeyPatch):
        s = Settings()
        # Default is project-relative (not CWD-relative) so the MCP server
        # works even when Claude Desktop spawns it from a read-only directory.
        expected = Path(__file__).resolve().parent.parent / "data"
        assert s.data_dir == expected

    def test_custom_data_dir(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("DATA_DIR", "/tmp/custom")
        s = Settings()
        assert s.data_dir == Path("/tmp/custom")

    def test_default_log_level(self, monkeypatch: pytest.MonkeyPatch):
        s = Settings()
        assert s.log_level == "INFO"

    def test_custom_log_level(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        s = Settings()
        assert s.log_level == "DEBUG"

    def test_db_path_computed(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("DATA_DIR", "/srv/data")
        s = Settings()
        assert s.db_path == Path("/srv/data/restaurant.db")

    def test_credentials_path_computed(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("DATA_DIR", "/srv/data")
        s = Settings()
        assert s.credentials_path == Path("/srv/data/.credentials")


class TestMasterKey:
    """Test master-key mode settings."""

    def test_restaurant_mcp_key_default_none(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("RESTAURANT_MCP_KEY", raising=False)
        s = Settings(_env_file=None)
        assert s.restaurant_mcp_key is None

    def test_restaurant_mcp_key_from_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("RESTAURANT_MCP_KEY", "test-master-key")
        s = Settings(_env_file=None)
        assert s.restaurant_mcp_key == "test-master-key"

    def test_uses_master_key_false_when_not_set(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("RESTAURANT_MCP_KEY", raising=False)
        s = Settings(_env_file=None)
        assert s.uses_master_key is False

    def test_uses_master_key_true_when_set(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("RESTAURANT_MCP_KEY", "some-key")
        s = Settings(_env_file=None)
        assert s.uses_master_key is True

    def test_uses_master_key_false_for_empty_string(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("RESTAURANT_MCP_KEY", "")
        s = Settings(_env_file=None)
        assert s.uses_master_key is False


class TestGetSettings:
    """Test the lazy singleton get_settings / reset_settings."""

    def setup_method(self):
        reset_settings()

    def teardown_method(self):
        reset_settings()

    def test_get_settings_returns_settings(self):
        s = get_settings()
        assert isinstance(s, Settings)
        assert s.google_api_key == "test-google-key"

    def test_get_settings_is_singleton(self):
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_reset_settings_clears_cache(self):
        s1 = get_settings()
        reset_settings()
        s2 = get_settings()
        assert s1 is not s2
