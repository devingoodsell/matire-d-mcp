# NYC Restaurant Reservation Assistant — EPIC Index

## Overview

This document is the master guide for implementing the Restaurant MCP server. There are **8 EPICs** that should be implemented roughly in order (with some parallelism possible). The end result is a FastMCP server that Claude Desktop connects to, enabling natural-language restaurant discovery, availability checking, and booking across Resy and OpenTable.

## EPIC Dependency Graph

```
EPIC-01: Project Foundation
    ↓
EPIC-02: Data Layer
    ↓
EPIC-03: User Preferences ──────────────┐
    ↓                                    │
EPIC-04: Restaurant Discovery ───────────┤
    ↓                                    │
EPIC-05: Resy Integration ──────────┐    │
    ↓                               │    │
EPIC-06: OpenTable Integration ─────┤    │
    ↓                               │    │
EPIC-07: Intelligence Layer ────────┤────┘
    ↓                               │
EPIC-08: Resilience & Production ───┘
```

## Implementation Order

| Order | EPIC | File | Key Deliverable |
|-------|------|------|-----------------|
| 1 | Project Foundation | [EPIC-01](./EPIC-01-PROJECT-FOUNDATION.md) | `python -m src.server` starts, Claude connects |
| 2 | Data Layer | [EPIC-02](./EPIC-02-DATA-LAYER.md) | Pydantic models + SQLite with full schema |
| 3 | User Preferences | [EPIC-03](./EPIC-03-USER-PREFERENCES.md) | Setup wizard, people, groups via conversation |
| 4 | Restaurant Discovery | [EPIC-04](./EPIC-04-RESTAURANT-DISCOVERY.md) | "Find Italian near home" works |
| 5 | Resy Integration | [EPIC-05](./EPIC-05-RESY-INTEGRATION.md) | Check availability + book on Resy |
| 6 | OpenTable Integration | [EPIC-06](./EPIC-06-OPENTABLE-INTEGRATION.md) | Check availability + book on OpenTable |
| 7 | Intelligence Layer | [EPIC-07](./EPIC-07-INTELLIGENCE-LAYER.md) | Weather, recency, recommendations |
| 8 | Resilience & Production | [EPIC-08](./EPIC-08-RESILIENCE-AND-PRODUCTION.md) | Retry, circuit breakers, caching, calendar (**complete**) |

