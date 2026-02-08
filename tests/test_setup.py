"""Tests for the interactive setup CLI (src.setup)."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import aiosqlite

from src.setup import _generate_master_key, _prompt, _run_setup, main
from src.storage.config_store import ConfigStore, derive_fernet_key


class TestGenerateMasterKey:
    def test_returns_base64_string(self):
        key = _generate_master_key()
        assert isinstance(key, str)
        assert len(key) > 20  # base64 of 32 bytes ≈ 44 chars

    def test_unique_each_call(self):
        k1 = _generate_master_key()
        k2 = _generate_master_key()
        assert k1 != k2

    def test_can_derive_fernet_key(self):
        """Generated master key must work with derive_fernet_key."""
        master = _generate_master_key()
        fernet_key = derive_fernet_key(master)
        from cryptography.fernet import Fernet

        Fernet(fernet_key)  # must not raise


class TestPrompt:
    def test_returns_input_value(self):
        with patch("builtins.input", return_value="my-value"):
            result = _prompt("Label")
        assert result == "my-value"

    def test_strips_whitespace(self):
        with patch("builtins.input", return_value="  spaced  "):
            result = _prompt("Label")
        assert result == "spaced"

    def test_optional_accepts_empty(self):
        with patch("builtins.input", return_value=""):
            result = _prompt("Label", required=False)
        assert result == ""

    def test_required_reprompts_on_empty(self):
        with patch("builtins.input", side_effect=["", "", "finally"]):
            result = _prompt("Label")
        assert result == "finally"

    def test_secret_uses_getpass(self):
        with patch("getpass.getpass", return_value="secret-pw"):
            result = _prompt("Password", secret=True)
        assert result == "secret-pw"


class TestRunSetup:
    async def test_creates_db_and_stores_credentials(self, tmp_path):
        data_dir = tmp_path / "data"
        inputs = iter([
            "test-google-key",     # google api key
            "test-weather-key",    # openweather api key
            "resy@test.com",       # resy email
            "resy-pw",             # resy password
            "ot@test.com",         # opentable email
            "ot-pw",               # opentable password
        ])

        with (
            patch("getpass.getpass", side_effect=lambda _: next(inputs)),
            patch("builtins.input", side_effect=lambda _: next(inputs)),
            patch("builtins.print"),
            patch("src.setup._generate_master_key", return_value="fixed-master-key"),
        ):
            await _run_setup(data_dir)

        # DB file should exist
        db_path = data_dir / "restaurant.db"
        assert db_path.exists()

        # Verify encrypted values
        async with aiosqlite.connect(str(db_path)) as conn:
            store = ConfigStore(conn, "fixed-master-key")
            assert await store.get("google_api_key") == "test-google-key"
            assert await store.get("openweather_api_key") == "test-weather-key"
            assert await store.get("resy_email") == "resy@test.com"
            assert await store.get("resy_password") == "resy-pw"
            assert await store.get("opentable_email") == "ot@test.com"
            assert await store.get("opentable_password") == "ot-pw"

    async def test_optional_fields_skipped(self, tmp_path):
        data_dir = tmp_path / "data"
        inputs = iter([
            "test-google-key",  # google api key (secret)
            "",                 # openweather (optional, secret) — skip
            "",                 # resy email (optional, input) — skip
            "",                 # opentable email (optional, input) — skip
        ])

        with (
            patch("getpass.getpass", side_effect=lambda _: next(inputs)),
            patch("builtins.input", side_effect=lambda _: next(inputs)),
            patch("builtins.print"),
            patch("src.setup._generate_master_key", return_value="fixed-key"),
        ):
            await _run_setup(data_dir)

        db_path = data_dir / "restaurant.db"
        async with aiosqlite.connect(str(db_path)) as conn:
            store = ConfigStore(conn, "fixed-key")
            assert await store.get("google_api_key") == "test-google-key"
            assert await store.has("openweather_api_key") is False
            assert await store.has("resy_email") is False
            assert await store.has("resy_password") is False
            assert await store.has("opentable_email") is False
            assert await store.has("opentable_password") is False

    async def test_prints_claude_config(self, tmp_path, capsys):
        data_dir = tmp_path / "data"
        inputs = iter([
            "test-google-key",
            "",   # skip weather
            "",   # skip resy
            "",   # skip opentable
        ])

        with (
            patch("getpass.getpass", side_effect=lambda _: next(inputs)),
            patch("builtins.input", side_effect=lambda _: next(inputs)),
            patch("src.setup._generate_master_key", return_value="test-master"),
        ):
            await _run_setup(data_dir)

        captured = capsys.readouterr()
        assert "RESTAURANT_MCP_KEY" in captured.out
        assert "test-master" in captured.out
        assert "mcpServers" in captured.out


class TestMain:
    def test_main_calls_run_setup(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RESTAURANT_MCP_DATA_DIR", str(tmp_path / "data"))
        mock_run = AsyncMock()
        with patch("src.setup._run_setup", mock_run):
            main()
        mock_run.assert_awaited_once()
        # Verify it was called with the correct data dir
        call_args = mock_run.call_args[0]
        assert call_args[0] == Path(str(tmp_path / "data"))

    def test_main_defaults_to_data_dir(self, monkeypatch):
        monkeypatch.delenv("RESTAURANT_MCP_DATA_DIR", raising=False)
        mock_run = AsyncMock()
        with patch("src.setup._run_setup", mock_run):
            main()
        call_args = mock_run.call_args[0]
        assert call_args[0] == Path("./data")  # setup uses RESTAURANT_MCP_DATA_DIR default
