# ADR-003: Restaurant Wishlist Feature

**Date:** 2026-02-13
**Status:** Accepted

## Context

Users wanted a way to save restaurants they'd like to try in the future — the inverse of the blacklist. When near a wishlisted restaurant, it should surface in recommendations. Restaurants must come from search results (ensuring structured data with location coordinates), and users can attach free-text notes and comma-separated tags for filtering.

## Decisions

### 1. Schema: Separate `wishlist_tags` Table

**Decision:** Tags are stored in a normalized `wishlist_tags` join table rather than a JSON column or comma-separated TEXT field on the `wishlist` row.

**Rationale:**
- Enables efficient tag-based filtering via `JOIN` without parsing strings
- `UNIQUE(wishlist_id, tag)` prevents duplicate tags per item at the database level
- `ON DELETE CASCADE` from `wishlist_tags.wishlist_id → wishlist.id` ensures orphan tags are cleaned up automatically
- Tags are free-form strings (not an enum) — the tool docstring suggests common ones like "date night", "group dinner", "special occasion", "brunch"

### 2. Upsert with SELECT for ID Retrieval

**Decision:** `add_to_wishlist()` uses `INSERT ... ON CONFLICT(restaurant_id) DO UPDATE SET notes = excluded.notes`, then fetches the `id` with a separate `SELECT`.

**Rationale:**
- `cursor.lastrowid` is unreliable on upsert — SQLite returns 0 when the `ON CONFLICT` path fires
- The separate `SELECT` is safe because `restaurant_id` has a `UNIQUE` constraint
- After fetching the id, old tags are deleted and new ones inserted (full replacement semantics)

### 3. Tags Normalized to Lowercase

**Decision:** All tags are lowercased on insert (`tag.lower()`) and on query (`tag.lower()` in `get_wishlist`).

**Rationale:**
- Prevents duplicates like "Brunch" vs "brunch" from coexisting
- Case-insensitive filtering without `LOWER()` in SQL — simpler queries, index-friendly

### 4. Require Cache for Add, Not for Remove

**Decision:** `manage_wishlist(action="add")` requires the restaurant to exist in `restaurant_cache` (i.e., the user must search first). `action="remove"` tries cache lookup first but falls back to removal by name.

**Rationale:**
- Adding requires structured data (restaurant_id, coordinates) for recommendation scoring
- Removing should be forgiving — if the cache was cleared, users should still be able to un-wishlist by name
- Matches the `blacklist.py` pattern for `remove`, but is stricter than blacklist for `add` (blacklist allows adding uncached restaurants with name-as-id)

### 5. Recommendation Scoring: +15 Points

**Decision:** Wishlisted restaurants receive a +15 score boost in `_score_restaurant()`, with "On your wishlist" appended to reasons.

**Rationale:**
- +15 is meaningful (more than liked-cuisine +10) but doesn't override poor fit
- Less than would-return +25, reflecting that wishlist is aspirational vs. proven experience
- The existing distance penalty already handles spatial relevance — no additional geo logic needed
- Parameter defaults to `None` so existing callers are unaffected

### 6. Fix Pre-existing Teardown Error

**Decision:** Replaced `asyncio.get_event_loop().run_until_complete()` with `asyncio.run()` in `tests/integration/conftest.py`.

**Rationale:**
- Python 3.10+ deprecates `get_event_loop()` in threads without a running loop
- The session finalizer runs after pytest tears down all event loops, causing `RuntimeError`
- `asyncio.run()` creates a fresh loop, executes the coroutine, and cleans up

## Consequences

- 1191 tests pass with 100% branch coverage (up from 1150 in ADR-002)
- Two new MCP tools: `manage_wishlist` (add/remove) and `my_wishlist` (list/filter)
- Wishlisted restaurants surface higher in `get_recommendations` when nearby
- `my_wishlist` enriches output with rating/cuisine from `restaurant_cache` when available
- Tags enable future filtering workflows (e.g., "show me my brunch wishlist")
