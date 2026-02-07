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
| **Calendar Sync** | Add reservations to Google Calendar automatically |

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
| [RESEARCH.md](./docs/specs/RESEARCH.md) | Background research on APIs, ecosystem, legal |

## Implementation Timeline

```
Week 1-2: Phase 1 - Foundation
          ✓ FastMCP server skeleton (outcome-oriented tools)
          ✓ Google Places integration
          ✓ Friends + Friend Groups storage
          → "Find Italian near home" works

Week 3-4: Phase 2 - Resy + OpenTable
          ✓ Resy: API-first with Playwright auth refresh
          ✓ OpenTable: Playwright browser automation
          ✓ Availability checking (both platforms)
          ✓ Booking + cancellation (both platforms)
          ✓ Google Calendar integration (day-one feature)
          → "Book Carbone for Saturday" works (Resy or OpenTable)

Week 5-6: Phase 3 - Intelligence Layer
          ✓ Weather-aware recommendations
          ✓ Recency-based suggestions
          ✓ Learning from your reviews
          → Smart recs that know your preferences

Week 7-8: Phase 4 - Polish + Resilience
          ✓ Fallback layers (API → Playwright → deep links)
          ✓ Circuit breaker pattern for API failures
          ✓ API schema change monitoring
          ✓ Performance optimization (3-tier caching)
          → Production-ready with graceful degradation
```

## Quick Start (After Building)

### 1. Get API Keys

```bash
# Required
GOOGLE_API_KEY=...          # Google Cloud Console → Places API
OPENWEATHER_API_KEY=...     # openweathermap.org (free tier)

# Stored securely by the app
RESY_EMAIL=...
RESY_PASSWORD=...
```

### 2. Install

```bash
git clone <repo>
cd restaurant-mcp
python -m venv venv
source venv/bin/activate
pip install -e .
```

### 3. Configure Claude Desktop

Add to `~/.claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "restaurant": {
      "command": "python",
      "args": ["-m", "src.server"],
      "cwd": "/path/to/restaurant-mcp",
      "env": {
        "GOOGLE_API_KEY": "your_key",
        "OPENWEATHER_API_KEY": "your_key"
      }
    }
  }
}
```

### 4. First Run - Setup Wizard

```
You: "Help me set up my restaurant preferences"

Claude: Let's get you set up! First, what's your home address?
        (I'll use this as "near home" when you search)

You: "123 Example St, New York, NY 10001"

Claude: Got it. Where do you work?
... (continues with cuisine preferences, dietary restrictions, etc.)
```

### 5. Store Resy Credentials

```
You: "Set up my Resy account for booking"

Claude: I'll need your Resy email and password to book on your behalf.
        These are encrypted and stored locally.

You: "Email: me@example.com, Password: ..."

Claude: ✓ Resy credentials saved and validated!
```

## API Costs

| API | Cost | Usage |
|-----|------|-------|
| Google Places | ~$17/1000 detail calls | Primary discovery |
| Google Distance Matrix | ~$5/1000 calls | Walking time |
| OpenWeatherMap | Free (1000/day) | Weather context |
| Resy | Free (unofficial) | Booking |
| OpenTable | Free (browser automation) | Booking |

**Estimated monthly cost for heavy use:** $5-15

## Technical Stack

- **Language:** Python 3.11+
- **Framework:** FastMCP (gofastmcp.com) — auto-generates tool schemas from type hints
- **Storage:** SQLite (local) → Cloud migration path
- **Browser Automation:** Playwright (for auth + OpenTable)
- **APIs:** Google Places, OpenWeatherMap, Resy (unofficial), OpenTable (automation)
- **Calendar:** Google Calendar API for reservation sync

## Project Structure

```
restaurant-mcp/
├── .ai/
│   ├── AGENTS.md               # Agent instructions (system prompt for AI engineers)
│   └── ENGINEERING-STANDARDS.md # Code patterns, architecture rules, testing mandate
├── docs/
│   ├── specs/                  # EPICs, architecture plan, research
│   └── adr/                    # Architecture Decision Records
├── scripts/
│   ├── validate.sh             # Full validation: lint + typecheck + test + coverage
│   ├── test.sh                 # Run tests with coverage
│   └── lint.sh                 # Ruff linting only
├── src/
│   ├── server.py               # MCP entry point
│   ├── config.py               # Environment configuration
│   ├── models/                 # Pydantic data models
│   ├── storage/                # SQLite + encrypted credentials
│   ├── clients/                # API clients (Google, Resy, OpenTable, Weather)
│   ├── matching/               # Cross-platform venue ID resolution
│   └── tools/                  # MCP tool definitions
├── tests/                      # Test suite (mirrors src/ structure)
├── data/
│   ├── restaurant.db           # SQLite: preferences, history, cache, API logs
│   ├── logs/                   # Debug logs (rotated)
│   └── .credentials/           # Encrypted (gitignored)
├── pyproject.toml
├── .env.example
├── .gitignore
└── README.md
```

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| **Resy API brittleness** | 3-6 month breakage cycle documented; implement fallback layers (API → Playwright → deep links) |
| Resy blocks unofficial API | Keep request rates low; have OpenTable fallback |
| Resy auth tokens expire | Auto-refresh via Playwright login (hourly cron pattern) |
| OpenTable bot detection | Use realistic delays (>30s between checks); Playwright browser automation |
| Google API costs spike | Aggressive caching (24hr TTL for metadata, 5-15min for availability) |
| **Account deactivation** | Use personal accounts only; avoid commercial patterns |

### Legal Considerations

The **NY Restaurant Reservation Anti-Piracy Act** (S.9365A, effective February 2025) prohibits third-party services from listing or selling restaurant reservations without written restaurant agreements. Penalties: $1,000/violation/day.

**For this project:** Personal-use automation is not explicitly prohibited, but both Resy's and OpenTable's Terms of Service prohibit automated access. This is a personal tool, not a commercial service.

## Future Ideas

- [ ] LA expansion (after NYC is stable)
- [ ] Shared preferences with wife (two-user mode)
- [ ] Restaurant deal tracking (NYC Restaurant Week, etc.)
- [ ] Tock integration (ticketed dining experiences)
- [ ] Yelp integration (official MCP server exists with booking support)
- [ ] Voice assistant compatibility (Slang AI, PolyAI patterns)

---

**Status:** Planning complete. Ready to build Phase 1.