**Parallelism opportunities:**
- EPIC-05 and EPIC-06 can be developed in parallel after EPIC-04
- EPIC-07 can start after EPIC-04 (weather + recommendations don't need booking)
- EPIC-08 can start partially after EPIC-05 (resilience for Resy)

## MCP Tools Summary

After all EPICs are implemented, the server exposes these tools to Claude:

| Tool | EPIC | Purpose |
|------|------|---------|
| `setup_preferences` | 03 | First-run profile setup |
| `get_my_preferences` | 03 | View current preferences |
| `update_preferences` | 03 | Change specific preferences |
| `manage_person` | 03 | Add/update/remove dining companions |
| `list_people` | 03 | Show all saved companions |
| `manage_group` | 03 | Create/update/remove groups |
| `list_groups` | 03 | Show all saved groups |
| `manage_blacklist` | 03 | Block/unblock restaurants |
| `search_restaurants` | 04 | Find restaurants by criteria |
| `check_availability` | 05/06 | Check time slots (Resy + OpenTable) |
| `make_reservation` | 05/06 | Book a table |
| `cancel_reservation` | 05/06 | Cancel a booking |
| `my_reservations` | 05 | View upcoming reservations |
| `store_resy_credentials` | 05 | Save Resy login |
| `store_opentable_credentials` | 06 | Save OpenTable login |
| `log_visit` | 07 | Record a restaurant visit |
| `rate_visit` | 07 | Rate a past visit |
| `visit_history` | 07 | View dining history |
| `get_recommendations` | 07 | Get personalized suggestions |
| `search_for_group` | 07 | Find restaurants for a group |
| `api_costs` | 08 | View API usage costs |

**Total: 22 tools** (target was 5-15 per the MCP best practices — this is acceptable given the breadth of functionality, and Claude handles tool selection well at this count).

## Estimated Monthly API Costs

| Provider | Cost | Notes |
|----------|------|-------|
| Google Places (New) | $3-8 | With field masks + 24hr cache. ~3-5 searches/day |
| Geocoding | ~$0.01 | One-time per address (home, work) |
| OpenWeatherMap | $0 | Free tier: 1000 calls/day |
| Resy | $0 | Unofficial API, no billing |
| OpenTable | $0 | Browser automation, no billing |
| **Total** | **$3-8/month** | Heavy personal use |

## Project Structure (Final)

> **Canonical structure.** See `.ai/ENGINEERING-STANDARDS.md` Section 1 for the full expanded tree with every file listed.

```
restaurant-mcp/
├── .ai/
│   ├── AGENTS.md                  # Primary agent instructions (system prompt)
│   └── ENGINEERING-STANDARDS.md   # Code patterns, architecture rules, testing mandate
│
├── docs/
│   ├── specs/                     # Feature specifications (EPICs, architecture, research)
│   └── adr/                       # Architecture Decision Records
│
├── scripts/
│   ├── validate.sh                # Full pipeline: lint + typecheck + test + coverage
│   ├── test.sh                    # Run tests with coverage
│   └── lint.sh                    # Ruff linting only
│
├── src/
│   ├── __init__.py
│   ├── __main__.py
│   ├── server.py                  # FastMCP entry point
│   ├── config.py                  # Environment config (pydantic-settings)
│   ├── models/                    # EPIC-02: Pydantic data models
│   │   ├── enums.py, restaurant.py, user.py, reservation.py, review.py
│   ├── storage/                   # EPIC-02/05: SQLite + encrypted credentials
│   │   ├── database.py, schema.sql, credentials.py
│   ├── clients/                   # EPIC-04-08: External API clients
│   │   ├── base.py, google_places.py, cuisine_mapper.py
│   │   ├── resy.py, resy_auth.py, opentable.py
│   │   ├── weather.py, calendar.py, cache.py, resilience.py
│   ├── matching/                  # EPIC-05/06: Cross-platform venue ID resolution
│   │   └── venue_matcher.py
│   └── tools/                     # EPIC-03-08: MCP tool definitions
│       ├── preferences.py, people.py, search.py, booking.py
│       ├── history.py, recommendations.py, date_utils.py
│       ├── error_messages.py, costs.py
│
├── tests/                         # Mirrors src/ structure exactly (see ENGINEERING-STANDARDS.md)
│   ├── conftest.py, factories.py
│   ├── fixtures/                  # Sample API response JSON files
│   ├── models/, storage/, clients/, matching/, tools/
│
├── data/                          # Runtime data (gitignored except .gitkeep)
│   ├── restaurant.db, logs/, .credentials/
│
├── pyproject.toml
├── .env.example
├── .gitignore
└── README.md
```

## Key Design Decisions

1. **Google Place ID as canonical restaurant identifier** — every restaurant is referenced by its Google Place ID throughout the system. Resy venue IDs and OpenTable slugs are cross-referenced in the cache.

2. **FastMCP framework** — auto-generates tool schemas from type hints and docstrings. Docstrings serve as Claude's instructions.

3. **SQLite for everything** — single file, zero config, sufficient for single-user personal tool. WAL mode for concurrent reads.

4. **API-first for Resy, Playwright-first for OpenTable** — Resy has a well-documented unofficial API. OpenTable requires browser automation. Both fall back to deep links.

5. **Cost optimization via field masks + caching** — Google Places (New) API charges per field requested. We request only what we need and cache for 24 hours.

6. **Haversine distance instead of Distance Matrix API** — saves $5/1000 calls. Walking time estimate is "close enough" for personal use.

7. **Calendar via URL generation (not OAuth)** — zero setup required. Generates a Google Calendar pre-filled link instead of requiring OAuth2 credentials.

8. **Deterministic recommendations, not ML** — simple weighted scoring formula that's transparent and debuggable. No training data needed.

## Getting Started

```bash
# 1. Clone and install
cd restaurant-mcp
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"

# 2. Install Playwright browser
playwright install chromium

# 3. Set up environment
cp .env.example .env
# Edit .env with your Google API key

# 4. Validate the setup
./scripts/validate.sh

# 5. Run the server
python -m src.server

# 6. Configure Claude Desktop (see docs/specs/EPIC-01-PROJECT-FOUNDATION.md)
```

## Conversation Examples

### First Run
```
You: "Help me set up my restaurant preferences"
Claude: [Calls setup_preferences with your responses]
→ Profile saved with home/work locations, cuisines, dietary restrictions

You: "Add my wife — she has a nut and seed allergy"
Claude: [Calls manage_person("Wife", dietary_restrictions=["nut_allergy", "seed_allergy"])]
→ Wife saved with allergies noted

You: "Create a group called family with my wife"
Claude: [Calls manage_group("family", members=["Wife"])]
→ Group 'family' created. Merged restrictions: nut_allergy, seed_allergy
```

### Daily Use
```
You: "Find me a quiet Italian place near home for Saturday at 7"
Claude: [Calls search_restaurants(cuisine="italian", location="home", ambience="quiet")]
       [Calls check_availability for top results]
→ Shows 3 restaurants with ratings, walk times, and available slots

You: "Book Carbone at 6:30"
Claude: [Calls make_reservation("Carbone", "Saturday", "18:30", party_size=2)]
→ Booked! Confirmation: RESY-ABC123
   Add to Google Calendar: [link]

You: "What should we do for team dinner Thursday?"
Claude: [Calls search_for_group("work_team", date="Thursday", location="work")]
→ Shows restaurants that work for everyone's dietary needs
```

---

## Status

**All 8 EPICs complete.** 945 tests, 100% branch coverage.

Architecture Decision Records:
- [ADR-001: EPIC-08 Resilience Decisions](../adr/001-epic08-resilience-decisions.md)
