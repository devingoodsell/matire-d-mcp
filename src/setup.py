"""Interactive setup CLI: ``python -m src.setup``

Prompts for API keys and booking credentials, encrypts them into the
SQLite database, and prints the Claude Desktop config snippet.
"""

import asyncio
import base64
import getpass
import json
import os
from pathlib import Path

import aiosqlite

from src.storage.config_store import ConfigStore, derive_fernet_key  # noqa: F401


def _read_file_value(path_str: str) -> str:
    """Read a value from a file path (strips whitespace)."""
    p = Path(path_str).expanduser()
    if not p.is_file():
        print(f"  File not found: {p}")
        return ""
    return p.read_text().strip()


def _prompt(label: str, *, secret: bool = False, required: bool = True) -> str:
    """Prompt the user for input (optionally hidden).

    Values prefixed with ``@`` are treated as file paths — the file
    contents are read and used as the value.  This is useful for long
    values (e.g. cookie headers) that exceed the terminal line buffer.
    """
    suffix = "" if required else " (optional, press Enter to skip)"
    prompt_text = f"{label}{suffix}: "
    while True:
        value = getpass.getpass(prompt_text) if secret else input(prompt_text)
        value = value.strip()
        if value.startswith("@"):
            value = _read_file_value(value[1:])
        if value or not required:
            return value
        print(f"  {label} is required.")


def _generate_master_key() -> str:
    """Generate a random 32-byte master key, base64-encoded."""
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


async def _run_setup(data_dir: Path) -> None:
    """Core async setup logic."""
    print()
    print("Restaurant MCP — Setup")
    print("=" * 40)
    print()

    # ── Collect credentials ──────────────────────────────────────────
    google_key = _prompt("Google API Key", secret=True)
    weather_key = _prompt("OpenWeather API Key", secret=True, required=False)

    print()
    resy_email = _prompt("Resy email", required=False)
    resy_password = ""
    if resy_email:
        resy_password = _prompt("Resy password", secret=True)

    print()
    print("  OpenTable requires browser session cookies for API access.")
    print("  To get them: log in at opentable.com, open DevTools (F12),")
    print("  Network tab, find any POST to /dapi/ and copy the")
    print("  x-csrf-token header, then copy the Cookie header from any")
    print("  request to www.opentable.com.")
    print()
    print("  Tip: For long values, save to a file and enter @path/to/file")
    print()
    ot_csrf = _prompt("OpenTable x-csrf-token", required=False)
    ot_cookies = ""
    ot_email = ""
    if ot_csrf:
        ot_cookies = _prompt("OpenTable Cookie header (or @path/to/file)", required=False)
        ot_email = _prompt("OpenTable email (for booking contact info)", required=False)

    # ── Generate master key ──────────────────────────────────────────
    master_key = _generate_master_key()

    # ── Ensure data directory and DB exist ───────────────────────────
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "restaurant.db"

    schema_path = Path(__file__).parent / "storage" / "schema.sql"
    schema_sql = schema_path.read_text()

    async with aiosqlite.connect(str(db_path)) as conn:
        await conn.executescript(schema_sql)
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA foreign_keys=ON")
        await conn.commit()

        store = ConfigStore(conn, master_key)

        await store.set("google_api_key", google_key)
        if weather_key:
            await store.set("openweather_api_key", weather_key)
        if resy_email:
            await store.set("resy_email", resy_email)
        if resy_password:
            await store.set("resy_password", resy_password)
        if ot_email:
            await store.set("opentable_email", ot_email)
        if ot_csrf:
            await store.set("opentable_csrf_token", ot_csrf)
        if ot_cookies:
            await store.set("opentable_cookies", ot_cookies)

    print()
    print("All credentials encrypted and stored in", db_path)
    print()

    # ── Print Claude Desktop config ──────────────────────────────────
    project_dir = Path(__file__).resolve().parent.parent
    venv_python = project_dir / ".venv" / "bin" / "python"

    config = {
        "mcpServers": {
            "restaurant": {
                "command": str(venv_python),
                "args": ["-m", "src"],
                "cwd": str(project_dir),
                "env": {
                    "RESTAURANT_MCP_KEY": master_key,
                },
            }
        }
    }

    print("Add this to your Claude Desktop config:")
    print()
    print(json.dumps(config, indent=2))
    print()


def main() -> None:
    """Entry point for ``python -m src.setup``."""
    data_dir = Path(os.environ.get("RESTAURANT_MCP_DATA_DIR", "./data"))
    asyncio.run(_run_setup(data_dir))


if __name__ == "__main__":  # pragma: no cover
    main()
