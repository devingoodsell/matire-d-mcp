# EPIC-07: Intelligence & Recommendations

## Goal
Add visit history tracking, weather awareness, recency-based filtering, and personalized recommendations so that the assistant learns from your dining patterns and makes increasingly relevant suggestions.

## Success Criteria
- Visits and reviews are recorded and inform future recommendations
- Weather data prevents outdoor seating suggestions in bad weather
- Recent cuisines are deprioritized to encourage variety
- Group dining merges all members' restrictions
- Recommendations improve over time based on review history

---

## Story 7.1: Visit History & Review Tools

**As a** user
**I want** to log visits and reviews
**So that** Claude learns what I like and what to avoid

### Tasks

- [ ] **7.1.1** Create `src/tools/history.py` with `log_visit` tool:
  ```python
  @mcp.tool()
  async def log_visit(
      restaurant_name: str,
      date: str | None = None,
      party_size: int = 2,
      companions: list[str] | None = None,
      cuisine: str | None = None,
  ) -> str:
      """
      Log a restaurant visit (for places booked outside the system).
      Visits booked through this assistant are logged automatically.

      Args:
          restaurant_name: Name of the restaurant you visited
          date: Date of visit, e.g. "2026-02-10" or "last Tuesday" (default: today)
          party_size: Number of diners
          companions: Names of who you dined with, e.g. ["Alice", "Bob"]
          cuisine: Type of cuisine, e.g. "italian", "mexican"

      Returns:
          Confirmation with visit ID for adding a review.
      """
  ```
  - Try to match restaurant name to cached restaurant (for Google Place ID)
  - If no match, store with name only (source="manual")
  - Store cuisine if provided (for recency tracking even without Google Place ID)

- [ ] **7.1.2** Create `rate_visit` tool:
  ```python
  @mcp.tool()
  async def rate_visit(
      restaurant_name: str,
      would_return: bool,
      overall_rating: int | None = None,
      noise_level: str | None = None,
      dishes: list[dict] | None = None,
      notes: str | None = None,
  ) -> str:
      """
      Rate a restaurant you recently visited. Used to improve future recommendations.

      Args:
          restaurant_name: Name of the restaurant
          would_return: True if you'd go back, False if not
          overall_rating: 1-5 stars (optional)
          noise_level: "quiet", "moderate", or "loud" — helps calibrate future recs
          dishes: List of dishes with ratings, e.g. [{"name": "cacio e pepe", "rating": 5, "order_again": true}]
          notes: Any additional notes, e.g. "Great for date night, ask for corner table"

      Returns:
          Confirmation that the review was saved.
      """
  ```
  - Find the most recent visit for this restaurant
  - Save review to `visit_reviews`
  - Save dish reviews to `dish_reviews` if provided
  - If `would_return` is False, optionally ask if they want to blacklist

- [ ] **7.1.3** Create `visit_history` tool:
  ```python
  @mcp.tool()
  async def visit_history(
      days: int = 90,
      cuisine: str | None = None,
  ) -> str:
      """
      Show your recent restaurant visit history.

      Args:
          days: How many days back to look (default 90)
          cuisine: Filter by cuisine type (optional)

      Returns:
          Formatted list of recent visits with dates, ratings, and notes.
      """
  ```

---

## Story 7.2: Weather-Aware Recommendations

**As a** developer
**I want** weather data integrated into search and recommendations
**So that** outdoor seating isn't suggested in rain/cold

### Tasks

- [ ] **7.2.1** Create `src/clients/weather.py` with `WeatherClient`:
  ```python
  class WeatherClient:
      """OpenWeatherMap client for weather-aware dining decisions."""
      BASE_URL = "https://api.openweathermap.org/data/2.5"

      def __init__(self, api_key: str):
          self.api_key = api_key
          self.client = httpx.AsyncClient()
          self._cache: dict[str, tuple[dict, datetime]] = {}

      async def get_weather(self, lat: float, lng: float, date: str | None = None) -> WeatherInfo:
          """
          Get weather for a location and date.
          Uses current weather for today, forecast for future dates.
          Caches for 1 hour to minimize API calls.
          """
  ```

