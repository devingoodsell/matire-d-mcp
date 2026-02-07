from pathlib import Path

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Required
    google_api_key: str

    # Optional — weather-aware recommendations
    openweather_api_key: str | None = None

    # Optional — Resy credentials (can be set up via MCP tool)
    resy_email: str | None = None
    resy_password: str | None = None

    # Optional — OpenTable credentials
    opentable_email: str | None = None
    opentable_password: str | None = None

    # Paths & logging
    data_dir: Path = Path("./data")
    log_level: str = "INFO"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def db_path(self) -> Path:
        return self.data_dir / "restaurant.db"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def credentials_path(self) -> Path:
        return self.data_dir / ".credentials"


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
