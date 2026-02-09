"""Tests for the interactive setup CLI (src.setup)."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import aiosqlite

from src.setup import _generate_master_key, _prompt, _read_file_value, _run_setup, main
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


class TestReadFileValue:
    def test_reads_file_contents(self, tmp_path):
        f = tmp_path / "cookie.txt"
        f.write_text("  long-cookie-value  \n")
        assert _read_file_value(str(f)) == "long-cookie-value"

    def test_returns_empty_for_missing_file(self, capsys):
        result = _read_file_value("/nonexistent/file.txt")
        assert result == ""
        captured = capsys.readouterr()
        assert "File not found" in captured.out

    def test_expands_tilde(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        f = tmp_path / "val.txt"
        f.write_text("home-value")
        assert _read_file_value("~/val.txt") == "home-value"


class TestPromptFileInput:
    def test_at_prefix_reads_from_file(self, tmp_path):
        f = tmp_path / "token.txt"
        f.write_text("file-token-value")
        with patch("builtins.input", return_value=f"@{f}"):
            result = _prompt("Token")
        assert result == "file-token-value"

    def test_at_prefix_missing_file_reprompts(self, tmp_path, capsys):
        good_file = tmp_path / "good.txt"
        good_file.write_text("ok")
        with patch("builtins.input", side_effect=["@/bad/path.txt", f"@{good_file}"]):
            result = _prompt("Token")
        assert result == "ok"

    def test_at_prefix_optional_missing_file_returns_empty(self):
        with patch("builtins.input", return_value="@/nonexistent.txt"):
            result = _prompt("Token", required=False)
        assert result == ""


class TestRunSetup:
    async def test_creates_db_and_stores_credentials(self, tmp_path):
        data_dir = tmp_path / "data"
        secret_inputs = iter([
            "test-google-key",     # google api key
            "test-weather-key",    # openweather api key
            "resy-pw",             # resy password
        ])
        text_inputs = iter([
            "resy@test.com",       # resy email
            "csrf-token-abc",      # opentable csrf token
            "session=xyz123",      # opentable cookies
            "ot@test.com",         # opentable email
        ])

        with (
            patch("getpass.getpass", side_effect=lambda _: next(secret_inputs)),
            patch("builtins.input", side_effect=lambda _: next(text_inputs)),
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
            assert await store.get("opentable_csrf_token") == "csrf-token-abc"
            assert await store.get("opentable_cookies") == "session=xyz123"
            assert await store.get("opentable_email") == "ot@test.com"

    async def test_optional_fields_skipped(self, tmp_path):
        data_dir = tmp_path / "data"
        secret_inputs = iter([
            "test-google-key",  # google api key
            "",                 # openweather — skip
        ])
        text_inputs = iter([
            "",                 # resy email — skip
            "",                 # opentable csrf token — skip
        ])

        with (
            patch("getpass.getpass", side_effect=lambda _: next(secret_inputs)),
            patch("builtins.input", side_effect=lambda _: next(text_inputs)),
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
            assert await store.has("opentable_csrf_token") is False
            assert await store.has("opentable_cookies") is False
            assert await store.has("opentable_email") is False

    async def test_prints_claude_config(self, tmp_path, capsys):
        data_dir = tmp_path / "data"
        secret_inputs = iter([
            "test-google-key",
            "",   # skip weather
        ])
        text_inputs = iter([
            "",   # skip resy
            "",   # skip opentable csrf
        ])

        with (
            patch("getpass.getpass", side_effect=lambda _: next(secret_inputs)),
            patch("builtins.input", side_effect=lambda _: next(text_inputs)),
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
