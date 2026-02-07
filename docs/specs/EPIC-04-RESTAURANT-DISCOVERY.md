# EPIC-04: Restaurant Discovery (Google Places)

## Goal
Build the restaurant search capability using Google Places API (New) with aggressive caching to minimize API costs. Users should be able to say "Find me Italian near home" and get relevant, rated results.

## Success Criteria
- Search returns restaurants filtered by cuisine, location, price, and rating
- Results include Google ratings, review counts, and price level
- Restaurant metadata is cached for 24 hours to minimize API calls
- Walking distance from user's saved locations is calculated
- Blacklisted and preference-filtered restaurants are excluded
- API costs are tracked per call

---

## Story 4.1: Google Places Client (Cost-Optimized)

**As a** developer
**I want** a Google Places API client that minimizes cost per request
**So that** the user pays as little as possible for restaurant discovery

### Tasks

- [ ] **4.1.1** Create `src/clients/google_places.py` with `GooglePlacesClient`:
  - Use the **Places API (New)** (`places.googleapis.com`) — it's the current version
  - Use **field masks** to request only needed fields (this directly reduces cost)
  - Base URL: `https://places.googleapis.com/v1/places:searchText`
  - Auth: `X-Goog-Api-Key` header

- [ ] **4.1.2** Implement `search_nearby` method:
  ```python
  async def search_nearby(
      self,
      query: str,                    # "Italian restaurant"
      lat: float,
      lng: float,
      radius_meters: int = 1500,     # ~15 min walk
      max_results: int = 10,
  ) -> list[dict]:
  ```
  - Use `searchText` endpoint with `locationBias` (circular area)
  - **Field mask** (critical for cost): Only request:
    ```
    places.id,
    places.displayName,
    places.formattedAddress,
    places.location,
    places.rating,
    places.userRatingCount,
    places.priceLevel,
    places.types,
    places.primaryType,
    places.regularOpeningHours,
    places.websiteUri,
    places.nationalPhoneNumber
    ```
  - **Cost**: Text Search = $0.032 per request (with field mask for basic fields)
  - Without field mask it's $0.035+. Field masks also reduce payload size.

- [ ] **4.1.3** Implement `get_place_details` method (for cache misses only):
  ```python
  async def get_place_details(self, place_id: str) -> dict:
  ```
  - Use `places/{place_id}` endpoint
  - Field mask: same fields as search + `reviews` and `editorialSummary`
  - **Cost**: $0.017 per request (Place Details basic) — only call when cache is stale
  - This is the most expensive call — cache aggressively

- [ ] **4.1.4** Implement cost tracking:
  - After every API call, log to `api_calls` table:
    - provider: "google_places"
    - endpoint: "searchText" or "getPlaceDetails"
    - cost_cents: estimated cost
    - status_code, cached (bool)

- [ ] **4.1.5** Implement response parsing:
  - Parse Places API (New) JSON response into `Restaurant` model
  - Map `priceLevel` enum (PRICE_LEVEL_FREE through PRICE_LEVEL_VERY_EXPENSIVE) to 1-4
  - Extract cuisine from `types` array (map Google types to our Cuisine enum)
  - Handle missing fields gracefully (not all restaurants have all data)

---

## Story 4.2: Restaurant Search Cache

**As a** developer
**I want** restaurant metadata cached in SQLite for 24 hours
**So that** repeated searches don't hit Google Places API

### Tasks

- [ ] **4.2.1** Implement cache-first search flow in `GooglePlacesClient`:
  ```
  1. Check restaurant_cache for matching restaurants near location
  2. If fresh cache hits exist (< 24 hours old), return those
  3. If not enough results or cache is stale, call Google Places API
  4. Store/update results in restaurant_cache
  5. Return combined results
  ```

- [ ] **4.2.2** Implement `cache_restaurant` method:
  - Upsert into `restaurant_cache` table
  - Store cuisine as JSON array
  - Store hours as JSON
  - Set `cached_at` to now

