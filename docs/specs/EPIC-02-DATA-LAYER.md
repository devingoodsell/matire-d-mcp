# EPIC-02: Data Models & Storage Layer

## Goal
Define all Pydantic models and implement the SQLite storage layer so that every other EPIC has a consistent, type-safe way to persist and query data.

## Success Criteria
- All Pydantic models validate correctly with realistic test data
- SQLite database initializes with full schema on first run
- Database manager provides async CRUD for all tables
- API call logging tracks cost per provider

---

## Story 2.1: Pydantic Models — Core Entities

**As a** developer
**I want** strongly-typed data models for all domain objects
**So that** data flows through the system validated and self-documenting

### Tasks

- [ ] **2.1.1** Create `src/models/enums.py` — shared enumerations:
  ```python
  class Cuisine(str, Enum):
      ITALIAN = "italian"
      MEXICAN = "mexican"
      JAPANESE = "japanese"
      KOREAN = "korean"
      CHINESE = "chinese"
      THAI = "thai"
      INDIAN = "indian"
      MEDITERRANEAN = "mediterranean"
      FRENCH = "french"
      AMERICAN = "american"
      SEAFOOD = "seafood"
      STEAKHOUSE = "steakhouse"
      PIZZA = "pizza"
      SUSHI = "sushi"
      OTHER = "other"

  class PriceLevel(int, Enum):
      BUDGET = 1       # $
      MODERATE = 2     # $$
      UPSCALE = 3      # $$$
      FINE_DINING = 4  # $$$$

  class Ambiance(str, Enum):
      QUIET = "quiet"
      MODERATE = "moderate"
      LIVELY = "lively"

  class NoiseLevel(str, Enum):
      QUIET = "quiet"
      MODERATE = "moderate"
      LOUD = "loud"

  class SeatingPreference(str, Enum):
      INDOOR = "indoor"
      OUTDOOR = "outdoor"
      NO_PREFERENCE = "no_preference"

  class BookingPlatform(str, Enum):
      RESY = "resy"
      OPENTABLE = "opentable"

  class CuisineCategory(str, Enum):
      FAVORITE = "favorite"
      LIKE = "like"
      NEUTRAL = "neutral"
      AVOID = "avoid"
  ```

- [ ] **2.1.2** Create `src/models/restaurant.py`:
  ```python
  class Restaurant(BaseModel):
      id: str                        # Google Place ID (canonical)
      name: str
      address: str
      lat: float
      lng: float
      cuisine: list[str]
      price_level: int | None        # 1-4
      rating: float | None           # Google rating
      review_count: int | None
      phone: str | None
      website: str | None
      hours: dict | None             # Opening hours
      resy_venue_id: str | None      # Cross-reference
      opentable_id: str | None       # Cross-reference
      cached_at: datetime | None

  class TimeSlot(BaseModel):
      time: str                      # "19:00"
      type: str | None               # "Dining Room", "Bar", "Patio"
      platform: BookingPlatform
      config_id: str | None          # Resy config_id or OpenTable slot ID

  class AvailabilityResult(BaseModel):
      restaurant_id: str
      restaurant_name: str
      date: str
      slots: list[TimeSlot]
      platform: BookingPlatform
      checked_at: datetime
  ```

- [ ] **2.1.3** Create `src/models/user.py`:
  ```python
  class UserPreferences(BaseModel):
      name: str
      rating_threshold: float = 4.0
      noise_preference: Ambiance = Ambiance.MODERATE
      seating_preference: SeatingPreference = SeatingPreference.NO_PREFERENCE
      max_walk_minutes: int = 15
      default_party_size: int = 2

  class DietaryRestriction(BaseModel):
      restriction: str               # "nut_allergy", "vegetarian", etc.

  class CuisinePreference(BaseModel):
      cuisine: str
      category: CuisineCategory

  class PricePreference(BaseModel):
      price_level: PriceLevel
      acceptable: bool = True

  class Location(BaseModel):
      name: str                      # "home", "work"
      address: str
      lat: float
      lng: float
      walk_radius_minutes: int = 15

  class Person(BaseModel):
      id: int | None = None
      name: str
      dietary_restrictions: list[str] = []
      no_alcohol: bool = False
      notes: str | None = None

  class Group(BaseModel):
      id: int | None = None
      name: str
      member_ids: list[int] = []
      member_names: list[str] = []   # Denormalized for display
  ```

