# Engineering Standards & Implementation Guide

> **This document is mandatory reading before implementing any EPIC.**
> Every file written, every function defined, and every test created must conform to these standards. When in doubt, refer back here. Consistency across EPICs is non-negotiable — this codebase should read as if a single author wrote it.

---

## Table of Contents

1. [File System Architecture](#1-file-system-architecture)
2. [Module Boundaries & Dependency Rules](#2-module-boundaries--dependency-rules)
3. [Naming Conventions](#3-naming-conventions)
4. [Python Patterns & Style](#4-python-patterns--style)
5. [Async Patterns](#5-async-patterns)
6. [Pydantic Models](#6-pydantic-models)
7. [Database Patterns](#7-database-patterns)
8. [MCP Tool Patterns](#8-mcp-tool-patterns)
9. [API Client Patterns](#9-api-client-patterns)
10. [Error Handling](#10-error-handling)
11. [Logging](#11-logging)
12. [Configuration](#12-configuration)
13. [Testing Requirements](#13-testing-requirements)
14. [Reuse & DRY Principles](#14-reuse--dry-principles)

---

## 1. File System Architecture

### Directory Structure (Canonical)

```
restaurant-mcp/
├── .ai/
│   ├── AGENTS.md                    # Primary agent instructions — read first
│   └── ENGINEERING-STANDARDS.md     # THIS FILE — code patterns, architecture, testing
│
├── docs/
│   ├── specs/                       # Feature specifications & EPICs
│   │   ├── ARCHITECTURE_PLAN.md     # High-level architecture, API landscape, data models
│   │   ├── EPICS-INDEX.md           # Master EPIC guide — dependency graph, tool inventory
│   │   ├── EPIC-01-PROJECT-FOUNDATION.md
│   │   ├── EPIC-02-DATA-LAYER.md
│   │   ├── EPIC-03-USER-PREFERENCES.md
│   │   ├── EPIC-04-RESTAURANT-DISCOVERY.md
│   │   ├── EPIC-05-RESY-INTEGRATION.md
│   │   ├── EPIC-06-OPENTABLE-INTEGRATION.md
│   │   ├── EPIC-07-INTELLIGENCE-LAYER.md
│   │   ├── EPIC-08-RESILIENCE-AND-PRODUCTION.md
│   │   └── RESEARCH.md              # Background research on APIs, ecosystem, legal
│   └── adr/                         # Architecture Decision Records (context on "why")
│       └── ADR-NNN-slug.md          # One file per decision (see .ai/AGENTS.md for template)
│
├── scripts/                         # Agent feedback-loop scripts
│   ├── validate.sh                  # Full pipeline: lint + typecheck + test + coverage
│   ├── test.sh                      # Run tests with coverage
│   └── lint.sh                      # Ruff linting only
│
├── src/
│   ├── __init__.py                  # Package marker only — no logic
│   ├── __main__.py                  # Entry: from src.server import mcp; mcp.run()
│   ├── server.py                    # FastMCP instance creation, tool registration, lifecycle
│   ├── config.py                    # pydantic-settings: all env vars, paths, defaults
│   │
│   ├── models/                      # Pydantic models — pure data, no I/O, no side effects
│   │   ├── __init__.py              # Re-export all public models
│   │   ├── enums.py                 # Shared enumerations (Cuisine, PriceLevel, etc.)
│   │   ├── restaurant.py            # Restaurant, TimeSlot, AvailabilityResult
│   │   ├── user.py                  # UserPreferences, Person, Group, Location
│   │   ├── reservation.py           # Reservation, BookingResult
│   │   └── review.py                # Visit, VisitReview, DishReview
│   │
│   ├── storage/                     # Data persistence — SQLite and encrypted credentials
│   │   ├── __init__.py
│   │   ├── database.py              # DatabaseManager: async SQLite connection + repository methods
│   │   ├── schema.sql               # Full DDL — executed on first run
│   │   └── credentials.py           # CredentialStore: Fernet-encrypted credential files
│   │
│   ├── clients/                     # External API integrations — HTTP and browser
│   │   ├── __init__.py
│   │   ├── base.py                  # BaseAPIClient: shared httpx setup, response classification, logging
│   │   ├── google_places.py         # GooglePlacesClient(BaseAPIClient)
│   │   ├── cuisine_mapper.py        # Pure function: Google types → Cuisine enum
│   │   ├── resy.py                  # ResyClient(BaseAPIClient)
│   │   ├── resy_auth.py             # ResyAuthManager: API login + Playwright fallback
│   │   ├── opentable.py             # OpenTableClient: Playwright-based
│   │   ├── weather.py               # WeatherClient(BaseAPIClient)
│   │   ├── calendar.py              # CalendarClient: Google Calendar URL generation
│   │   ├── cache.py                 # InMemoryCache: TTL-based LRU
│   │   └── resilience.py            # Retry decorators, circuit breakers, exception hierarchy
│   │
│   ├── matching/                    # Cross-platform identity resolution
│   │   ├── __init__.py
│   │   └── venue_matcher.py         # VenueMatcher: Google Place ID → Resy/OpenTable ID
│   │
│   └── tools/                       # MCP tool definitions — orchestration layer
│       ├── __init__.py
│       ├── preferences.py           # setup_preferences, get_my_preferences, update_preferences
│       ├── people.py                # manage_person, list_people, manage_group, list_groups, manage_blacklist
│       ├── search.py                # search_restaurants
│       ├── booking.py               # check_availability, make_reservation, cancel_reservation, my_reservations,
│       │                            # store_resy_credentials, store_opentable_credentials
│       ├── history.py               # log_visit, rate_visit, visit_history
│       ├── recommendations.py       # get_recommendations, search_for_group
│       ├── date_utils.py            # parse_date, parse_time — shared helpers
│       └── error_messages.py        # User-facing error message templates
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py                  # Shared fixtures: in-memory DB, mock clients, sample data
│   ├── factories.py                 # Test data factories for all models
│   ├── fixtures/                    # Sample API response JSON files
│   │   ├── resy_find_response.json
│   │   ├── resy_details_response.json
│   │   ├── resy_book_response.json
│   │   ├── google_places_search_response.json
│   │   ├── google_places_detail_response.json
│   │   ├── openweather_current_response.json
│   │   └── openweather_forecast_response.json
│   │
│   ├── models/                      # Model validation tests
│   │   ├── test_enums.py
│   │   ├── test_restaurant.py
│   │   ├── test_user.py
│   │   ├── test_reservation.py
│   │   └── test_review.py
│   │
│   ├── storage/                     # Database and credential tests
│   │   ├── test_database.py
│   │   └── test_credentials.py
│   │
│   ├── clients/                     # API client tests (mocked HTTP)
│   │   ├── test_google_places.py
│   │   ├── test_resy.py
│   │   ├── test_resy_auth.py
│   │   ├── test_opentable.py
│   │   ├── test_weather.py
│   │   ├── test_calendar.py
│   │   ├── test_cache.py
│   │   └── test_resilience.py
│   │
│   ├── matching/
│   │   └── test_venue_matcher.py
│   │
│   └── tools/                       # MCP tool integration tests
│       ├── test_preferences.py
│       ├── test_people.py
│       ├── test_search.py
│       ├── test_booking.py
│       ├── test_history.py
│       ├── test_recommendations.py
│       └── test_date_utils.py
│
├── data/                            # Runtime data (gitignored except .gitkeep)
│   └── .gitkeep
├── pyproject.toml
├── .env.example
├── .gitignore
└── README.md
```

### Rules

1. **Test directory mirrors `src/` exactly.** Every `src/foo/bar.py` has a corresponding `tests/foo/test_bar.py`. No exceptions.
2. **No logic in `__init__.py`** beyond re-exports. Importing `from src.models import Restaurant` should work via `__init__.py` re-exports, but the class is defined in `src/models/restaurant.py`.
3. **One concern per file.** If a file exceeds ~300 lines, it is doing too much. Split into focused modules.
4. **No circular imports.** The dependency flow is strictly: `models → storage → clients → matching → tools → server`. Lower layers never import higher layers.
5. **`data/` is gitignored** except `.gitkeep`. The database, logs, and credentials are created at runtime.
6. **`.ai/` contains agent instructions only** — `AGENTS.md` (system prompt) and `ENGINEERING-STANDARDS.md` (this file). No code, no generated output.
7. **`docs/` is for human and agent documentation** — `docs/specs/` for EPICs and architecture, `docs/adr/` for Architecture Decision Records.
8. **`scripts/` contains executable validation scripts** — used by agents as deterministic feedback loops. Always run `./scripts/validate.sh` after completing work.

---

## 2. Module Boundaries & Dependency Rules

### Layer Architecture

```
┌─────────────────────────────────────────┐
│  server.py  (entry point, lifecycle)    │  ← Imports tools, initializes clients/DB
├─────────────────────────────────────────┤
│  tools/     (MCP tool definitions)      │  ← Orchestrates clients + storage
├─────────────────────────────────────────┤
│  matching/  (cross-platform resolution) │  ← Uses clients + storage
├─────────────────────────────────────────┤
│  clients/   (external API wrappers)     │  ← Uses models, resilience, config
├─────────────────────────────────────────┤
│  storage/   (SQLite + credentials)      │  ← Uses models, config
├─────────────────────────────────────────┤
│  models/    (Pydantic data structures)  │  ← Pure. No imports from other src/ layers.
├─────────────────────────────────────────┤
│  config.py  (settings singleton)        │  ← Pure. Only pydantic-settings + stdlib.
└─────────────────────────────────────────┘
```

### Import Rules

| Module | Can Import From | Cannot Import From |
|--------|----------------|-------------------|
| `models/` | stdlib, pydantic | anything in `src/` |
| `config.py` | stdlib, pydantic-settings | anything in `src/` |
| `storage/` | models, config | clients, matching, tools |
| `clients/` | models, config, `clients/resilience.py`, `clients/cache.py` | storage, matching, tools |
| `matching/` | models, config, clients, storage | tools |
| `tools/` | models, config, clients, storage, matching | (nothing above it) |
| `server.py` | everything | — |

### Dependency Injection

Components receive their dependencies explicitly — no hidden global state.

```python
# GOOD: Dependencies are explicit parameters
class GooglePlacesClient:
    def __init__(self, api_key: str, cache: InMemoryCache, db: DatabaseManager):
        self.api_key = api_key
        self.cache = cache
        self.db = db

# BAD: Reaching into global config or importing singletons inside methods
class GooglePlacesClient:
    def __init__(self):
        from src.config import settings  # Hidden dependency
        self.api_key = settings.google_api_key
```

**How this works in practice:** `server.py` is the composition root. It creates the `Settings`, `DatabaseManager`, `InMemoryCache`, and all clients, then passes them to the tool registration functions.

```python
# server.py — composition root
async def create_app():
    settings = Settings()
    db = DatabaseManager(settings.db_path)
    await db.initialize()
    cache = InMemoryCache(max_size=200)

    google_client = GooglePlacesClient(settings.google_api_key, cache, db)
    resy_client = ResyClient(...)
    # ... etc.

    # Register tools with their dependencies
    register_search_tools(mcp, google_client, db)
    register_booking_tools(mcp, resy_client, opentable_client, db)
    # ... etc.
```

Each tool file exports a registration function:

```python
# tools/search.py
def register_search_tools(mcp: FastMCP, google_client: GooglePlacesClient, db: DatabaseManager):
    @mcp.tool()
    async def search_restaurants(...) -> str:
        # Uses google_client and db via closure
        ...
```

---

## 3. Naming Conventions

### Files

| Type | Convention | Example |
|------|-----------|---------|
| Module | `snake_case.py` | `google_places.py`, `venue_matcher.py` |
| Test | `test_` prefix | `test_google_places.py` |
| SQL | `snake_case.sql` | `schema.sql` |
| Config | dot-prefix for hidden | `.env`, `.gitignore` |

### Python Identifiers

| Type | Convention | Example |
|------|-----------|---------|
| Class | `PascalCase` | `GooglePlacesClient`, `TimeSlot` |
| Function / Method | `snake_case` | `find_availability`, `parse_date` |
| Async function | `snake_case` (same) | `async def search_restaurants()` |
| Constant | `UPPER_SNAKE_CASE` | `BASE_URL`, `TRANSIENT_STATUS_CODES` |
| Variable | `snake_case` | `venue_id`, `party_size` |
| Private | `_leading_underscore` | `_parse_slots`, `_cache` |
| Enum member | `UPPER_SNAKE_CASE` | `Cuisine.ITALIAN`, `PriceLevel.UPSCALE` |
| MCP tool function | `snake_case` (becomes the tool name) | `search_restaurants`, `make_reservation` |

### Database

| Type | Convention | Example |
|------|-----------|---------|
| Table | `snake_case`, plural | `restaurants`, `visit_reviews` |
| Column | `snake_case` | `restaurant_id`, `created_at` |
| Index | `idx_{table}_{column}` | `idx_visits_restaurant` |
| Foreign key columns | `{referenced_table_singular}_id` | `person_id`, `group_id` |

---

## 4. Python Patterns & Style

### Type Hints — Always, Everywhere

Every function signature, every variable that isn't obvious, every return type.

```python
# GOOD
async def find_availability(
    self,
    venue_id: str,
    date: str,
    party_size: int,
) -> list[TimeSlot]:
    ...

# BAD
async def find_availability(self, venue_id, date, party_size):
    ...
```

Use modern Python 3.11+ type syntax:
- `str | None` not `Optional[str]`
- `list[str]` not `List[str]`
- `dict[str, Any]` not `Dict[str, Any]`

### String Formatting

Use f-strings. No `.format()`, no `%` formatting.

```python
# GOOD
message = f"Found {len(results)} restaurants near {location}"

# BAD
message = "Found {} restaurants near {}".format(len(results), location)
```

### Dataclass-Style Construction

Prefer keyword arguments for any function/constructor with more than 2 parameters.

```python
# GOOD
restaurant = Restaurant(
    id=place_id,
    name="Carbone",
    address="181 Thompson St",
    lat=40.7276,
    lng=-74.0009,
    cuisine=["italian"],
    price_level=4,
    rating=4.7,
)

# BAD
restaurant = Restaurant(place_id, "Carbone", "181 Thompson St", 40.7276, -74.0009, ...)
```

### Guard Clauses Over Deep Nesting

```python
# GOOD
async def get_cached_restaurant(self, place_id: str) -> Restaurant | None:
    if not place_id:
        return None

    row = await self.fetch_one("SELECT * FROM restaurant_cache WHERE id = ?", (place_id,))
    if not row:
        return None

    return Restaurant(**row)

# BAD
async def get_cached_restaurant(self, place_id: str) -> Restaurant | None:
    if place_id:
        row = await self.fetch_one("SELECT * FROM restaurant_cache WHERE id = ?", (place_id,))
        if row:
            return Restaurant(**row)
        else:
            return None
    else:
        return None
```

### No Bare `except`

Always catch specific exceptions. Always.

```python
# GOOD
try:
    response = await self.client.get(url)
except httpx.TimeoutException:
    raise TransientAPIError("Request timed out")
except httpx.HTTPStatusError as e:
    classify_response(e.response)

# BAD
try:
    response = await self.client.get(url)
except Exception:
    return None  # Swallows everything including bugs
```

---

## 5. Async Patterns

### Everything I/O is Async

All database queries, HTTP requests, and file operations use `async/await`.

```python
# GOOD
async def search_restaurants(...) -> str:
    prefs = await db.get_preferences()
    results = await google_client.search_nearby(...)
    return format_results(results)

# BAD (blocking I/O in async context)
def search_restaurants(...) -> str:
    prefs = db.get_preferences_sync()  # Blocks the event loop
```

### Use `asyncio.gather` for Independent I/O

When two operations don't depend on each other, run them concurrently.

```python
# GOOD: Resy and OpenTable checks run concurrently
resy_task = resy_client.find_availability(venue_id, date, party_size)
ot_task = opentable_client.find_availability(slug, date, party_size)
resy_slots, ot_slots = await asyncio.gather(resy_task, ot_task, return_exceptions=True)

# Handle exceptions from gather
if isinstance(resy_slots, Exception):
    resy_slots = []
if isinstance(ot_slots, Exception):
    ot_slots = []
```

### Never Block the Event Loop

- Use `aiosqlite` (not `sqlite3`)
- Use `httpx.AsyncClient` (not `requests`)
- Use `playwright.async_api` (not sync API)
- For CPU-bound work (unlikely in this project), use `asyncio.to_thread()`

### Resource Cleanup

Use `async with` for resources that need cleanup.

```python
# GOOD
async with httpx.AsyncClient() as client:
    response = await client.get(url)

# GOOD — for long-lived clients, clean up in lifecycle
class ResyClient:
    async def close(self):
        await self.client.aclose()
```

---

## 6. Pydantic Models

### Models Are Pure Data

Models live in `src/models/` and contain:
- Field definitions with types and defaults
- Validators (`@field_validator`)
- Computed properties (`@computed_field`)
- Serialization config (`model_config`)

Models must **never** contain:
- Database queries
- API calls
- File I/O
- Business logic (that goes in tools or clients)

```python
# GOOD — pure data model
class Restaurant(BaseModel):
    id: str
    name: str
    rating: float | None = None

    @field_validator("rating")
    @classmethod
    def validate_rating(cls, v: float | None) -> float | None:
        if v is not None and not (0 <= v <= 5):
            raise ValueError("Rating must be between 0 and 5")
        return v

# BAD — model with I/O
class Restaurant(BaseModel):
    id: str
    name: str

    async def save(self):  # Don't do this
        await db.save_restaurant(self)
```

### Use `model_config` for Serialization

```python
class Restaurant(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,      # Allow construction from ORM-like objects (sqlite rows)
        str_strip_whitespace=True,  # Strip leading/trailing whitespace from strings
    )
```

### Shared Enums Live in `enums.py`

Any enum used by more than one model file lives in `src/models/enums.py`. Enums used only within a single model file may live in that file.

---

## 7. Database Patterns

### Single `DatabaseManager` Class

All SQL lives in `src/storage/database.py`. No other file writes raw SQL. The `DatabaseManager` exposes typed methods that accept and return Pydantic models.

```python
# GOOD — typed repository method
async def get_person(self, name: str) -> Person | None:
    row = await self.fetch_one(
        "SELECT * FROM people WHERE LOWER(name) = LOWER(?)",
        (name,),
    )
    if not row:
        return None
    dietary = await self.fetch_all(
        "SELECT restriction FROM people_dietary WHERE person_id = ?",
        (row["id"],),
    )
    return Person(
        id=row["id"],
        name=row["name"],
        dietary_restrictions=[r["restriction"] for r in dietary],
        no_alcohol=bool(row["no_alcohol"]),
        notes=row["notes"],
    )

# BAD — raw SQL in a tool file
# tools/people.py
async def manage_person(name: str, ...):
    await db.execute("INSERT INTO people ...", (...))  # SQL should not be here
```

### Parameterized Queries Only

Never interpolate values into SQL strings. Always use `?` placeholders.

```python
# GOOD
await self.execute("SELECT * FROM people WHERE name = ?", (name,))

# BAD — SQL injection risk
await self.execute(f"SELECT * FROM people WHERE name = '{name}'")
```

### Transactions for Multi-Statement Operations

When an operation touches multiple tables, wrap in a transaction.

```python
async def save_person(self, person: Person) -> int:
    async with self.connection.execute("BEGIN"):
        cursor = await self.execute(
            "INSERT OR REPLACE INTO people (name, no_alcohol, notes) VALUES (?, ?, ?)",
            (person.name, person.no_alcohol, person.notes),
        )
        person_id = cursor.lastrowid

        await self.execute("DELETE FROM people_dietary WHERE person_id = ?", (person_id,))
        for restriction in person.dietary_restrictions:
            await self.execute(
                "INSERT INTO people_dietary (person_id, restriction) VALUES (?, ?)",
                (person_id, restriction),
            )
        await self.connection.commit()
    return person_id
```

### JSON Columns

Store complex data (lists, dicts) as JSON text in SQLite. Parse in Python.

```python
import json

# Writing
cuisine_json = json.dumps(["italian", "seafood"])
await self.execute("INSERT INTO restaurant_cache (..., cuisine) VALUES (..., ?)", (..., cuisine_json))

# Reading
row = await self.fetch_one("SELECT * FROM restaurant_cache WHERE id = ?", (place_id,))
cuisine_list = json.loads(row["cuisine"]) if row["cuisine"] else []
```

---

## 8. MCP Tool Patterns

### Tools Are Thin Orchestrators

A tool function should:
1. Parse/validate inputs
2. Call the appropriate client or database method
3. Format the result as a human-readable string
4. Return the string

A tool function should **not**:
- Contain business logic (put it in a client or helper)
- Write raw SQL (that's `DatabaseManager`'s job)
- Make raw HTTP calls (that's the client's job)
- Exceed ~50 lines (if longer, extract logic into helpers)

```python
# GOOD — thin orchestrator
@mcp.tool()
async def search_restaurants(cuisine: str | None = None, location: str = "home", ...) -> str:
    coords = await resolve_location(location, db)
    prefs = await db.get_preferences()
    raw_results = await google_client.search_nearby(query=cuisine, lat=coords.lat, lng=coords.lng)
    filtered = apply_preference_filters(raw_results, prefs, db)
    return format_search_results(filtered, coords)
```

### Docstrings Are Claude's Instructions

Tool docstrings are the **primary interface** for Claude to understand what a tool does. They must include:

1. **One-sentence summary** of what the tool does
2. **Args section** with every parameter explained, including valid values and defaults
3. **Returns section** describing the output format
4. **Example** showing a realistic invocation

```python
@mcp.tool()
async def search_restaurants(
    cuisine: str | None = None,
    location: str = "home",
    party_size: int = 2,
) -> str:
    """
    Search for restaurants matching your criteria near a location.
    Automatically applies your dietary restrictions, cuisine preferences,
    minimum rating threshold, and blacklist.

    Args:
        cuisine: Type of food, e.g. "italian", "mexican", "sushi".
                 Leave empty to search all cuisines.
        location: Where to search near. Use "home", "work", or a specific
                  NYC address like "123 Broadway, New York".
        party_size: Number of diners (default 2).

    Returns:
        Formatted list of matching restaurants with name, rating,
        price level, address, and walking distance.

    Example:
        search_restaurants(cuisine="italian", location="home")
    """
```

### Return Strings, Not Objects

MCP tools return strings that Claude presents to the user. Format them for readability.

```python
# GOOD
return (
    f"Found {len(results)} restaurants:\n\n"
    + "\n\n".join(
        f"{i+1}. {r.name} ({r.rating}★, {'$' * r.price_level})\n"
        f"   {r.address} | ~{r.walk_minutes} min walk"
        for i, r in enumerate(results)
    )
)

# BAD — returning raw JSON or repr
return json.dumps([r.model_dump() for r in results])
```

### Registration Pattern

Tools are registered via a function that receives dependencies, not via module-level decorators with global state.

```python
# tools/search.py
def register_search_tools(
    mcp: FastMCP,
    google_client: GooglePlacesClient,
    db: DatabaseManager,
):
    @mcp.tool()
    async def search_restaurants(...) -> str:
        # google_client and db available via closure
        ...
```

---

## 9. API Client Patterns

### Base Client Class

All HTTP-based clients inherit from a shared base that handles httpx setup, response classification, and API logging.

```python
# clients/base.py
class BaseAPIClient:
    def __init__(
        self,
        base_url: str,
        headers: dict[str, str],
        db: DatabaseManager,
        timeout: float = 30.0,
    ):
        self.base_url = base_url
        self.db = db
        self.client = httpx.AsyncClient(
            base_url=base_url,
            headers=headers,
            timeout=timeout,
        )
        self._provider_name: str = ""  # Set by subclass

    async def _request(
        self,
        method: str,
        path: str,
        cost_cents: float = 0.0,
        **kwargs,
    ) -> httpx.Response:
        """Make an HTTP request with logging and error classification."""
        response = await self.client.request(method, path, **kwargs)
        await self.db.log_api_call(
            provider=self._provider_name,
            endpoint=path,
            cost_cents=cost_cents,
            status_code=response.status_code,
            cached=False,
        )
        classify_response(response)
        return response

    async def close(self):
        await self.client.aclose()
```

Subclasses set `_provider_name` and call `self._request()` for all HTTP calls.

```python
# clients/google_places.py
class GooglePlacesClient(BaseAPIClient):
    def __init__(self, api_key: str, cache: InMemoryCache, db: DatabaseManager):
        super().__init__(
            base_url="https://places.googleapis.com",
            headers={
                "X-Goog-Api-Key": api_key,
                "Content-Type": "application/json",
            },
            db=db,
        )
        self._provider_name = "google_places"
        self.cache = cache
```

### Clients Own Their Response Parsing

Each client method returns **Pydantic models**, not raw dicts or JSON.

```python
# GOOD
async def find_availability(self, venue_id: str, date: str, party_size: int) -> list[TimeSlot]:
    response = await self._request("GET", "/4/find", params={...})
    return self._parse_slots(response.json())

def _parse_slots(self, data: dict) -> list[TimeSlot]:
    slots = []
    for slot_data in data.get("results", {}).get("venues", [{}])[0].get("slots", []):
        slots.append(TimeSlot(
            time=slot_data["date"]["start"],
            type=slot_data["config"]["type"],
            platform=BookingPlatform.RESY,
            config_id=slot_data["config"]["token"],
        ))
    return slots

# BAD — returning raw dict for caller to parse
async def find_availability(self, ...) -> dict:
    response = await self._request("GET", "/4/find", params={...})
    return response.json()  # Parsing pushed to the caller
```

### Separate Auth from Operations

Auth logic lives in dedicated `*_auth.py` files, not mixed into the API client.

---

## 10. Error Handling

### Exception Hierarchy

All custom exceptions inherit from a single base in `src/clients/resilience.py`:

```
APIError (base)
├── TransientAPIError      — retryable (429, 5xx)
├── PermanentAPIError      — not retryable (4xx)
│   └── AuthError          — credentials invalid/expired
├── SchemaChangeError      — response structure unexpected
└── CAPTCHAError           — bot detection triggered
```

### Every Tool Has a Try/Except Boundary

Tools are the boundary between the system and the user. Every tool catches exceptions and returns helpful error strings — never lets exceptions propagate to the MCP framework.

```python
@mcp.tool()
async def make_reservation(...) -> str:
    try:
        result = await _do_booking(...)
        return format_confirmation(result)
    except AuthError:
        return "Your Resy credentials may have expired. Please run store_resy_credentials to re-authenticate."
    except CAPTCHAError:
        link = generate_deep_link(...)
        return f"Resy is requiring manual verification. Book directly: {link}"
    except TransientAPIError:
        return "Resy is temporarily unavailable. Please try again in a minute."
    except Exception as e:
        logger.exception("Unexpected error in make_reservation")
        return f"Something went wrong: {e}. Please try again."
```

### Never Swallow Errors Silently

If you catch an exception, either re-raise it, log it, or return a meaningful message. Never `pass`.

```python
# BAD
try:
    result = await resy_client.book(...)
except Exception:
    pass  # Silent failure — user never knows what happened
```

---

## 11. Logging

### Use Python `logging` Module

Every module gets its own logger:

```python
import logging

logger = logging.getLogger(__name__)
```

### Log Levels

| Level | When to Use |
|-------|-------------|
| `DEBUG` | Detailed trace info: cache hits, parsed values, intermediate steps |
| `INFO` | Significant events: tool invoked, reservation made, token refreshed |
| `WARNING` | Recoverable issues: cache miss, stale data served, retry triggered |
| `ERROR` | Failed operations: booking failed, auth expired, API unreachable |

### Structured Context

Include relevant IDs and parameters in log messages:

```python
# GOOD
logger.info("Searching restaurants", extra={"cuisine": cuisine, "location": location, "party_size": party_size})
logger.error("Resy booking failed", extra={"venue_id": venue_id, "error": str(e)})

# At minimum, use f-strings with context
logger.info(f"Booking confirmed: {restaurant_name} on {date} at {time}, confirmation={confirmation_id}")
```

### Redact Sensitive Data

Never log passwords, auth tokens, or full API keys.

```python
# GOOD
logger.info(f"Resy auth token refreshed for {email}")

# BAD
logger.info(f"Resy auth: token={auth_token}, password={password}")
```

---

## 12. Configuration

### Single Source via `pydantic-settings`

All configuration flows through `src/config.py`:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    google_api_key: str
    openweather_api_key: str | None = None
    resy_email: str | None = None
    resy_password: str | None = None
    data_dir: Path = Path("./data")
    log_level: str = "INFO"
```

### No Hardcoded Values

URLs, API keys, timeouts, cache TTLs — anything that might change goes in config or as a class-level constant.

```python
# GOOD — constants at class level
class ResyClient(BaseAPIClient):
    BASE_URL = "https://api.resy.com"
    DEFAULT_TIMEOUT = 30.0

# BAD — magic values inline
response = await self.client.get("https://api.resy.com/4/find", timeout=30)
```

---

## 13. Testing Requirements

### Coverage Target: 100%

Every EPIC must include tests that cover 100% of the code introduced in that EPIC. This is measured by `pytest --cov=src --cov-report=term-missing` and verified before an EPIC is considered complete.

**What 100% coverage means in practice:**
- Every function and method is called by at least one test
- Every branch (`if`/`else`, `try`/`except`, early returns) is exercised
- Every error path is tested (not just the happy path)

### Test Configuration

Add to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
python_files = ["test_*.py"]
python_functions = ["test_*"]

[tool.coverage.run]
source = ["src"]
branch = true

[tool.coverage.report]
fail_under = 100
show_missing = true
exclude_lines = [
    "pragma: no cover",
    "if TYPE_CHECKING:",
    "if __name__ == .__main__.",
]
```

### Running Tests

**Always use the project scripts** for deterministic feedback:

```bash
# Full validation pipeline (lint + typecheck + test + coverage) — run after completing any story
./scripts/validate.sh

# Tests with coverage only
./scripts/test.sh

# Linting only (quick check while editing)
./scripts/lint.sh
```

For targeted runs during development:

```bash
# Run tests for a specific EPIC
pytest tests/tools/test_search.py tests/clients/test_google_places.py -v

# Run with verbose output
pytest -v --tb=short
```

### Test Structure Rules

1. **One test file per source file.** `src/clients/resy.py` → `tests/clients/test_resy.py`

2. **Test function naming:** `test_{method_name}_{scenario}_{expected_outcome}`
   ```python
   def test_find_availability_valid_venue_returns_slots():
   def test_find_availability_invalid_venue_returns_empty():
   def test_find_availability_expired_token_raises_auth_error():
   ```

3. **Arrange-Act-Assert pattern:**
   ```python
   async def test_search_restaurants_filters_blacklisted():
       # Arrange
       await db.add_to_blacklist("place123", "Badplace", "terrible service")
       mock_results = [make_restaurant(id="place123"), make_restaurant(id="place456")]
       google_client.search_nearby = AsyncMock(return_value=mock_results)

       # Act
       result = await search_restaurants(cuisine="italian", location="home")

       # Assert
       assert "place123" not in result
       assert "place456" in result or "Restaurant 456" in result
   ```

4. **Use fixtures from `conftest.py`** for shared setup:
   ```python
   # tests/conftest.py
   @pytest.fixture
   async def db():
       """In-memory SQLite database with schema applied."""
       manager = DatabaseManager(":memory:")
       await manager.initialize()
       yield manager
       await manager.close()

   @pytest.fixture
   def sample_restaurant():
       """A realistic Restaurant instance for testing."""
       return Restaurant(
           id="ChIJN1t_tDeuEmsRUsoyG83frY4",
           name="Carbone",
           address="181 Thompson St, New York, NY 10012",
           lat=40.7276,
           lng=-74.0009,
           cuisine=["italian"],
           price_level=4,
           rating=4.7,
           review_count=3200,
       )
   ```

5. **Test data factories in `tests/factories.py`** for generating model instances:
   ```python
   # tests/factories.py
   def make_restaurant(**overrides) -> Restaurant:
       defaults = {
           "id": f"place_{uuid4().hex[:8]}",
           "name": "Test Restaurant",
           "address": "123 Test St, New York, NY 10001",
           "lat": 40.7128,
           "lng": -74.0060,
           "cuisine": ["italian"],
           "price_level": 3,
           "rating": 4.5,
       }
       defaults.update(overrides)
       return Restaurant(**defaults)

   def make_person(**overrides) -> Person:
       defaults = {"name": "Test Person", "dietary_restrictions": [], "no_alcohol": False}
       defaults.update(overrides)
       return Person(**defaults)
   ```

### Mocking External Services

**External APIs are always mocked. Tests must never make real HTTP requests or launch real browsers.**

```python
# GOOD — mock the HTTP client
from unittest.mock import AsyncMock, patch

async def test_resy_find_availability_returns_parsed_slots(resy_client):
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = SAMPLE_RESY_AVAILABILITY_RESPONSE

    resy_client.client.get = AsyncMock(return_value=mock_response)

    slots = await resy_client.find_availability("834", "2026-02-14", 2)

    assert len(slots) == 3
    assert slots[0].platform == BookingPlatform.RESY
    assert slots[0].time == "18:30"
```

For Playwright tests, mock the browser at the `async_playwright` level:

```python
@patch("src.clients.opentable.async_playwright")
async def test_opentable_login(mock_playwright):
    mock_page = AsyncMock()
    mock_browser = AsyncMock()
    mock_browser.new_context.return_value.new_page.return_value = mock_page
    mock_playwright.return_value.start.return_value.chromium.launch.return_value = mock_browser

    client = OpenTableClient(credential_store)
    await client._login()

    mock_page.goto.assert_called_once_with("https://www.opentable.com/sign-in")
```

### Store Sample API Responses as Fixtures

Sample JSON responses live in `tests/fixtures/` (see directory structure in Section 1). Load in tests:

```python
import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"

def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())
```

### What to Test Per Layer

| Layer | What to Test | How |
|-------|-------------|-----|
| **Models** | Validation, defaults, edge cases | Direct instantiation, check field validators |
| **Storage** | CRUD operations, schema constraints, transactions | In-memory SQLite, real queries |
| **Clients** | Request construction, response parsing, error handling | Mock httpx/playwright, fixture responses |
| **Matching** | Name normalization, fuzzy matching, cache hits | Mock clients, test match accuracy |
| **Tools** | End-to-end orchestration, formatting, error messages | Mock clients + real in-memory DB |
| **Resilience** | Retry behavior, circuit breaker state, fallback cascade | Mock failures, count retries |

### Tests Required Per EPIC

| EPIC | Required Test Files |
|------|-------------------|
| 01 | `test_config.py` — settings load from env, defaults work, paths resolve |
| 02 | `test_enums.py`, `test_restaurant.py`, `test_user.py`, `test_reservation.py`, `test_review.py`, `test_database.py` |
| 03 | `test_preferences.py`, `test_people.py` |
| 04 | `test_google_places.py`, `test_search.py`, `test_cuisine_mapper.py` |
| 05 | `test_resy.py`, `test_resy_auth.py`, `test_credentials.py`, `test_booking.py`, `test_venue_matcher.py`, `test_date_utils.py` |
| 06 | `test_opentable.py`, update `test_booking.py` and `test_venue_matcher.py` |
| 07 | `test_weather.py`, `test_history.py`, `test_recommendations.py` |
| 08 | `test_resilience.py`, `test_cache.py`, `test_calendar.py`, update all client tests for circuit breakers |

---

## 14. Reuse & DRY Principles

### Extract Shared Logic Into Helpers

If the same logic appears in two or more places, extract it.

| Shared Concern | Where It Lives | Used By |
|---------------|----------------|---------|
| Date parsing ("Saturday" → "2026-02-15") | `tools/date_utils.py` | search, booking, history, recommendations |
| Location resolution ("home" → lat/lng) | `tools/search.py: resolve_location()` | search, recommendations, group search |
| Response classification (HTTP → exception) | `clients/resilience.py: classify_response()` | all API clients via BaseAPIClient |
| API call logging | `clients/base.py: BaseAPIClient._request()` | all API clients |
| Restaurant formatting for display | `tools/search.py: format_search_results()` | search, recommendations, group search |
| Deep link generation | `tools/booking.py: generate_deep_link()` | booking, availability, error fallback |
| Preference filter application | `tools/search.py: apply_preference_filters()` | search, recommendations, group search |

### Composition Over Inheritance

Use inheritance sparingly — only where there is genuine "is-a" relationship (e.g., `GooglePlacesClient` is a `BaseAPIClient`). For everything else, compose.

```python
# GOOD — composition
class VenueMatcher:
    def __init__(self, resy_client: ResyClient, opentable_client: OpenTableClient, db: DatabaseManager):
        self.resy = resy_client
        self.opentable = opentable_client
        self.db = db

# BAD — unnecessary inheritance
class VenueMatcher(ResyClient, OpenTableClient):  # Multiple inheritance mess
    ...
```

### Shared Constants

Constants used across modules (like API cost estimates, default TTLs, etc.) live in the module that owns the concept:

- Cache TTLs → `clients/cache.py`
- API cost estimates → `clients/base.py` or each client's module
- Error codes → `clients/resilience.py`
- Default search parameters → `tools/search.py`

### Format Functions Are Reusable

The same formatting function should work for search results, recommendations, and group search — they all display restaurants. Extract it once.

```python
# tools/search.py
def format_restaurant_list(
    restaurants: list[Restaurant],
    origin_lat: float | None = None,
    origin_lng: float | None = None,
    show_platform: bool = True,
) -> str:
    """Format a list of restaurants for display. Reused across search, recs, group search."""
    ...
```

---

## Quick Reference Checklist

Before marking any EPIC as complete, verify:

- [ ] All new files follow the directory structure in Section 1
- [ ] No circular imports (verify with `python -c "from src.server import mcp"`)
- [ ] All functions have type hints (parameters and return types)
- [ ] All MCP tools have comprehensive docstrings with Args, Returns, and Example
- [ ] All external API calls go through `BaseAPIClient._request()` with cost logging
- [ ] All SQL lives in `DatabaseManager` methods, nowhere else
- [ ] All tool functions catch exceptions and return user-friendly strings
- [ ] Tests exist for every new file with 100% branch coverage
- [ ] Tests mock all external services (no real HTTP/browser in tests)
- [ ] `./scripts/validate.sh` passes cleanly (lint + typecheck + tests + coverage)
- [ ] No hardcoded secrets, URLs, or magic numbers
- [ ] Sensitive data is never logged
- [ ] Any non-obvious architectural decisions are documented in `docs/adr/`