- [ ] **4.2.3** Implement `search_cache` method:
  - Search by cuisine, location (bounding box), and price level
  - Filter out entries older than 24 hours
  - Return matching `Restaurant` objects

- [ ] **4.2.4** Track cache hit/miss ratio in API logging:
  - Log `cached=True` when serving from cache
  - Log `cached=False` with cost when calling API

---

## Story 4.3: Search Restaurants MCP Tool

**As a** user
**I want** to search for restaurants matching my criteria through Claude
**So that** I get curated results aligned with my preferences

### Tasks

- [ ] **4.3.1** Implement the full `search_restaurants` tool in `src/tools/search.py`:
  ```python
  @mcp.tool()
  async def search_restaurants(
      cuisine: str | None = None,
      location: str = "home",
      party_size: int = 2,
      price_max: int | None = None,
      ambience: str | None = None,
      outdoor_seating: bool = False,
      query: str | None = None,
      max_results: int = 5,
  ) -> str:
      """
      Search for restaurants matching your criteria near a location.
      Automatically applies your dietary restrictions, cuisine preferences,
      minimum rating threshold, and blacklist.

      Args:
          cuisine: Type of food, e.g. "italian", "mexican", "sushi", "seafood".
                   Leave empty to search all cuisines.
          location: Where to search near. Use "home", "work", or a specific
                    NYC address like "123 Broadway, New York".
          party_size: Number of diners (used to filter restaurants that can accommodate).
          price_max: Maximum price level 1-4 ($-$$$$). Leave empty to use your
                     saved price preferences.
          ambience: Desired vibe: "quiet", "moderate", or "lively". Leave empty
                    for no preference.
          outdoor_seating: Set to true if outdoor seating is specifically desired.
          query: Free-text search query for specific restaurants or features,
                 e.g. "rooftop bar", "private dining room", "Carbone".
          max_results: Maximum number of restaurants to return (default 5, max 10).

      Returns:
          Formatted list of matching restaurants with:
          - Name, address, and walking distance from your location
          - Google rating and review count
          - Price level
          - Cuisine type
          - Whether available on Resy, OpenTable, or both (if known)

      Example:
          search_restaurants(cuisine="italian", location="home", price_max=3)
          → Returns Italian restaurants near home, up to $$$, rated above your threshold
      """
  ```