- [ ] **7.2.2** Define `WeatherInfo` model:
  ```python
  class WeatherInfo(BaseModel):
      temperature_f: float
      condition: str             # "clear", "clouds", "rain", "snow"
      description: str           # "light rain", "overcast clouds"
      outdoor_suitable: bool     # True if temp > 55°F and no rain/snow
      wind_mph: float
      humidity: int
  ```

- [ ] **7.2.3** Implement weather fetching:
  - **Today**: Use `GET /weather?lat={lat}&lon={lng}&units=imperial`
  - **Future (up to 5 days)**: Use `GET /forecast?lat={lat}&lon={lng}&units=imperial`
  - Parse response into `WeatherInfo`
  - Cache result for 1 hour (in-memory dict with timestamp)
  - **Cost**: Free tier = 1000 calls/day (more than enough)

- [ ] **7.2.4** Implement `outdoor_suitable` logic:
  ```python
  def _is_outdoor_suitable(self, data: dict) -> bool:
      temp = data["main"]["temp"]  # Fahrenheit
      condition = data["weather"][0]["main"].lower()
      wind = data["wind"]["speed"]

      return (
          temp >= 55 and temp <= 95 and
          condition not in ("rain", "snow", "thunderstorm", "drizzle") and
          wind < 20  # mph
      )
  ```

- [ ] **7.2.5** Integrate weather into `search_restaurants` tool:
  - If `outdoor_seating=True` is requested, check weather first
  - If weather is bad, inform user: "Note: Rain expected Saturday. Showing indoor options."
  - Automatically flip `outdoor_seating` to False in bad weather
  - If no API key configured, skip weather check silently

---

## Story 7.3: Recency-Based Filtering

**As a** developer
**I want** recently visited cuisines deprioritized in recommendations
**So that** the user gets variety in their dining

### Tasks

- [ ] **7.3.1** Implement recency scoring in search/recommendations:
  ```python
  async def get_recency_penalties(self, days: int = 14) -> dict[str, float]:
      """
      Returns a penalty score (0-1) for each cuisine based on recent visits.
      Higher penalty = visited more recently.

      Example:
          {"italian": 0.8, "mexican": 0.3}  # Italian visited 2 days ago, Mexican 10 days ago
      """
  ```
  - Query `visits` table for last N days
  - Map each visit to its cuisine
  - Calculate penalty: `1.0 - (days_since_visit / window_days)`
  - Cuisines not visited recently get 0 penalty

- [ ] **7.3.2** Apply recency to search results:
  - When sorting/ranking search results, apply penalty to score
  - Don't completely exclude recent cuisines — just rank them lower
  - Display note if a cuisine is being deprioritized: "You had Italian 2 days ago — showing other options first"

