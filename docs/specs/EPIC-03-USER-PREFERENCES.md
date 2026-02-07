# EPIC-03: User Preferences & People Management

## Goal
Provide MCP tools that let the user set up their profile, dietary restrictions, cuisine preferences, saved locations, dining companions, and groups — all through natural conversation with Claude.

## Success Criteria
- User can configure all preferences through Claude conversation
- People and groups can be created, updated, and deleted
- Group dietary restrictions are automatically merged from members
- Preferences are persisted in SQLite and loaded on every server start
- Claude can query preferences to inform restaurant search

---

## Story 3.1: User Profile Setup Tool

**As a** user
**I want** to set up my restaurant preferences through conversation
**So that** Claude knows my tastes without me repeating them

### Tasks

- [ ] **3.1.1** Create `src/tools/preferences.py` with `setup_preferences` tool:
  ```python
  @mcp.tool()
  async def setup_preferences(
      name: str,
      home_address: str | None = None,
      work_address: str | None = None,
      dietary_restrictions: list[str] | None = None,
      favorite_cuisines: list[str] | None = None,
      cuisines_to_avoid: list[str] | None = None,
      price_levels: list[int] | None = None,
      noise_preference: str = "moderate",
      seating_preference: str = "no_preference",
      max_walk_minutes: int = 15,
      default_party_size: int = 2,
      rating_threshold: float = 4.0,
  ) -> str:
      """
      Set up or update your restaurant preferences. Call this when the user
      first configures the assistant or wants to change their profile.

      Args:
          name: User's first name
          home_address: Home address for "near home" searches. Full street address in NYC.
          work_address: Work address for "near work" searches. Full street address in NYC.
          dietary_restrictions: List like ["no_red_meat", "nut_allergy", "vegetarian", "gluten_free"]
          favorite_cuisines: Cuisines you love, e.g. ["italian", "mexican", "korean"]
          cuisines_to_avoid: Cuisines you dislike, e.g. ["fast_food"]
          price_levels: Acceptable price levels 1-4 ($-$$$$), e.g. [2, 3] for $$ and $$$
          noise_preference: "quiet", "moderate", or "lively"
          seating_preference: "indoor", "outdoor", or "no_preference"
          max_walk_minutes: Maximum walking time from location (default 15)
          default_party_size: Usual party size (default 2)
          rating_threshold: Minimum Google rating to show (default 4.0)

      Returns:
          Confirmation message with saved preferences summary.
      """
  ```

- [ ] **3.1.2** When `home_address` or `work_address` is provided, geocode it:
  - Use Google Geocoding API (or extract lat/lng from a Places text search)
  - Store in `locations` table with name="home" or name="work"
  - **Cost optimization**: Geocoding is ~$5/1000 requests — cache the result, it won't change

- [ ] **3.1.3** Save all preference fields to their respective tables (upsert pattern):
  - `user_preferences` — single row upsert
  - `user_dietary` — clear and re-insert
  - `cuisine_preferences` — clear and re-insert
  - `price_preferences` — clear and re-insert

---

## Story 3.2: View & Update Preferences

**As a** user
**I want** to view and selectively update my preferences
**So that** I can tweak settings without redoing full setup

### Tasks

- [ ] **3.2.1** Create `get_my_preferences` tool:
  ```python
  @mcp.tool()
  async def get_my_preferences() -> str:
      """
      Show all your current restaurant preferences including dietary restrictions,
      favorite cuisines, saved locations, and dining defaults.

      Returns a formatted summary of all preferences.
      """
  ```
  - Query all preference tables
  - Return a human-readable formatted string

- [ ] **3.2.2** Create `update_preferences` tool:
  ```python
  @mcp.tool()
  async def update_preferences(
      dietary_restrictions: list[str] | None = None,
      add_favorite_cuisine: str | None = None,
      remove_favorite_cuisine: str | None = None,
      add_avoid_cuisine: str | None = None,
      noise_preference: str | None = None,
      seating_preference: str | None = None,
      rating_threshold: float | None = None,
      default_party_size: int | None = None,
      max_walk_minutes: int | None = None,
  ) -> str:
      """
      Update specific preferences without resetting everything.
      Only provided fields are changed; everything else stays the same.

      Returns confirmation of what was changed.
      """
  ```
  - Only update fields that are not None
  - For dietary_restrictions, replace the full list (not append)
  - For cuisines, add/remove individually

---

## Story 3.3: People Management

**As a** user
**I want** to save my dining companions and their dietary needs
**So that** Claude considers everyone's restrictions when recommending restaurants

### Tasks