- [ ] **4.3.2** Implement the search flow:
  1. Resolve `location` to lat/lng:
     - "home" / "work" → look up in `locations` table
     - Address string → geocode via Google (cache the result)
  2. Build search query:
     - Combine cuisine + "restaurant" + location context
     - E.g., "Italian restaurant" with locationBias centered on home
  3. Call `GooglePlacesClient.search_nearby()` (cache-first)
  4. Apply filters:
     - Exclude blacklisted restaurants
     - Exclude cuisines the user avoids
     - Filter by `rating_threshold` from preferences
     - Filter by `price_max` (or user's saved price preferences)
  5. Sort by rating (descending), then distance
  6. Format results as human-readable string

- [ ] **4.3.3** Implement walking distance estimation:
  - **Cost-free approach**: Calculate straight-line (haversine) distance between user location and restaurant
  - Estimate walking time: `distance_km / 0.08` (average walking speed ~5 km/h → 80m/min)
  - This avoids Google Distance Matrix API calls ($5/1000)
  - Display as "~X min walk" in results

- [ ] **4.3.4** Format search results for Claude:
  - Return structured text that Claude can present conversationally
  - Include: name, rating (X.X/5), price level ($-$$$$), address, walk time, cuisine
  - Flag if restaurant has known Resy/OpenTable IDs (from cache)
  - Example output:
    ```
    Found 3 Italian restaurants near home:

    1. Carbone (4.7★, $$$$) - ~8 min walk
       181 Thompson St, New York
       Cuisine: Italian | Available on: Resy

    2. L'Artusi (4.5★, $$$) - ~12 min walk
       228 W 10th St, New York
       Cuisine: Italian | Available on: OpenTable

    3. Via Carota (4.6★, $$$) - ~6 min walk
       51 Grove St, New York
       Cuisine: Italian
    ```

---

## Story 4.4: Cuisine Type Mapping

**As a** developer
**I want** Google Places types mapped to our cuisine categories
**So that** cuisine filtering works accurately

### Tasks

- [ ] **4.4.1** Create `src/clients/cuisine_mapper.py`:
  - Map Google Places `types` (e.g., "italian_restaurant", "mexican_restaurant") to our `Cuisine` enum
  - Google types reference: `primaryType` field has values like "italian_restaurant", "sushi_restaurant", etc.
  - Handle ambiguous types: "restaurant" alone → look at `editorialSummary` or name
  - Fallback: if no specific cuisine type, classify as "OTHER"

- [ ] **4.4.2** Build a lookup table:
  ```python
  GOOGLE_TYPE_TO_CUISINE = {
      "italian_restaurant": "italian",
      "mexican_restaurant": "mexican",
      "japanese_restaurant": "japanese",
      "korean_restaurant": "korean",
      "chinese_restaurant": "chinese",
      "thai_restaurant": "thai",
      "indian_restaurant": "indian",
      "mediterranean_restaurant": "mediterranean",
      "french_restaurant": "french",
      "american_restaurant": "american",
      "seafood_restaurant": "seafood",
      "steak_house": "steakhouse",
      "pizza_restaurant": "pizza",
      "sushi_restaurant": "sushi",
      # ... extend as needed
  }
  ```

---

## Story 4.5: Search by Restaurant Name

**As a** user
**I want** to search for a specific restaurant by name
**So that** I can quickly find and book a place I already know

### Tasks

- [ ] **4.5.1** When `query` parameter is provided and looks like a restaurant name:
  - Use Google Places `searchText` with the restaurant name + "New York"
  - Return the single best match (or top 3 if ambiguous)
  - Cache the result

- [ ] **4.5.2** Check cache first:
  - Search `restaurant_cache` by name (case-insensitive LIKE match)
  - If found and fresh, skip API call

---

## Dependencies
- EPIC-01 (server)
- EPIC-02 (database + models)
- EPIC-03 (preferences for filtering)

## Blocked By
- EPIC-02 (need Restaurant model and cache table)
- EPIC-03 (need user preferences for filtering)

## Blocks
- EPIC-05 (Resy needs restaurants to check availability for)
- EPIC-06 (OpenTable needs restaurants)
- EPIC-07 (recommendations build on search)

## Cost Considerations

**This is the highest-cost EPIC. Optimization is critical.**

| Operation | Cost | Frequency | Monthly Estimate |
|-----------|------|-----------|-----------------|
| Text Search (with field mask) | $0.032/call | ~3-5 per session | $2-5/month |
| Place Details | $0.017/call | Only cache misses | $1-3/month |
| Geocoding (address→coords) | $0.005/call | Once per address | ~$0.01 |

**Cost-saving strategies implemented:**
1. **Field masks** on every request — only request fields we use
2. **24-hour cache** on restaurant metadata — most queries hit cache
3. **Haversine distance** instead of Distance Matrix API — saves $5/1000 calls
4. **No photo requests** — photos are the most expensive Places API feature ($7/1000)
5. **Cache geocoding results** — home/work addresses don't change

**Estimated monthly cost for moderate use (3-4 searches/day): $3-8**

## Technical Notes
- Google Places API (New) uses `places.googleapis.com` — not the legacy `maps.googleapis.com`
- Field masks are specified via `X-Goog-FieldMask` header
- Text Search with `locationBias` is more cost-effective than Nearby Search for our use case
- The `primaryType` field is the best cuisine indicator (vs the `types` array which has generic types)
- Rate limit: 600 requests per minute (more than enough for personal use)
- Always include `languageCode: "en"` for consistent results
