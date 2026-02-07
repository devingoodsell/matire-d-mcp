# EPIC-01: Project Foundation & MCP Server Skeleton

## Goal
Stand up the project structure, dependency management, FastMCP server entry point, and Claude Desktop integration so that a bare MCP server starts and responds to Claude.

## Success Criteria
- `python -m src.server` launches a working FastMCP server
- Claude Desktop can connect and see at least one placeholder tool
- All configuration is driven by environment variables with sane defaults
- Project installs cleanly via `pip install -e .`

---

## Story 1.1: Project Structure & Dependency Management

**As a** developer
**I want** a clean Python project skeleton with all dependencies declared
**So that** I can install and develop locally with a single command

### Tasks

- [ ] **1.1.1** Create project directory structure (the full canonical structure is in `.ai/ENGINEERING-STANDARDS.md` Section 1):
  ```
  restaurant-mcp/
  ├── .ai/                     # Already exists — agent instructions & standards
  │   ├── AGENTS.md
  │   └── ENGINEERING-STANDARDS.md
  ├── docs/                    # Already exists — specs & ADRs
  │   ├── specs/
  │   └── adr/
  ├── scripts/                 # Already exists — validation scripts
  │   ├── validate.sh
  │   ├── test.sh
  │   └── lint.sh
  ├── src/
  │   ├── __init__.py
  │   ├── __main__.py
  │   ├── server.py
  │   ├── config.py
  │   ├── tools/
  │   │   └── __init__.py
  │   ├── clients/
  │   │   └── __init__.py
  │   ├── storage/
  │   │   └── __init__.py
  │   ├── matching/
  │   │   └── __init__.py
  │   └── models/
  │       └── __init__.py
  ├── tests/
  │   ├── __init__.py
  │   ├── conftest.py
  │   └── fixtures/
  ├── data/
  │   └── .gitkeep
  ├── pyproject.toml
  ├── .env.example
  ├── .gitignore
  └── README.md
  ```

- [ ] **1.1.2** Create `pyproject.toml` with dependencies:
  ```toml
  [project]
  name = "restaurant-mcp"
  version = "0.1.0"
  requires-python = ">=3.11"
  dependencies = [
      "fastmcp>=2.0.0",
      "httpx>=0.25.0",
      "aiosqlite>=0.19.0",
      "pydantic>=2.0.0",
      "pydantic-settings>=2.0.0",
      "python-dotenv>=1.0.0",
      "playwright>=1.40.0",
      "cryptography>=41.0.0",
      "tenacity>=8.0.0",
  ]

  [project.optional-dependencies]
  dev = [
      "pytest>=7.0.0",
      "pytest-asyncio>=0.21.0",
      "pytest-cov>=4.0.0",
      "ruff>=0.1.0",
  ]
  ```

- [ ] **1.1.3** Create `.gitignore` covering: `data/restaurant.db`, `data/.credentials`, `data/logs/`, `.env`, `__pycache__`, `*.egg-info`, `venv/`, `.playwright/`

- [ ] **1.1.4** Create `.env.example` with all required/optional env vars documented:
  ```bash
  # Required
  GOOGLE_API_KEY=           # Google Cloud Console → Places API (New)

  # Optional - for weather-aware recommendations
  OPENWEATHER_API_KEY=      # openweathermap.org (free tier: 1000/day)

  # Optional - Resy credentials (can be set up via MCP tool)
  RESY_EMAIL=
  RESY_PASSWORD=

  # Optional - OpenTable credentials
  OPENTABLE_EMAIL=
  OPENTABLE_PASSWORD=

  # Paths
  DATA_DIR=./data           # SQLite DB and credentials location
  LOG_LEVEL=INFO
  ```

---

## Story 1.2: Configuration Management

**As a** developer
**I want** centralized, validated configuration from environment variables
**So that** all components pull from a single source of truth

### Tasks

- [ ] **1.2.1** Create `src/config.py` using `pydantic-settings.BaseSettings`:
  - `google_api_key: str` (required)
  - `openweather_api_key: str | None = None`
  - `resy_email: str | None = None`
  - `resy_password: str | None = None`
  - `opentable_email: str | None = None`
  - `opentable_password: str | None = None`
  - `data_dir: Path = Path("./data")`
  - `log_level: str = "INFO"`
  - `db_path` property that returns `data_dir / "restaurant.db"`
  - `credentials_path` property that returns `data_dir / ".credentials"`
  - Load from `.env` file via `model_config = SettingsConfigDict(env_file=".env")`

- [ ] **1.2.2** Add a module-level singleton: `settings = Settings()` with lazy initialization

---

## Story 1.3: FastMCP Server Entry Point

**As a** user
**I want** the MCP server to start and register with Claude Desktop
**So that** I can interact with restaurant tools through Claude

### Tasks

- [ ] **1.3.1** Create `src/server.py`:
  - Instantiate `FastMCP("restaurant-assistant")` server
  - Import and register tool modules (start with a `ping` placeholder)
  - Add `if __name__ == "__main__": mcp.run()` entry point
  - Ensure `python -m src.server` works (add `__main__.py` if needed)

- [ ] **1.3.2** Create a placeholder tool in `src/tools/search.py`:
  ```python
  @mcp.tool()
  async def search_restaurants(query: str) -> str:
      """Search for restaurants. (Placeholder — full implementation in EPIC-04)"""
      return f"Search not yet implemented. Query: {query}"
  ```

- [ ] **1.3.3** Set up logging configuration:
  - Use Python `logging` module
  - Log to `data/logs/server.log` with rotation (5MB, 3 backups)
  - Console output at configured log level
  - Log all MCP tool invocations with arguments (redact passwords)

---

## Story 1.4: Claude Desktop Integration

**As a** user
**I want** to add this server to Claude Desktop with minimal effort
**So that** I can start chatting with my restaurant assistant

### Tasks

- [ ] **1.4.1** Document the Claude Desktop config snippet in README:
  ```json
  {
    "mcpServers": {
      "restaurant": {
        "command": "python",
        "args": ["-m", "src.server"],
        "cwd": "/path/to/restaurant-mcp",
        "env": {
          "GOOGLE_API_KEY": "your_key"
        }
      }
    }
  }
  ```

- [ ] **1.4.2** Verify the server starts without errors when no optional env vars are set (Google API key is the only required key)

- [ ] **1.4.3** Create `data/` directory automatically on first run if it doesn't exist (in `server.py` startup)

---

## Dependencies
- None (this is the foundation EPIC)

## Blocked By
- Nothing

## Blocks
- EPIC-02 (Data Layer needs project structure)
- EPIC-03 through EPIC-08 (all need the server running)

## Cost Considerations
- No API costs in this EPIC
- Playwright is only needed at runtime for auth; install via `playwright install chromium` (one-time ~200MB download)

## Technical Notes
- FastMCP v2+ uses `mcp.run()` which handles stdio transport for Claude Desktop
- The server must be importable as a module (`python -m src.server`) — this is how Claude Desktop launches it
- All tools will be registered on the shared `mcp` instance imported from `server.py`
- The `.ai/`, `docs/`, and `scripts/` directories already exist before this EPIC — they are part of the repo scaffolding, not created by EPIC-01
- After completing this EPIC, run `./scripts/validate.sh` to verify everything passes
- Refer to `.ai/ENGINEERING-STANDARDS.md` for all code patterns and testing requirements