- [ ] **7.3.3** Add `exclude_recent_days` parameter to recommendations:
  - Default: 7 days for same restaurant, 3 days for same cuisine
  - Same restaurant: hard exclude (don't show at all)
  - Same cuisine: soft deprioritize (show lower in list)

---

## Story 7.4: Personalized Recommendations Tool

**As a** user
**I want** Claude to proactively suggest restaurants based on my history
**So that** I discover new places that match my taste

### Tasks

- [ ] **7.4.1** Create `get_recommendations` tool:
  ```python
  @mcp.tool()
  async def get_recommendations(
      occasion: str | None = None,
      party_size: int = 2,
      location: str = "home",
      group: str | None = None,
      exclude_recent_days: int = 14,
  ) -> str:
      """
      Get personalized restaurant recommendations based on your history,
      preferences, and current context (weather, recent visits).

      Args:
          occasion: The type of dining occasion. Options:
                    "date_night" - romantic, quieter spots
                    "casual" - relaxed, neighborhood places
                    "group_dinner" - accommodates larger parties
                    "special" - high-end, celebration-worthy
                    "quick" - fast, nearby options
                    Leave empty for general recommendations.
          party_size: Number of diners
          location: "home", "work", or an address
          group: Name of a saved group — their restrictions will be applied
          exclude_recent_days: Don't recommend places visited in the last N days

      Returns:
          Curated list of 3-5 restaurants with reasons for each recommendation.

      Examples:
          get_recommendations(occasion="date_night")
          get_recommendations(group="work_team", occasion="group_dinner", location="work")
      """
  ```

- [ ] **7.4.2** Implement recommendation scoring algorithm:
  ```python
  def score_restaurant(self, restaurant, context) -> float:
      score = 0.0

      # Base: Google rating (0-5 → 0-50 points)
      score += restaurant.rating * 10

      # Cuisine preference bonus
      if restaurant.cuisine in user_favorites:
          score += 20
      elif restaurant.cuisine in user_likes:
          score += 10
      elif restaurant.cuisine in user_avoids:
          score -= 100  # Effectively excludes

      # Recency penalty
      score -= recency_penalty * 30

      # "Would return" bonus from past visits
      if past_reviews and past_reviews.would_return:
          score += 25

      # Occasion matching
      if occasion == "date_night" and restaurant.ambiance == "quiet":
          score += 15
      if occasion == "group_dinner" and can_accommodate:
          score += 10

      # Distance penalty (closer is better)
      score -= walk_minutes * 0.5

      return score
  ```

- [ ] **7.4.3** Format recommendations with reasons:
  ```
  Here are my picks for date night:

  1. Via Carota (4.6★, $$$) - ~6 min walk
     Italian | Known for quiet atmosphere
     ↳ You rated it 5/5 last time. Your wife loved the cacio e pepe.

  2. The Musket Room (4.5★, $$$$) - ~14 min walk
     New Zealand-inspired | Romantic setting
     ↳ Matches your love of creative cuisine. No nut-heavy dishes (safe for your wife).

  3. Lilia (4.7★, $$$) - ~18 min walk
     Italian | Open kitchen concept
     ↳ Highly rated, you haven't tried it yet. Pasta-focused menu.
  ```

---

## Story 7.5: Group Dining Search

**As a** user
**I want** to search for restaurants suitable for a specific group
**So that** everyone's dietary needs are met

### Tasks

- [ ] **7.5.1** Create `search_for_group` tool:
  ```python
  @mcp.tool()
  async def search_for_group(
      group_name: str,
      location: str = "work",
      date: str = "today",
      time: str = "18:00",
      cuisine: str | None = None,
  ) -> str:
      """
      Search for restaurants suitable for a saved group.
      Automatically merges all members' dietary restrictions and
      finds restaurants that work for everyone.

      Args:
          group_name: Name of the saved group (e.g., "work_team", "family")
          location: Where to search near
          date: Date for the dinner
          time: Preferred time
          cuisine: Specific cuisine (optional)

      Returns:
          Restaurant recommendations with notes on dietary compatibility.
          Example: "All 4 work_team members can eat here. Note: Nora doesn't drink,
                    so I picked places with good mocktail programs."
      """
  ```

- [ ] **7.5.2** Implement group-aware search:
  1. Load group members and merge all dietary restrictions
  2. Set party_size = number of members + user
  3. Search restaurants using merged restrictions as filters
  4. Add compatibility notes to results
  5. If a member has `no_alcohol=True`, note that in recommendations

---

## Dependencies
- EPIC-01 (server)
- EPIC-02 (data layer — visits, reviews tables)
- EPIC-03 (preferences, people, groups)
- EPIC-04 (restaurant search)

## Blocked By
- EPIC-02 (visit/review models and DB methods)
- EPIC-03 (people and groups)
- EPIC-04 (search infrastructure)

## Blocks
- Nothing — this is an enhancement layer

## Cost Considerations
- OpenWeatherMap: **Free** (1000 calls/day free tier, we'll use ~5-10/day)
- All recommendation logic is local computation — zero API cost
- Visit history, reviews, and scoring are all SQLite queries

## Technical Notes
- Weather caching: 1 hour in-memory is fine — weather doesn't change that fast
- Recency is a soft signal, not a hard filter — users should be able to override
- Recommendation scoring is deterministic (not ML) — simple weighted formula
- Group dietary merging: union of all restrictions + user's own
- Occasion mapping to restaurant attributes:
  - "date_night" → quiet ambiance, $$$ or $$$$, rating > 4.3
  - "casual" → moderate ambiance, $$ or $$$
  - "group_dinner" → can accommodate party size, not too quiet
  - "special" → $$$$, rating > 4.5
  - "quick" → closest distance, $$ or less
- The recommendation algorithm should be simple and explainable — no black box ML.
  Users trust recommendations they understand.
