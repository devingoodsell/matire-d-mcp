import json
import logging
from pathlib import Path

import aiosqlite

from src.models.enums import (
    Ambiance,
    BookingPlatform,
    CuisineCategory,
    PriceLevel,
    SeatingPreference,
)
from src.models.reservation import Reservation
from src.models.restaurant import Restaurant
from src.models.review import DishReview, Visit, VisitReview
from src.models.user import (
    CuisinePreference,
    Group,
    Location,
    Person,
    PricePreference,
    UserPreferences,
)

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Async SQLite database manager with typed repository methods.

    All SQL in the application lives in this class. Other layers
    call typed methods that accept and return Pydantic models.
    """

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = str(db_path)
        self.connection: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Open connection, enable WAL mode and foreign keys, execute schema."""
        self.connection = await aiosqlite.connect(self.db_path)
        self.connection.row_factory = aiosqlite.Row
        schema_path = Path(__file__).parent / "schema.sql"
        schema_sql = schema_path.read_text()
        await self.connection.executescript(schema_sql)
        await self.connection.execute("PRAGMA journal_mode=WAL")
        await self.connection.execute("PRAGMA foreign_keys=ON")
        await self.connection.commit()
        logger.info(f"Database initialized at {self.db_path}")

    async def close(self) -> None:
        """Close the database connection."""
        if self.connection:
            await self.connection.close()
            self.connection = None

    async def __aenter__(self) -> "DatabaseManager":
        await self.initialize()
        return self

    async def __aexit__(
        self, exc_type: type | None, exc_val: Exception | None, exc_tb: object
    ) -> None:
        await self.close()

    async def execute(self, sql: str, params: tuple = ()) -> aiosqlite.Cursor:
        """Execute a single SQL statement and commit."""
        assert self.connection is not None
        cursor = await self.connection.execute(sql, params)
        await self.connection.commit()
        return cursor

    async def execute_many(self, sql: str, params_list: list[tuple]) -> None:
        """Execute a SQL statement with multiple parameter sets."""
        assert self.connection is not None
        await self.connection.executemany(sql, params_list)
        await self.connection.commit()

    async def fetch_one(self, sql: str, params: tuple = ()) -> dict | None:
        """Execute a query and return a single row as a dict, or None."""
        assert self.connection is not None
        cursor = await self.connection.execute(sql, params)
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    async def fetch_all(self, sql: str, params: tuple = ()) -> list[dict]:
        """Execute a query and return all rows as list of dicts."""
        assert self.connection is not None
        cursor = await self.connection.execute(sql, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ── User Preferences ──────────────────────────────────────────────────

    async def get_preferences(self) -> UserPreferences | None:
        row = await self.fetch_one("SELECT * FROM user_preferences WHERE id = 1")
        if not row:
            return None
        return UserPreferences(
            name=row["name"],
            rating_threshold=row["rating_threshold"],
            noise_preference=Ambiance(row["noise_preference"]),
            seating_preference=SeatingPreference(row["seating_preference"]),
            max_walk_minutes=row["max_walk_minutes"],
            default_party_size=row["default_party_size"],
        )

    async def save_preferences(self, prefs: UserPreferences) -> None:
        await self.execute(
            """INSERT OR REPLACE INTO user_preferences
               (id, name, rating_threshold, noise_preference, seating_preference,
                max_walk_minutes, default_party_size)
               VALUES (1, ?, ?, ?, ?, ?, ?)""",
            (
                prefs.name,
                prefs.rating_threshold,
                prefs.noise_preference.value,
                prefs.seating_preference.value,
                prefs.max_walk_minutes,
                prefs.default_party_size,
            ),
        )

    async def get_dietary_restrictions(self) -> list[str]:
        rows = await self.fetch_all("SELECT restriction FROM user_dietary")
        return [r["restriction"] for r in rows]

    async def set_dietary_restrictions(self, restrictions: list[str]) -> None:
        assert self.connection is not None
        await self.connection.execute("DELETE FROM user_dietary")
        for restriction in restrictions:
            await self.connection.execute(
                "INSERT INTO user_dietary (restriction) VALUES (?)",
                (restriction,),
            )
        await self.connection.commit()

    async def get_cuisine_preferences(self) -> list[CuisinePreference]:
        rows = await self.fetch_all("SELECT cuisine, category FROM cuisine_preferences")
        return [
            CuisinePreference(cuisine=r["cuisine"], category=CuisineCategory(r["category"]))
            for r in rows
        ]

    async def set_cuisine_preferences(self, prefs: list[CuisinePreference]) -> None:
        assert self.connection is not None
        await self.connection.execute("DELETE FROM cuisine_preferences")
        for p in prefs:
            await self.connection.execute(
                "INSERT INTO cuisine_preferences (cuisine, category) VALUES (?, ?)",
                (p.cuisine, p.category.value),
            )
        await self.connection.commit()

    async def get_price_preferences(self) -> list[PricePreference]:
        rows = await self.fetch_all("SELECT price_level, acceptable FROM price_preferences")
        return [
            PricePreference(
                price_level=PriceLevel(r["price_level"]),
                acceptable=bool(r["acceptable"]),
            )
            for r in rows
        ]

    async def set_price_preferences(self, prefs: list[PricePreference]) -> None:
        assert self.connection is not None
        await self.connection.execute("DELETE FROM price_preferences")
        for p in prefs:
            await self.connection.execute(
                "INSERT INTO price_preferences (price_level, acceptable) VALUES (?, ?)",
                (p.price_level.value, p.acceptable),
            )
        await self.connection.commit()

    async def get_locations(self) -> list[Location]:
        rows = await self.fetch_all("SELECT * FROM locations")
        return [
            Location(
                name=r["name"],
                address=r["address"],
                lat=r["lat"],
                lng=r["lng"],
                walk_radius_minutes=r["walk_radius_minutes"],
            )
            for r in rows
        ]

    async def save_location(self, location: Location) -> None:
        await self.execute(
            """INSERT INTO locations (name, address, lat, lng, walk_radius_minutes)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET
                   address = excluded.address,
                   lat = excluded.lat,
                   lng = excluded.lng,
                   walk_radius_minutes = excluded.walk_radius_minutes""",
            (
                location.name, location.address, location.lat,
                location.lng, location.walk_radius_minutes,
            ),
        )

    async def get_location(self, name: str) -> Location | None:
        row = await self.fetch_one(
            "SELECT * FROM locations WHERE LOWER(name) = LOWER(?)", (name,)
        )
        if not row:
            return None
        return Location(
            name=row["name"],
            address=row["address"],
            lat=row["lat"],
            lng=row["lng"],
            walk_radius_minutes=row["walk_radius_minutes"],
        )

    # ── People & Groups ───────────────────────────────────────────────────

    async def get_people(self) -> list[Person]:
        rows = await self.fetch_all("SELECT * FROM people")
        people = []
        for row in rows:
            dietary = await self.fetch_all(
                "SELECT restriction FROM people_dietary WHERE person_id = ?",
                (row["id"],),
            )
            people.append(
                Person(
                    id=row["id"],
                    name=row["name"],
                    dietary_restrictions=[d["restriction"] for d in dietary],
                    no_alcohol=bool(row["no_alcohol"]),
                    notes=row["notes"],
                )
            )
        return people

    async def get_person(self, name: str) -> Person | None:
        row = await self.fetch_one(
            "SELECT * FROM people WHERE LOWER(name) = LOWER(?)", (name,)
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
            dietary_restrictions=[d["restriction"] for d in dietary],
            no_alcohol=bool(row["no_alcohol"]),
            notes=row["notes"],
        )

    async def save_person(self, person: Person) -> int:
        assert self.connection is not None
        cursor = await self.connection.execute(
            """INSERT INTO people (name, no_alcohol, notes) VALUES (?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET
                   no_alcohol = excluded.no_alcohol,
                   notes = excluded.notes""",
            (person.name, person.no_alcohol, person.notes),
        )
        person_id = cursor.lastrowid
        await self.connection.execute(
            "DELETE FROM people_dietary WHERE person_id = ?", (person_id,)
        )
        for restriction in person.dietary_restrictions:
            await self.connection.execute(
                "INSERT INTO people_dietary (person_id, restriction) VALUES (?, ?)",
                (person_id, restriction),
            )
        await self.connection.commit()
        return person_id

    async def delete_person(self, name: str) -> None:
        await self.execute(
            "DELETE FROM people WHERE LOWER(name) = LOWER(?)", (name,)
        )

    async def get_groups(self) -> list[Group]:
        rows = await self.fetch_all("SELECT * FROM groups")
        groups = []
        for row in rows:
            members = await self.fetch_all(
                """SELECT p.id, p.name FROM group_members gm
                   JOIN people p ON gm.person_id = p.id
                   WHERE gm.group_id = ?""",
                (row["id"],),
            )
            groups.append(
                Group(
                    id=row["id"],
                    name=row["name"],
                    member_ids=[m["id"] for m in members],
                    member_names=[m["name"] for m in members],
                )
            )
        return groups

    async def get_group(self, name: str) -> Group | None:
        row = await self.fetch_one(
            "SELECT * FROM groups WHERE LOWER(name) = LOWER(?)", (name,)
        )
        if not row:
            return None
        members = await self.fetch_all(
            """SELECT p.id, p.name FROM group_members gm
               JOIN people p ON gm.person_id = p.id
               WHERE gm.group_id = ?""",
            (row["id"],),
        )
        return Group(
            id=row["id"],
            name=row["name"],
            member_ids=[m["id"] for m in members],
            member_names=[m["name"] for m in members],
        )

    async def save_group(self, group: Group) -> int:
        assert self.connection is not None
        cursor = await self.connection.execute(
            """INSERT INTO groups (name) VALUES (?)
               ON CONFLICT(name) DO UPDATE SET name = excluded.name""",
            (group.name,),
        )
        group_id = cursor.lastrowid
        await self.connection.execute(
            "DELETE FROM group_members WHERE group_id = ?", (group_id,)
        )
        for member_id in group.member_ids:
            await self.connection.execute(
                "INSERT INTO group_members (group_id, person_id) VALUES (?, ?)",
                (group_id, member_id),
            )
        await self.connection.commit()
        return group_id

    async def delete_group(self, name: str) -> None:
        await self.execute(
            "DELETE FROM groups WHERE LOWER(name) = LOWER(?)", (name,)
        )

    async def get_group_dietary_restrictions(self, group_name: str) -> list[str]:
        rows = await self.fetch_all(
            """SELECT DISTINCT pd.restriction
               FROM groups g
               JOIN group_members gm ON g.id = gm.group_id
               JOIN people_dietary pd ON gm.person_id = pd.person_id
               WHERE LOWER(g.name) = LOWER(?)""",
            (group_name,),
        )
        return [r["restriction"] for r in rows]

    # ── Restaurant Cache ──────────────────────────────────────────────────

    def _row_to_restaurant(self, row: dict) -> Restaurant:
        """Convert a database row dict to a Restaurant model."""
        return Restaurant(
            id=row["id"],
            name=row["name"],
            address=row["address"],
            lat=row["lat"],
            lng=row["lng"],
            cuisine=json.loads(row["cuisine"]) if row["cuisine"] else [],
            price_level=row["price_level"],
            rating=row["rating"],
            review_count=row["review_count"],
            phone=row["phone"],
            website=row["website"],
            hours=json.loads(row["hours"]) if row["hours"] else None,
            resy_venue_id=row["resy_venue_id"],
            opentable_id=row["opentable_id"],
            cached_at=row["cached_at"],
        )

    async def cache_restaurant(self, restaurant: Restaurant) -> None:
        await self.execute(
            """INSERT OR REPLACE INTO restaurant_cache
               (id, name, address, lat, lng, cuisine, price_level, rating,
                review_count, phone, website, hours, resy_venue_id,
                opentable_id, cached_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                       CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
            (
                restaurant.id,
                restaurant.name,
                restaurant.address,
                restaurant.lat,
                restaurant.lng,
                json.dumps(restaurant.cuisine),
                restaurant.price_level,
                restaurant.rating,
                restaurant.review_count,
                restaurant.phone,
                restaurant.website,
                json.dumps(restaurant.hours) if restaurant.hours else None,
                restaurant.resy_venue_id,
                restaurant.opentable_id,
            ),
        )

    async def get_cached_restaurant(self, place_id: str) -> Restaurant | None:
        row = await self.fetch_one(
            "SELECT * FROM restaurant_cache WHERE id = ?", (place_id,)
        )
        if not row:
            return None
        return self._row_to_restaurant(row)

    async def search_cached_restaurants(self, name: str) -> list[Restaurant]:
        rows = await self.fetch_all(
            "SELECT * FROM restaurant_cache WHERE LOWER(name) LIKE LOWER(?)",
            (f"%{name}%",),
        )
        return [self._row_to_restaurant(r) for r in rows]

    async def get_stale_cache_ids(self, max_age_hours: int = 24) -> list[str]:
        rows = await self.fetch_all(
            """SELECT id FROM restaurant_cache
               WHERE cached_at < datetime('now', ?)""",
            (f"-{max_age_hours} hours",),
        )
        return [r["id"] for r in rows]

    async def update_platform_ids(
        self,
        place_id: str,
        resy_id: str | None,
        opentable_id: str | None,
    ) -> None:
        await self.execute(
            """UPDATE restaurant_cache
               SET resy_venue_id = ?, opentable_id = ?, updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (resy_id, opentable_id, place_id),
        )

    # ── Visits & Reviews ──────────────────────────────────────────────────

    def _row_to_visit(self, row: dict) -> Visit:
        """Convert a database row dict to a Visit model."""
        return Visit(
            id=row["id"],
            restaurant_id=row["restaurant_id"],
            restaurant_name=row["restaurant_name"],
            date=row["date"],
            party_size=row["party_size"],
            companions=json.loads(row["companions"]) if row["companions"] else [],
            cuisine=row.get("cuisine"),
            source=row["source"],
        )

    async def log_visit(self, visit: Visit) -> int:
        cursor = await self.execute(
            """INSERT INTO visits
               (restaurant_id, restaurant_name, date, party_size, companions, cuisine, source)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                visit.restaurant_id,
                visit.restaurant_name,
                visit.date,
                visit.party_size,
                json.dumps(visit.companions),
                visit.cuisine,
                visit.source,
            ),
        )
        return cursor.lastrowid

    async def get_recent_visits(self, days: int = 14) -> list[Visit]:
        rows = await self.fetch_all(
            """SELECT * FROM visits
               WHERE date >= date('now', ?)
               ORDER BY date DESC""",
            (f"-{days} days",),
        )
        return [self._row_to_visit(r) for r in rows]

    async def get_visits_for_restaurant(self, restaurant_id: str) -> list[Visit]:
        rows = await self.fetch_all(
            "SELECT * FROM visits WHERE restaurant_id = ? ORDER BY date DESC",
            (restaurant_id,),
        )
        return [self._row_to_visit(r) for r in rows]

    async def save_visit_review(self, review: VisitReview) -> None:
        await self.execute(
            """INSERT INTO visit_reviews
               (visit_id, would_return, overall_rating, ambiance_rating,
                noise_level, notes)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                review.visit_id,
                review.would_return,
                review.overall_rating,
                review.ambiance_rating,
                review.noise_level.value if review.noise_level else None,
                review.notes,
            ),
        )

    async def save_dish_review(self, review: DishReview) -> None:
        await self.execute(
            """INSERT INTO dish_reviews
               (visit_id, dish_name, rating, would_order_again, notes)
               VALUES (?, ?, ?, ?, ?)""",
            (
                review.visit_id,
                review.dish_name,
                review.rating,
                review.would_order_again,
                review.notes,
            ),
        )

    async def get_visit_by_restaurant_name(self, name: str) -> Visit | None:
        """Find the most recent visit matching a restaurant name."""
        row = await self.fetch_one(
            """SELECT * FROM visits
               WHERE LOWER(restaurant_name) LIKE LOWER(?)
               ORDER BY date DESC LIMIT 1""",
            (f"%{name}%",),
        )
        if not row:
            return None
        return self._row_to_visit(row)

    async def get_visit_review(self, visit_id: int) -> VisitReview | None:
        """Get the review for a specific visit."""
        row = await self.fetch_one(
            "SELECT * FROM visit_reviews WHERE visit_id = ?", (visit_id,)
        )
        if not row:
            return None
        return VisitReview(
            visit_id=row["visit_id"],
            would_return=bool(row["would_return"]),
            overall_rating=row["overall_rating"],
            ambiance_rating=row["ambiance_rating"],
            noise_level=row["noise_level"],
            notes=row["notes"],
        )

    async def get_restaurant_reviews(self, restaurant_id: str) -> list[VisitReview]:
        """Get all reviews for visits to a specific restaurant."""
        rows = await self.fetch_all(
            """SELECT vr.* FROM visit_reviews vr
               JOIN visits v ON vr.visit_id = v.id
               WHERE v.restaurant_id = ?""",
            (restaurant_id,),
        )
        return [
            VisitReview(
                visit_id=r["visit_id"],
                would_return=bool(r["would_return"]),
                overall_rating=r["overall_rating"],
                ambiance_rating=r["ambiance_rating"],
                noise_level=r["noise_level"],
                notes=r["notes"],
            )
            for r in rows
        ]

    async def get_recency_penalties(self, days: int = 14) -> dict[str, float]:
        """Return penalty scores (0-1) for cuisines based on recent visits.

        Higher penalty = visited more recently.
        Cuisines not visited get 0 penalty.
        """
        rows = await self.fetch_all(
            """SELECT v.cuisine, rc.cuisine as cached_cuisine,
                      julianday('now') - julianday(v.date) as days_ago
               FROM visits v
               LEFT JOIN restaurant_cache rc ON v.restaurant_id = rc.id
               WHERE v.date >= date('now', ?)
               ORDER BY v.date DESC""",
            (f"-{days} days",),
        )
        penalties: dict[str, float] = {}
        for r in rows:
            # Get cuisine from visit or from cached restaurant
            cuisine_str = r["cuisine"]
            if not cuisine_str and r["cached_cuisine"]:
                cuisine_list = json.loads(r["cached_cuisine"])
                cuisine_str = cuisine_list[0] if cuisine_list else None
            if not cuisine_str:
                continue

            cuisine_lower = cuisine_str.lower()
            days_ago = max(r["days_ago"], 0)
            penalty = max(0.0, 1.0 - (days_ago / days))
            # Keep the highest penalty (most recent visit)
            if cuisine_lower not in penalties or penalty > penalties[cuisine_lower]:
                penalties[cuisine_lower] = penalty
        return penalties

    async def get_recent_cuisines(self, days: int = 7) -> list[str]:
        rows = await self.fetch_all(
            """SELECT DISTINCT rc.cuisine
               FROM visits v
               JOIN restaurant_cache rc ON v.restaurant_id = rc.id
               WHERE v.date >= date('now', ?)""",
            (f"-{days} days",),
        )
        cuisines: list[str] = []
        for r in rows:
            if r["cuisine"]:
                cuisines.extend(json.loads(r["cuisine"]))
        return list(set(cuisines))

    # ── Reservations ──────────────────────────────────────────────────────

    def _row_to_reservation(self, row: dict) -> Reservation:
        """Convert a database row dict to a Reservation model."""
        return Reservation(
            id=row["id"],
            restaurant_id=row["restaurant_id"],
            restaurant_name=row["restaurant_name"],
            platform=BookingPlatform(row["platform"]),
            platform_confirmation_id=row["platform_confirmation_id"],
            date=row["date"],
            time=row["time"],
            party_size=row["party_size"],
            special_requests=row["special_requests"],
            status=row["status"],
            created_at=row["created_at"],
            cancelled_at=row["cancelled_at"],
        )

    async def save_reservation(self, reservation: Reservation) -> None:
        await self.execute(
            """INSERT OR REPLACE INTO reservations
               (id, restaurant_id, restaurant_name, platform,
                platform_confirmation_id, date, time, party_size,
                special_requests, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                reservation.id,
                reservation.restaurant_id,
                reservation.restaurant_name,
                reservation.platform.value,
                reservation.platform_confirmation_id,
                reservation.date,
                reservation.time,
                reservation.party_size,
                reservation.special_requests,
                reservation.status,
            ),
        )

    async def get_upcoming_reservations(self) -> list[Reservation]:
        rows = await self.fetch_all(
            """SELECT * FROM reservations
               WHERE date >= date('now') AND status = 'confirmed'
               ORDER BY date, time""",
        )
        return [self._row_to_reservation(r) for r in rows]

    async def cancel_reservation(self, reservation_id: str) -> None:
        await self.execute(
            """UPDATE reservations
               SET status = 'cancelled', cancelled_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (reservation_id,),
        )

    async def get_reservation(self, reservation_id: str) -> Reservation | None:
        row = await self.fetch_one(
            "SELECT * FROM reservations WHERE id = ?", (reservation_id,)
        )
        if not row:
            return None
        return self._row_to_reservation(row)

    # ── Blacklist ─────────────────────────────────────────────────────────

    async def add_to_blacklist(
        self, restaurant_id: str, restaurant_name: str, reason: str
    ) -> None:
        await self.execute(
            """INSERT OR REPLACE INTO blacklist
               (restaurant_id, restaurant_name, reason)
               VALUES (?, ?, ?)""",
            (restaurant_id, restaurant_name, reason),
        )

    async def is_blacklisted(self, restaurant_id: str) -> bool:
        row = await self.fetch_one(
            "SELECT 1 FROM blacklist WHERE restaurant_id = ?", (restaurant_id,)
        )
        return row is not None

    async def get_blacklist(self) -> list[dict]:
        return await self.fetch_all("SELECT * FROM blacklist")

    async def remove_from_blacklist(self, restaurant_id: str) -> None:
        await self.execute(
            "DELETE FROM blacklist WHERE restaurant_id = ?", (restaurant_id,)
        )

    # ── API Call Logging ──────────────────────────────────────────────────

    async def log_api_call(
        self,
        provider: str,
        endpoint: str,
        cost_cents: float,
        status_code: int,
        cached: bool,
    ) -> None:
        await self.execute(
            """INSERT INTO api_calls
               (provider, endpoint, cost_cents, status_code, cached)
               VALUES (?, ?, ?, ?, ?)""",
            (provider, endpoint, cost_cents, status_code, cached),
        )

    async def get_api_costs(self, days: int = 30) -> dict[str, float]:
        rows = await self.fetch_all(
            """SELECT provider, SUM(cost_cents) as total_cents
               FROM api_calls
               WHERE created_at >= datetime('now', ?)
               GROUP BY provider""",
            (f"-{days} days",),
        )
        return {r["provider"]: r["total_cents"] for r in rows}
