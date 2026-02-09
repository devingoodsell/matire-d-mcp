# NYC Restaurant Reservation Assistant

An MCP-based personal assistant that discovers restaurants, checks availability, and books reservations through natural conversation with Claude.

> **Note:** Three MCP servers for Resy reservations already exist in the ecosystem ([see Prior Art](#prior-art)), but none combine Google Places discovery, weather integration, dining companion tracking, and real booking across both Resy **and** OpenTable — that gap is this project's value proposition.

## What It Does

```
You: "Book me a quiet Italian place near home for Saturday at 7"

Claude: I found 3 Italian spots within 10 min walk of your home:
        1. Carbone (4.7★) - 6:30 PM, 9:15 PM on Resy
        2. L'Artusi (4.5★) - 7:00 PM on OpenTable
        3. Via Carota (4.6★) - 8:45 PM on Resy

        Your wife has a nut allergy - I've verified these don't
        have nut-heavy menus. Which would you like?

You: "Carbone at 6:30"

Claude: ✓ Booked! Carbone, Saturday 6:30 PM, 2 people
        Confirmation: RESY-ABC123
        Add to Google Calendar: https://calendar.google.com/calendar/render?...
```

## Key Features

| Feature | Description |
|---------|-------------|
| **Smart Discovery** | Google Places ratings + reviews, filtered by your preferences |
| **Multi-Platform Booking** | Resy (automated), OpenTable (automated) |
| **Dietary Awareness** | Remembers your restrictions and your dining companions' |
| **Group Dining** | Save people (with their restrictions) and groups for easy booking |
| **Recency Tracking** | Won't suggest Mexican if you had it yesterday |
| **Weather Aware** | No outdoor seating suggestions in winter/rain |
| **Visit History** | Tracks where you've been, resurfaces favorites |
| **Calendar Sync** | Add reservations to Google Calendar with one click |
| **Cost Tracking** | Monitor your API usage costs |
| **Resilient** | Retry with backoff, circuit breakers, graceful fallbacks |

## Quick Start

### 1. Prerequisites

- Python 3.11+
- [Claude Desktop](https://claude.ai/download) installed
- Google Cloud API key (Places API enabled)

### 2. Clone & Install

```bash
git clone <repo>
cd restaurant-mcp
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
```

### 3. Run Setup

The interactive setup encrypts all secrets into the local database and generates your Claude Desktop config:

```bash
source .venv/bin/activate
python -m src.setup
```

You will be prompted for:
- **Google API Key** (required) — Google Cloud Console → Places API (New)
- **OpenWeather API Key** (optional) — openweathermap.org (free tier: 1000/day)
- **Resy credentials** (optional) — for automated Resy booking
- **OpenTable session** (optional) — CSRF token + browser cookies for OpenTable booking

The script outputs a ready-to-paste Claude Desktop config with a single `RESTAURANT_MCP_KEY` env var.

<details>
<summary><b>Extracting OpenTable Session Values</b></summary>

OpenTable's API requires authenticated browser session cookies to bypass bot protection. Without this step, OpenTable availability checks and bookings will fail.

During `python -m src.setup`, when you provide an OpenTable email you'll be prompted for:
- **OpenTable x-csrf-token** — from browser DevTools
- **OpenTable Cookie header** — from browser DevTools

**How to get these values (re-run setup when cookies expire, typically every few days):**

1. Open https://www.opentable.com in Chrome and **log in**
2. Open DevTools (`Cmd+Option+I` on macOS, `F12` on Windows)
3. Go to the **Network** tab
4. Navigate to any restaurant page (e.g. search for "Carbone" and click it)
5. In the Network list, click any request to `www.opentable.com`
6. Find any request to a `/dapi/` endpoint (POST) and copy the **`x-csrf-token`** header value
7. In the **Headers** tab, copy the full **`Cookie`** header value
8. Save the cookie value into a temp file that can be referenced in the `src.setup` command. This is due to the paste size being too large.

> **Why is this needed?** OpenTable uses Cloudflare bot protection that blocks plain HTTP requests. By storing your browser's session cookies, the MCP server can make API calls as your authenticated session. The cookies are encrypted at rest using the same Fernet encryption as all other credentials.
</details>

### 4. Configure Claude Desktop

Copy the JSON output from step 3 into your Claude Desktop MCP config file:

- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

The config should look like:

```json
{
  "mcpServers": {
    "restaurant": {
      "command": "/path/to/restaurant-mcp/.venv/bin/python",
      "args": ["-m", "src"],
      "cwd": "/path/to/restaurant-mcp",
      "env": {
        "RESTAURANT_MCP_KEY": "your-generated-master-key"
      }
    }
  }
}
```

Replace paths with the actual paths from the setup output.

### 5. Restart Claude Desktop

Quit and reopen Claude Desktop. You should see the restaurant tools available (hammer icon in the chat input).

### 6. First Run — Set Up Your Profile

Start a conversation with Claude:

```
You: "Help me set up my restaurant preferences"

Claude: Let's get you set up! First, what's your home address?
        (I'll use this as "near home" when you search)

You: "123 Main St, New York, NY 10001"

Claude: Got it. Where do you work?

You: "456 Park Ave, New York, NY 10022"

Claude: What are your favorite cuisines?

You: "Italian, Japanese, Mexican"

Claude: Any dietary restrictions?

You: "None for me"

Claude: ✓ Profile saved! You're all set.
```

### 7. Add Dining Companions

```
You: "Add my wife — she has a nut allergy and a seed allergy"

Claude: ✓ Saved! I'll remember her allergies when searching restaurants.

You: "Create a group called 'date night' with my wife"

Claude: ✓ Group 'date night' created. Merged restrictions: nut allergy, seed allergy.
```

### Security Model

| Layer | Protection |
|-------|-----------|
| **Setup script** | `python -m src.setup` — passwords entered via `getpass` (not echoed), never in chat |
| **Single secret** | One master key (`RESTAURANT_MCP_KEY`) replaces 6+ scattered secrets |
| **Encryption at rest** | Fernet (AES-128-CBC) via PBKDF2-derived key; all config in SQLite `app_config` table |
| **Legacy mode** | `.env` file + OS keyring/file-based Fernet key still supported |
| **Resy password** | NOT persisted after authentication — only email + auth token stored |
| **OpenTable session** | CSRF token + browser cookies stored encrypted; no password needed |
| **File permissions** | Credentials dir 0o700, all files 0o600 |

Install the optional `keyring` dependency for OS keyring support (legacy mode):

```bash
pip install -e ".[security]"
```

## Example Prompts

### Discovery
- "Find Italian restaurants near home"
- "What's good for dinner near work tonight?"
- "Show me highly-rated sushi places within walking distance"
- "Find restaurants good for a group of 6 near Union Square"

### Booking
- "Check availability at Carbone for Saturday at 7 PM, party of 2"
- "Book L'Artusi for Friday at 8, party of 4"
- "What reservations do I have coming up?"
- "Cancel my reservation at Via Carota"

### Group Dining
- "Find a restaurant for date night this Saturday"
- "Search for a place that works for the whole family — remember everyone's allergies"

### Recommendations
- "What should we try tonight? We haven't been out in a week"
- "Recommend something new — I'm tired of Italian"
- "What's good for outdoor dining today?" *(checks weather automatically)*

### History & Preferences
- "Log that we went to Lilia last night — it was amazing, 5 stars"
- "Where have we eaten in the last month?"
- "Update my preferences — add Thai to my favorite cuisines"
- "Blacklist TGI Friday's — never suggest it again"

### Cost Tracking
- "How much have I spent on API calls this month?"

## MCP Tools (22 total)

| Tool | Purpose |
|------|---------|
| `setup_preferences` | First-run profile setup (home, work, cuisines, dietary) |
| `get_my_preferences` | View current preferences |
| `update_preferences` | Change specific preferences |
| `manage_person` | Add/update/remove dining companions |
| `list_people` | Show all saved companions |
| `manage_group` | Create/update/remove groups |
| `list_groups` | Show all saved groups |
| `manage_blacklist` | Block/unblock restaurants |
| `search_restaurants` | Find restaurants by cuisine, location, rating |
| `check_availability` | Check time slots across Resy + OpenTable |
| `make_reservation` | Book a table (with calendar link) |
| `cancel_reservation` | Cancel a booking |
| `my_reservations` | View upcoming reservations |
| `store_resy_credentials` | Save Resy login (encrypted) |
| `store_opentable_credentials` | Save OpenTable login (encrypted) |
| `log_visit` | Record a restaurant visit |
| `rate_visit` | Rate a past visit |
| `visit_history` | View dining history |
| `get_recommendations` | Get personalized suggestions |
| `search_for_group` | Find restaurants for a group (merged dietary needs) |
| `api_costs` | View API usage costs and cache stats |

## API Costs

| API | Cost | Usage |
|-----|------|-------|
| Google Places | ~$17/1000 detail calls | Primary discovery |
| OpenWeatherMap | Free (1000/day) | Weather context |
| Resy | Free (unofficial) | Booking |
| OpenTable | Free (DAPI + browser session) | Booking |

**Estimated monthly cost for heavy use:** $3-8 (with caching)

Use `api_costs` to monitor your spending at any time.

## Architecture

### Technical Stack

- **Language:** Python 3.11+
- **Framework:** [FastMCP](https://gofastmcp.com) — auto-generates tool schemas from type hints
- **Storage:** SQLite (local, WAL mode) with aiosqlite
- **Browser Automation:** Playwright (for auth + OpenTable)
- **APIs:** Google Places (New), OpenWeatherMap, Resy (unofficial), OpenTable (automation)
- **Calendar:** Google Calendar URL generation (zero-config)
- **Resilience:** tenacity (retry), custom CircuitBreaker, InMemoryCache (LRU + TTL)

### Resilience Features

- **Retry with exponential backoff** — transient errors (429, 5xx) are automatically retried up to 3 times
- **Circuit breakers** — per-service (Resy, Google Places, OpenTable, Weather) to prevent hammering failed APIs
- **3-layer booking fallback** — Resy API -> OpenTable Playwright -> deep links with manual instructions
- **In-memory caching** — LRU cache with TTL for search results, reducing API costs
- **User-friendly errors** — all exceptions are mapped to actionable messages for Claude to relay

### Project Structure

```
restaurant-mcp/
├── .ai/
│   ├── AGENTS.md               # Agent instructions
│   └── ENGINEERING-STANDARDS.md # Code patterns, testing mandate
├── docs/
│   ├── specs/                   # EPICs, architecture plan, research
│   └── adr/                     # Architecture Decision Records
├── scripts/
│   ├── validate.sh              # Full validation: lint + test + coverage
│   ├── test.sh                  # Run tests with coverage
│   └── lint.sh                  # Ruff linting only
├── src/
│   ├── server.py                # FastMCP entry point
│   ├── config.py                # Environment configuration
│   ├── models/                  # Pydantic data models
│   ├── storage/                 # SQLite + encrypted credentials
│   ├── clients/                 # API clients + resilience + cache
│   ├── matching/                # Cross-platform venue ID resolution
│   └── tools/                   # MCP tool definitions
├── tests/                       # 1112 tests, 100% branch coverage
├── data/                        # Runtime: DB, logs, credentials (gitignored)
├── pyproject.toml
├── .env.example
└── README.md
```

## Development

```bash
# Activate virtual environment
source .venv/bin/activate

# Run full validation (lint + tests + coverage + import check)
bash scripts/validate.sh

# Run tests only
bash scripts/test.sh

# Run linter only
bash scripts/lint.sh
```

**Testing:** 1112 unit tests with 100% branch coverage (`fail_under = 100` enforced).

### Integration Tests

On-demand integration tests exercise the full stack against live Resy and OpenTable APIs:

```bash
# Run all integration tests
python -m pytest tests/integration/ -m integration -v

# Resy only
python -m pytest tests/integration/test_resy_integration.py -m integration -v

# OpenTable only (requires session cookies — see step 9 above)
python -m pytest tests/integration/test_opentable_integration.py -m integration -v

# With a specific restaurant / date
INTEGRATION_RESTAURANT="Lilia" INTEGRATION_DATE="2026-03-15" \
  python -m pytest tests/integration/ -m integration -v
```

Integration tests are excluded from `validate.sh` and default pytest runs. They require real credentials in the credential store (set up via `python -m src.setup`).

## Prior Art

Several MCP restaurant reservation servers already exist — these serve as reference implementations:

| Repository | Language | What It Does |
|-----------|----------|-------------|
| [jrklein343-svg/restaurant-mcp](https://github.com/jrklein343-svg/restaurant-mcp) | TypeScript | Most complete — unified Resy+OpenTable search, direct Resy booking, `snipe_reservation` tool |
| [musemen/resy-mcp-server](https://github.com/musemen/resy-mcp-server) | Python | Claude Desktop focused — encrypted storage, multi-account, calendar export (ICS) |
| [agupta01/resy-mcp](https://github.com/agupta01/resy-mcp) | Python | PyPI-published (`pip install resy-mcp`), lightweight Resy-only |
| [samwang0723/mcp-booking](https://github.com/samwang0723/mcp-booking) | TypeScript | Google Maps discovery with mood-based filtering (mock booking only) |

**What we add:** Full Google Places integration, weather-aware outdoor seating, dining companion dietary tracking, visit history with reviews, and true dual-platform booking (Resy + OpenTable).

## Documentation

| Document | Description |
|----------|-------------|
| [AGENTS.md](./.ai/AGENTS.md) | Agent instructions — primary entry point for AI engineers |
| [ENGINEERING-STANDARDS.md](./.ai/ENGINEERING-STANDARDS.md) | Code patterns, architecture rules, testing mandate |
| [EPICS-INDEX.md](./docs/specs/EPICS-INDEX.md) | Master EPIC guide — dependency graph, tool inventory |
| [ARCHITECTURE_PLAN.md](./docs/specs/ARCHITECTURE_PLAN.md) | High-level architecture, API landscape, data models |
| [ADR-001](./docs/adr/001-epic08-resilience-decisions.md) | EPIC-08 resilience implementation decisions |

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| **Resy API brittleness** | 3-6 month breakage cycle; 3-layer fallback (API -> Playwright -> deep links) |
| Resy blocks unofficial API | Low request rates; OpenTable fallback |
| Resy auth tokens expire | Auto-refresh via Playwright login |
| OpenTable bot detection | Realistic delays (>30s); Playwright browser automation |
| Google API costs spike | In-memory LRU cache with 5-min TTL; cost tracking via `api_costs` tool |
| **Account deactivation** | Personal accounts only; no commercial patterns |

### Legal Considerations

The **NY Restaurant Reservation Anti-Piracy Act** (S.9365A, effective February 2025) prohibits third-party services from listing or selling restaurant reservations without written restaurant agreements. Penalties: $1,000/violation/day.

**For this project:** Personal-use automation is not explicitly prohibited, but both Resy's and OpenTable's Terms of Service prohibit automated access. This is a personal tool, not a commercial service.

## Future Ideas

- [ ] LA expansion (after NYC is stable)
- [ ] Shared preferences with partner (two-user mode)
- [ ] Restaurant deal tracking (NYC Restaurant Week, etc.)
- [ ] Tock integration (ticketed dining experiences)
- [ ] Yelp integration (official MCP server exists with booking support)
- [ ] Google Calendar API (OAuth2) for automatic sync (currently URL-based)
- [ ] SQLite cache tier for cross-session persistence

---

**Status:** All 8 EPICs complete. 1112 tests, 100% branch coverage. Integration tests for Resy and OpenTable.