- [ ] **2.1.4** Create `src/models/reservation.py`:
  ```python
  class Reservation(BaseModel):
      id: str | None = None          # Our internal ID
      restaurant_id: str             # Google Place ID
      restaurant_name: str
      platform: BookingPlatform
      platform_confirmation_id: str | None
      date: str                      # "2026-02-14"
      time: str                      # "19:00"
      party_size: int
      special_requests: str | None = None
      status: str = "confirmed"      # confirmed, cancelled
      created_at: datetime | None = None
      cancelled_at: datetime | None = None

  class BookingResult(BaseModel):
      success: bool
      reservation: Reservation | None = None
      error: str | None = None
      deep_link: str | None = None   # Fallback URL
      message: str
  ```

- [ ] **2.1.5** Create `src/models/review.py`:
  ```python
  class Visit(BaseModel):
      id: int | None = None
      restaurant_id: str
      restaurant_name: str
      date: str
      party_size: int
      companions: list[str] = []     # Names of dining companions
      source: str = "booked"         # "booked" or "manual"

  class VisitReview(BaseModel):
      visit_id: int
      would_return: bool
      overall_rating: int | None     # 1-5
      ambiance_rating: int | None    # 1-5
      noise_level: NoiseLevel | None
      notes: str | None = None

  class DishReview(BaseModel):
      visit_id: int
      dish_name: str
      rating: int                    # 1-5
      would_order_again: bool
      notes: str | None = None
  ```

---

## Story 2.2: SQLite Schema & Database Initialization

**As a** developer
**I want** the database schema created automatically on first run
**So that** no manual migration steps are needed

### Tasks

