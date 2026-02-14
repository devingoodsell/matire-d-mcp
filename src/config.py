from pathlib import Path

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables and .env file.

    Two modes of operation:

    1. **Legacy (.env) mode** — ``GOOGLE_API_KEY`` is required as an env var.
    2. **Master-key mode** — set ``RESTAURANT_MCP_KEY`` and all API keys /
       credentials are loaded from the encrypted ``app_config`` table at
       runtime (``google_api_key`` may be empty at construction time).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Master key — when set, credentials come from the encrypted DB
    restaurant_mcp_key: str | None = None

    # Required in legacy mode, loaded from DB in master-key mode
    google_api_key: str = ""

    # Optional — weather-aware recommendations
    openweather_api_key: str | None = None

    # Optional — booking platform credentials (prefer env vars over chat input)
    resy_email: str | None = None
    resy_password: str | None = None
    opentable_email: str | None = None
    opentable_csrf_token: str | None = None
    opentable_cookies: str | None = None

    # Remote hosting — transport, bind address, and auth
    mcp_transport: str = "stdio"
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8000
    mcp_auth_token: str | None = None

    # Paths & logging — default is <project_root>/data so it works
    # regardless of the process working directory (Claude Desktop may
    # spawn the server from a read-only location).
    data_dir: Path = Path(__file__).resolve().parent.parent / "data"
    log_level: str = "INFO"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def db_path(self) -> Path:
        return self.data_dir / "restaurant.db"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def credentials_path(self) -> Path:
        return self.data_dir / ".credentials"

    @property
    def uses_master_key(self) -> bool:
        """Return True when running in master-key (encrypted DB) mode."""
        return bool(self.restaurant_mcp_key)


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the cached Settings singleton. Created on first call."""
    global _settings  # noqa: PLW0603
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Clear the cached settings. Used in tests."""
    global _settings  # noqa: PLW0603
    _settings = None