- [ ] **3.3.1** Create `src/tools/people.py` with `manage_person` tool:
  ```python
  @mcp.tool()
  async def manage_person(
      name: str,
      action: str = "add",
      dietary_restrictions: list[str] | None = None,
      no_alcohol: bool = False,
      notes: str | None = None,
  ) -> str:
      """
      Add, update, or remove a dining companion.

      Args:
          name: Person's name (case-insensitive matching)
          action: "add" to create/update, "remove" to delete
          dietary_restrictions: Their restrictions, e.g. ["nut_allergy", "vegan"]
          no_alcohol: True if they don't drink alcohol
          notes: Any other notes, e.g. "Prefers window seats"

      Examples:
          manage_person("Alice", dietary_restrictions=["nut_allergy", "seed_allergy"])
          manage_person("Bob", no_alcohol=True, notes="Doesn't drink")
          manage_person("Alice", action="remove")

      Returns:
          Confirmation of the action taken.
      """
  ```
  - "add" should upsert (create if new, update if exists)
  - For dietary_restrictions on update, replace the full list
  - "remove" cascades to `people_dietary` and `group_members`

- [ ] **3.3.2** Create `list_people` tool:
  ```python
  @mcp.tool()
  async def list_people() -> str:
      """
      List all saved dining companions with their dietary restrictions and notes.

      Returns formatted list of all people and their preferences.
      """
  ```

---

## Story 3.4: Group Management

**As a** user
**I want** to create named groups of people (e.g., "work_team", "family")
**So that** I can quickly search for restaurants suitable for the whole group

### Tasks

- [ ] **3.4.1** Create `manage_group` tool:
  ```python
  @mcp.tool()
  async def manage_group(
      group_name: str,
      action: str = "add",
      members: list[str] | None = None,
  ) -> str:
      """
      Create, update, or remove a named group of dining companions.

      Args:
          group_name: Name for the group, e.g. "work_team", "family", "college_friends"
          action: "add" to create/update, "remove" to delete the group
          members: List of people names (must already be saved via manage_person)

      Examples:
          manage_group("work_team", members=["Nora", "David", "Behrooz", "Andrej"])
          manage_group("family", members=["Wife"])
          manage_group("work_team", action="remove")

      Returns:
          Confirmation with group details and merged dietary restrictions.
      """
  ```
  - Validate all member names exist in `people` table
  - On "add", upsert group and replace all members
  - On success, compute and display merged dietary restrictions for the group

- [ ] **3.4.2** Create `list_groups` tool:
  ```python
  @mcp.tool()
  async def list_groups() -> str:
      """
      List all saved groups with their members and merged dietary restrictions.

      Returns formatted list of groups with member details.
      """
  ```

- [ ] **3.4.3** Implement `get_group_dietary_restrictions` in the database layer:
  - Query all members of a group
  - Union all their dietary restrictions
  - Include the user's own restrictions
  - Return deduplicated list

---

## Story 3.5: Blacklist Management

**As a** user
**I want** to blacklist restaurants I never want suggested again
**So that** Claude respects my hard no's

### Tasks

- [ ] **3.5.1** Create blacklist tool:
  ```python
  @mcp.tool()
  async def manage_blacklist(
      restaurant_name: str,
      action: str = "add",
      reason: str | None = None,
  ) -> str:
      """
      Add or remove restaurants from your blacklist.
      Blacklisted restaurants will never appear in search results or recommendations.

      Args:
          restaurant_name: Name of the restaurant
          action: "add" to blacklist, "remove" to un-blacklist
          reason: Why you're blacklisting (for your records)

      Returns:
          Confirmation of the action.
      """
  ```
  - For "add": look up restaurant in cache by name, or store name-only if not cached
  - For "remove": delete from blacklist table

---

## Dependencies
- EPIC-01 (server skeleton)
- EPIC-02 (database layer)

## Blocked By
- EPIC-02

## Blocks
- EPIC-04 (search uses preferences for filtering)
- EPIC-07 (recommendations use preferences)

## Cost Considerations
- Geocoding home/work address: ~$0.005 per call (one-time per address)
- All other operations are local SQLite — zero API cost

## Technical Notes
- All tool docstrings are detailed because Claude uses them as instructions
- Name matching for people/groups should be case-insensitive
- Preferences are queried at the start of every search/recommendation to apply filters
- The `setup_preferences` tool is designed for first-run conversation flow:
  Claude asks questions → user answers → Claude calls setup_preferences with all answers
- Geocoding for addresses: use Google Geocoding API or `places.searchText` with the address
  to get lat/lng. Cache permanently — addresses don't change.