- [ ] **2.2.1** Create `src/storage/schema.sql` with the full schema:
  ```sql
  -- User preferences (single row — one user)
  CREATE TABLE IF NOT EXISTS user_preferences (
      id INTEGER PRIMARY KEY DEFAULT 1,
      name TEXT NOT NULL,
      rating_threshold REAL DEFAULT 4.0,
      noise_preference TEXT DEFAULT 'moderate',
      seating_preference TEXT DEFAULT 'no_preference',
      max_walk_minutes INTEGER DEFAULT 15,
      default_party_size INTEGER DEFAULT 2
  );

  CREATE TABLE IF NOT EXISTS user_dietary (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      restriction TEXT NOT NULL UNIQUE
  );

  CREATE TABLE IF NOT EXISTS cuisine_preferences (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      cuisine TEXT NOT NULL UNIQUE,
      category TEXT NOT NULL  -- 'favorite', 'like', 'neutral', 'avoid'
  );

  CREATE TABLE IF NOT EXISTS price_preferences (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      price_level INTEGER NOT NULL UNIQUE,
      acceptable BOOLEAN DEFAULT 1
  );

  CREATE TABLE IF NOT EXISTS locations (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL UNIQUE,
      address TEXT NOT NULL,
      lat REAL NOT NULL,
      lng REAL NOT NULL,
      walk_radius_minutes INTEGER DEFAULT 15
  );

  -- People & groups
  CREATE TABLE IF NOT EXISTS people (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL UNIQUE,
      no_alcohol BOOLEAN DEFAULT 0,
      notes TEXT
  );

  CREATE TABLE IF NOT EXISTS people_dietary (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
      restriction TEXT NOT NULL,
      UNIQUE(person_id, restriction)
  );

  CREATE TABLE IF NOT EXISTS groups (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL UNIQUE
  );

  CREATE TABLE IF NOT EXISTS group_members (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
      person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
      UNIQUE(group_id, person_id)
  );

  -- Restaurant cache
  CREATE TABLE IF NOT EXISTS restaurant_cache (
      id TEXT PRIMARY KEY,           -- Google Place ID
      name TEXT NOT NULL,
      address TEXT NOT NULL,
      lat REAL,
      lng REAL,
      cuisine TEXT,                  -- JSON array
      price_level INTEGER,
      rating REAL,
      review_count INTEGER,
      phone TEXT,
      website TEXT,
      hours TEXT,                    -- JSON
      resy_venue_id TEXT,
      opentable_id TEXT,
      cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  );

  -- Visit history
  CREATE TABLE IF NOT EXISTS visits (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      restaurant_id TEXT NOT NULL,
      restaurant_name TEXT NOT NULL,
      date TEXT NOT NULL,
      party_size INTEGER DEFAULT 2,
      companions TEXT,               -- JSON array of names
      source TEXT DEFAULT 'booked',
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  );

  CREATE TABLE IF NOT EXISTS visit_reviews (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      visit_id INTEGER NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
      would_return BOOLEAN,
      overall_rating INTEGER,
      ambiance_rating INTEGER,
      noise_level TEXT,
      notes TEXT
  );

  CREATE TABLE IF NOT EXISTS dish_reviews (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      visit_id INTEGER NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
      dish_name TEXT NOT NULL,
      rating INTEGER,
      would_order_again BOOLEAN,
      notes TEXT
  );

  -- Reservations
  CREATE TABLE IF NOT EXISTS reservations (
      id TEXT PRIMARY KEY,
      restaurant_id TEXT NOT NULL,
      restaurant_name TEXT NOT NULL,
      platform TEXT NOT NULL,
      platform_confirmation_id TEXT,
      date TEXT NOT NULL,
      time TEXT NOT NULL,
      party_size INTEGER NOT NULL,
      special_requests TEXT,
      status TEXT DEFAULT 'confirmed',
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      cancelled_at TIMESTAMP
  );

  -- Blacklist
  CREATE TABLE IF NOT EXISTS blacklist (
      restaurant_id TEXT PRIMARY KEY,
      restaurant_name TEXT,
      reason TEXT,
      added_date TEXT DEFAULT (date('now'))
  );

  -- API call logging (cost tracking)
  CREATE TABLE IF NOT EXISTS api_calls (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      provider TEXT NOT NULL,        -- 'google_places', 'resy', 'opentable', 'openweather'
      endpoint TEXT NOT NULL,
      cost_cents REAL DEFAULT 0,     -- Estimated cost in cents
      status_code INTEGER,
      cached BOOLEAN DEFAULT 0,
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  );

  -- Indexes for common queries
  CREATE INDEX IF NOT EXISTS idx_visits_restaurant ON visits(restaurant_id);
  CREATE INDEX IF NOT EXISTS idx_visits_date ON visits(date);
  CREATE INDEX IF NOT EXISTS idx_restaurant_cache_name ON restaurant_cache(name);
  CREATE INDEX IF NOT EXISTS idx_api_calls_provider ON api_calls(provider, created_at);
  CREATE INDEX IF NOT EXISTS idx_reservations_date ON reservations(date);
  ```

- [ ] **2.2.2** Create `src/storage/database.py` with `DatabaseManager` class:
  - `__init__(self, db_path: Path)` — stores path, connection is None
  - `async initialize()` — creates connection, enables WAL mode, enables foreign keys, executes schema.sql
  - `async close()` — closes connection
  - Context manager support (`async with DatabaseManager(path) as db:`)
  - `async execute(sql, params)` — execute single query
  - `async execute_many(sql, params_list)` — batch execute
  - `async fetch_one(sql, params)` — returns dict or None
  - `async fetch_all(sql, params)` — returns list of dicts
  - Use `aiosqlite` with `row_factory = aiosqlite.Row` for dict-like access

---

## Story 2.3: Database Repository Methods

**As a** developer
**I want** typed repository methods for each domain area
**So that** tools don't write raw SQL

### Tasks

- [ ] **2.3.1** Add user preference methods to `DatabaseManager`:
  - `async get_preferences() -> UserPreferences | None`
  - `async save_preferences(prefs: UserPreferences)`
  - `async get_dietary_restrictions() -> list[str]`
  - `async set_dietary_restrictions(restrictions: list[str])`
  - `async get_cuisine_preferences() -> list[CuisinePreference]`
  - `async set_cuisine_preferences(prefs: list[CuisinePreference])`
  - `async get_price_preferences() -> list[PricePreference]`
  - `async set_price_preferences(prefs: list[PricePreference])`
  - `async get_locations() -> list[Location]`
  - `async save_location(location: Location)`
  - `async get_location(name: str) -> Location | None`

