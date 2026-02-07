import pytest

from src.storage.database import DatabaseManager


@pytest.fixture(autouse=True)
def _set_test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure required env vars are set for all tests."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")


@pytest.fixture
def tmp_data_dir(tmp_path):
    """Provide a temporary data directory for tests that touch the filesystem."""
    return tmp_path / "data"


@pytest.fixture
async def db():
    """In-memory SQLite database with schema applied."""
    manager = DatabaseManager(":memory:")
    await manager.initialize()
    yield manager
    await manager.close()
