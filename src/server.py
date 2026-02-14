import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastmcp import FastMCP

from src.storage.config_store import ConfigStore
from src.storage.database import DatabaseManager

logger = logging.getLogger(__name__)

_db: DatabaseManager | None = None
_config_store: ConfigStore | None = None


def get_db() -> DatabaseManager:
    """Get the current DatabaseManager instance. Raises if not initialized."""
    if _db is None:
        raise RuntimeError("Database not initialized. Server lifespan has not started.")
    return _db


def get_config_store() -> ConfigStore | None:
    """Return the ConfigStore if running in master-key mode, else ``None``."""
    return _config_store


def _reset_db() -> None:
    """Clear the module-level DB reference. Used in tests."""
    global _db  # noqa: PLW0603
    _db = None


def _reset_config_store() -> None:
    """Clear the module-level ConfigStore reference. Used in tests."""
    global _config_store  # noqa: PLW0603
    _config_store = None


async def resolve_credential(key: str) -> str | None:
    """Look up a credential from ConfigStore (master-key mode), falling back to Settings.

    Used by all tool modules that need API keys or passwords that may be
    stored in the encrypted database.
    """
    if _config_store is not None:
        value = await _config_store.get(key)
        if value:
            return value

    from src.config import get_settings

    return getattr(get_settings(), key, None)


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[dict]:
    """Manage async resources (database) for the server lifecycle."""
    global _db, _config_store  # noqa: PLW0603
    from src.config import get_settings

    settings = get_settings()
    _db = DatabaseManager(settings.db_path)
    await _db.initialize()
    logger.info("Database initialized")

    # Master-key mode: initialise ConfigStore so tools can read encrypted config
    if settings.uses_master_key and _db.connection is not None:
        _config_store = ConfigStore(_db.connection, settings.restaurant_mcp_key)  # type: ignore[arg-type]
        logger.info("ConfigStore initialized (master-key mode)")

    try:
        yield {"db": _db}
    finally:
        _config_store = None
        await _db.close()
        _db = None
        logger.info("Database closed")


mcp = FastMCP("restaurant-assistant", lifespan=app_lifespan)


def setup_logging(log_level: str, data_dir: Path) -> None:
    """Configure logging with file rotation and console output.

    Args:
        log_level: Logging level string (DEBUG, INFO, WARNING, ERROR).
        data_dir: Base data directory — logs go to data_dir/logs/server.log.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler — exact type check avoids matching subclasses (FileHandler, etc.)
    if not any(type(h) is logging.StreamHandler for h in root_logger.handlers):
        console = logging.StreamHandler()
        console.setLevel(level)
        console.setFormatter(formatter)
        root_logger.addHandler(console)

    # File handler with rotation
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "server.log"

    if not any(isinstance(h, RotatingFileHandler) for h in root_logger.handlers):
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=5 * 1024 * 1024,  # 5 MB
            backupCount=3,
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)


def initialize() -> FastMCP:
    """Set up directories, logging, and register tools. Returns the MCP server."""
    from src.config import get_settings

    settings = get_settings()

    # Ensure runtime directories exist
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "logs").mkdir(exist_ok=True)

    # Logging
    setup_logging(settings.log_level, settings.data_dir)

    # Register tools
    from src.tools.blacklist import register_blacklist_tools
    from src.tools.booking import register_booking_tools
    from src.tools.costs import register_cost_tools
    from src.tools.groups import register_group_tools
    from src.tools.history import register_history_tools
    from src.tools.people import register_people_tools
    from src.tools.preferences import register_preference_tools
    from src.tools.recommendations import register_recommendation_tools
    from src.tools.search import register_search_tools

    register_search_tools(mcp)
    register_preference_tools(mcp)
    register_people_tools(mcp)
    register_group_tools(mcp)
    register_blacklist_tools(mcp)

    from src.tools.wishlist import register_wishlist_tools

    register_wishlist_tools(mcp)
    register_booking_tools(mcp)
    register_history_tools(mcp)
    register_recommendation_tools(mcp)
    register_cost_tools(mcp)

    logger.info("Restaurant MCP server initialized")
    return mcp
