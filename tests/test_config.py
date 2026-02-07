from pathlib import Path

import pytest

from src.config import Settings, get_settings, reset_settings


class TestSettings:
    """Test Settings class field defaults and computed properties."""

    def test_required_google_api_key(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "my-key-123")
        s = Settings()
        assert s.google_api_key == "my-key-123"

    def test_missing_google_api_key_raises(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        with pytest.raises(Exception):
            Settings()

    def test_optional_fields_default_none(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "k")
        s = Settings()
        assert s.openweather_api_key is None
        assert s.resy_email is None
        assert s.resy_password is None
        assert s.opentable_email is None
        assert s.opentable_password is None

    def test_optional_fields_from_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "k")
        monkeypatch.setenv("OPENWEATHER_API_KEY", "weather-key")
        monkeypatch.setenv("RESY_EMAIL", "resy@example.com")
        monkeypatch.setenv("RESY_PASSWORD", "secret")
        monkeypatch.setenv("OPENTABLE_EMAIL", "ot@example.com")
        monkeypatch.setenv("OPENTABLE_PASSWORD", "secret2")
        s = Settings()
        assert s.openweather_api_key == "weather-key"
        assert s.resy_email == "resy@example.com"
        assert s.resy_password == "secret"
        assert s.opentable_email == "ot@example.com"
        assert s.opentable_password == "secret2"

    def test_default_data_dir(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "k")
        s = Settings()
        assert s.data_dir == Path("./data")

    def test_custom_data_dir(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "k")
        monkeypatch.setenv("DATA_DIR", "/tmp/custom")
        s = Settings()
        assert s.data_dir == Path("/tmp/custom")

    def test_default_log_level(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "k")
        s = Settings()
        assert s.log_level == "INFO"

    def test_custom_log_level(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "k")
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        s = Settings()
        assert s.log_level == "DEBUG"

    def test_db_path_computed(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "k")
        monkeypatch.setenv("DATA_DIR", "/srv/data")
        s = Settings()
        assert s.db_path == Path("/srv/data/restaurant.db")

    def test_credentials_path_computed(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "k")
        monkeypatch.setenv("DATA_DIR", "/srv/data")
        s = Settings()
        assert s.credentials_path == Path("/srv/data/.credentials")


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