- [ ] **2.3.2** Add people & group methods:
  - `async get_people() -> list[Person]`
  - `async get_person(name: str) -> Person | None`
  - `async save_person(person: Person) -> int` (returns ID)
  - `async delete_person(name: str)`
  - `async get_groups() -> list[Group]`
  - `async get_group(name: str) -> Group | None`
  - `async save_group(group: Group) -> int`
  - `async delete_group(name: str)`
  - `async get_group_dietary_restrictions(group_name: str) -> list[str]` — merges all member restrictions

- [ ] **2.3.3** Add restaurant cache methods:
  - `async cache_restaurant(restaurant: Restaurant)`
  - `async get_cached_restaurant(place_id: str) -> Restaurant | None`
  - `async search_cached_restaurants(name: str) -> list[Restaurant]`
  - `async get_stale_cache_ids(max_age_hours: int = 24) -> list[str]`
  - `async update_platform_ids(place_id: str, resy_id: str | None, opentable_id: str | None)`

- [ ] **2.3.4** Add visit & review methods:
  - `async log_visit(visit: Visit) -> int`
  - `async get_recent_visits(days: int = 14) -> list[Visit]`
  - `async get_visits_for_restaurant(restaurant_id: str) -> list[Visit]`
  - `async save_visit_review(review: VisitReview)`
  - `async save_dish_review(review: DishReview)`
  - `async get_recent_cuisines(days: int = 7) -> list[str]` — for recency filtering

- [ ] **2.3.5** Add reservation methods:
  - `async save_reservation(reservation: Reservation)`
  - `async get_upcoming_reservations() -> list[Reservation]`
  - `async cancel_reservation(reservation_id: str)`
  - `async get_reservation(reservation_id: str) -> Reservation | None`

- [ ] **2.3.6** Add blacklist methods:
  - `async add_to_blacklist(restaurant_id: str, restaurant_name: str, reason: str)`
  - `async is_blacklisted(restaurant_id: str) -> bool`
  - `async get_blacklist() -> list[dict]`
  - `async remove_from_blacklist(restaurant_id: str)`

- [ ] **2.3.7** Add API logging methods:
  - `async log_api_call(provider: str, endpoint: str, cost_cents: float, status_code: int, cached: bool)`
  - `async get_api_costs(days: int = 30) -> dict[str, float]` — returns cost by provider

---

## Story 2.4: Database Lifecycle in Server

**As a** developer
**I want** the database initialized at server startup and available globally
**So that** all tools can access it

### Tasks

- [ ] **2.4.1** In `src/server.py`, initialize `DatabaseManager` at startup:
  - Create `data/` directory if it doesn't exist
  - Call `db.initialize()` before starting MCP server
  - Store `db` instance accessible to all tool modules (module-level or via dependency injection)

- [ ] **2.4.2** Add a `lifespan` handler to FastMCP (if supported) or initialize in server startup to ensure DB is ready before any tool call

---

## Dependencies
- EPIC-01 (project structure must exist)

## Blocked By
- EPIC-01

## Blocks
- EPIC-03 (preferences tools need DB)
- EPIC-04 (search caching needs DB)
- EPIC-05, EPIC-06 (reservation storage needs DB)
- EPIC-07 (visit history needs DB)

## Cost Considerations
- No API costs — pure local storage
- SQLite with WAL mode handles concurrent reads well for single-user

## Technical Notes
- Use `aiosqlite` for async SQLite access — FastMCP tools are async
- Enable WAL mode for better concurrent read performance: `PRAGMA journal_mode=WAL`
- Enable foreign keys: `PRAGMA foreign_keys=ON`
- All JSON fields (cuisine list, hours, companions) stored as JSON text, parsed in Python
- Single-user app: `user_preferences` table has exactly one row (id=1)
- Google Place ID as canonical `restaurant_id` throughout the system
