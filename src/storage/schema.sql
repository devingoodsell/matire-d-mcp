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
    category TEXT NOT NULL
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
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    address TEXT NOT NULL,
    lat REAL,
    lng REAL,
    cuisine TEXT,
    price_level INTEGER,
    rating REAL,
    review_count INTEGER,
    phone TEXT,
    website TEXT,
    hours TEXT,
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
    companions TEXT,
    cuisine TEXT,
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

-- Wishlist
CREATE TABLE IF NOT EXISTS wishlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    restaurant_id TEXT NOT NULL UNIQUE,
    restaurant_name TEXT NOT NULL,
    notes TEXT,
    added_date TEXT DEFAULT (date('now'))
);

CREATE TABLE IF NOT EXISTS wishlist_tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wishlist_id INTEGER NOT NULL REFERENCES wishlist(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    UNIQUE(wishlist_id, tag)
);

-- API call logging (cost tracking)
CREATE TABLE IF NOT EXISTS api_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    cost_cents REAL DEFAULT 0,
    status_code INTEGER,
    cached BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Encrypted application config (master key mode)
CREATE TABLE IF NOT EXISTS app_config (
    key   TEXT PRIMARY KEY,
    value BLOB NOT NULL
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_visits_restaurant ON visits(restaurant_id);
CREATE INDEX IF NOT EXISTS idx_visits_date ON visits(date);
CREATE INDEX IF NOT EXISTS idx_restaurant_cache_name ON restaurant_cache(name);
CREATE INDEX IF NOT EXISTS idx_api_calls_provider ON api_calls(provider, created_at);
CREATE INDEX IF NOT EXISTS idx_reservations_date ON reservations(date);
CREATE INDEX IF NOT EXISTS idx_wishlist_restaurant ON wishlist(restaurant_id);
CREATE INDEX IF NOT EXISTS idx_wishlist_tags_wishlist ON wishlist_tags(wishlist_id);
CREATE INDEX IF NOT EXISTS idx_wishlist_tags_tag ON wishlist_tags(tag);
