import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from src.server import (
    _reset_config_store,
    _reset_db,
    app_lifespan,
    get_config_store,
    get_db,
    initialize,
    mcp,
    setup_logging,
)


class TestSetupLogging:
    """Test setup_logging configuration."""

    def setup_method(self):
        root = logging.getLogger()
        for handler in root.handlers[:]:
            root.removeHandler(handler)
            handler.close()

    def teardown_method(self):
        root = logging.getLogger()
        for handler in root.handlers[:]:
            root.removeHandler(handler)
            handler.close()

    def test_sets_root_logger_level(self, tmp_path):
        setup_logging("DEBUG", tmp_path)
        assert logging.getLogger().level == logging.DEBUG

    def test_creates_console_handler(self, tmp_path):
        setup_logging("INFO", tmp_path)
        root = logging.getLogger()
        stream_handlers = [h for h in root.handlers if type(h) is logging.StreamHandler]
        assert len(stream_handlers) == 1

    def test_creates_file_handler(self, tmp_path):
        setup_logging("INFO", tmp_path)
        root = logging.getLogger()
        file_handlers = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
        assert len(file_handlers) == 1

    def test_creates_log_directory(self, tmp_path):
        log_dir = tmp_path / "logs"
        assert not log_dir.exists()
        setup_logging("INFO", tmp_path)
        assert log_dir.exists()

    def test_log_file_path(self, tmp_path):
        setup_logging("INFO", tmp_path)
        root = logging.getLogger()
        file_handler = next(
            h for h in root.handlers if isinstance(h, RotatingFileHandler)
        )
        assert Path(file_handler.baseFilename) == tmp_path / "logs" / "server.log"

    def test_no_duplicate_handlers_on_second_call(self, tmp_path):
        setup_logging("INFO", tmp_path)
        setup_logging("INFO", tmp_path)
        root = logging.getLogger()
        stream_handlers = [h for h in root.handlers if type(h) is logging.StreamHandler]
        file_handlers = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
        assert len(stream_handlers) == 1
        assert len(file_handlers) == 1

    def test_invalid_log_level_falls_back_to_info(self, tmp_path):
        setup_logging("INVALID_LEVEL", tmp_path)
        assert logging.getLogger().level == logging.INFO


class TestInitialize:
    """Test the initialize function."""

    def setup_method(self):
        from src.config import reset_settings

        reset_settings()
        root = logging.getLogger()
        for handler in root.handlers[:]:
            root.removeHandler(handler)
            handler.close()

    def teardown_method(self):
        from src.config import reset_settings

        reset_settings()
        root = logging.getLogger()
        for handler in root.handlers[:]:
            root.removeHandler(handler)
            handler.close()

    def test_returns_mcp_instance(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        result = initialize()
        assert result is mcp

    def test_creates_data_dir(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "new_data"
        monkeypatch.setenv("DATA_DIR", str(data_dir))
        initialize()
        assert data_dir.exists()

    def test_creates_logs_subdir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        initialize()
        assert (tmp_path / "logs").exists()

    def test_configures_logging(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        initialize()
        root = logging.getLogger()
        assert any(isinstance(h, RotatingFileHandler) for h in root.handlers)


    def test_sets_auth_when_token_configured(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        monkeypatch.setenv("MCP_AUTH_TOKEN", "a" * 48)
        result = initialize()
        from src.auth import BearerTokenVerifier

        assert isinstance(result.auth, BearerTokenVerifier)

    def test_no_auth_without_token(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
        # Reset mcp.auth to a known state before test
        mcp.auth = None
        result = initialize()
        assert result.auth is None


class TestHealthCheck:
    """Test the /health custom route handler."""

    async def test_health_returns_ok(self):
        from src.server import health_check

        response = await health_check(None)
        assert response.status_code == 200
        assert response.body == b'{"status":"ok"}'


class TestAppLifespan:
    """Test the async database lifecycle."""

    def setup_method(self):
        from src.config import reset_settings

        reset_settings()
        _reset_db()
        _reset_config_store()

    def teardown_method(self):
        from src.config import reset_settings

        reset_settings()
        _reset_db()
        _reset_config_store()

    async def test_lifespan_initializes_and_closes_db(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        import src.server as server_module

        async with app_lifespan(mcp) as result:
            assert "db" in result
            assert result["db"] is not None
            assert server_module._db is not None

        assert server_module._db is None

    async def test_lifespan_creates_db_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        tmp_path.mkdir(parents=True, exist_ok=True)

        async with app_lifespan(mcp):
            assert (tmp_path / "restaurant.db").exists()

    async def test_lifespan_no_config_store_without_master_key(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        monkeypatch.delenv("RESTAURANT_MCP_KEY", raising=False)

        async with app_lifespan(mcp):
            assert get_config_store() is None

    async def test_lifespan_creates_config_store_with_master_key(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        monkeypatch.setenv("RESTAURANT_MCP_KEY", "test-master-key")

        async with app_lifespan(mcp):
            cs = get_config_store()
            assert cs is not None
            from src.storage.config_store import ConfigStore
            assert isinstance(cs, ConfigStore)

        # After lifespan exits, config_store should be None
        assert get_config_store() is None


class TestGetDb:
    """Test the get_db accessor."""

    def setup_method(self):
        _reset_db()

    def teardown_method(self):
        _reset_db()

    def test_get_db_raises_when_not_initialized(self):
        with pytest.raises(RuntimeError, match="Database not initialized"):
            get_db()

    async def test_get_db_returns_manager_during_lifespan(self, tmp_path, monkeypatch):
        from src.config import reset_settings

        reset_settings()
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        tmp_path.mkdir(parents=True, exist_ok=True)

        async with app_lifespan(mcp):
            db = get_db()
            assert db is not None
            assert db.connection is not None

        reset_settings()


class TestGetConfigStore:
    """Test the get_config_store accessor."""

    def setup_method(self):
        _reset_config_store()

    def teardown_method(self):
        _reset_config_store()

    def test_returns_none_when_not_initialized(self):
        assert get_config_store() is None


class TestResetDb:
    """Test the _reset_db helper."""

    def test_reset_db_clears_reference(self):
        import src.server as server_module

        server_module._db = "sentinel"  # type: ignore[assignment]
        _reset_db()
        assert server_module._db is None


class TestResetConfigStore:
    """Test the _reset_config_store helper."""

    def test_reset_config_store_clears_reference(self):
        import src.server as server_module

        server_module._config_store = "sentinel"  # type: ignore[assignment]
        _reset_config_store()
        assert server_module._config_store is None
