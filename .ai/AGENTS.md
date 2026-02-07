# Restaurant MCP — Agent Instructions

> You are an engineer building an MCP server that lets Claude Desktop discover, book, and manage NYC restaurant reservations through natural conversation.

---

## Project Overview

This is a **FastMCP Python server** that exposes tools for restaurant discovery (Google Places), reservation booking (Resy API + OpenTable Playwright automation), user preference management, dining companion tracking, weather-aware recommendations, and visit history. It connects to Claude Desktop via the MCP protocol.

**Key constraints:**
- Personal use only — single user, not a commercial service
- Optimize for lowest possible API cost (field masks, aggressive caching, haversine over Distance Matrix)
- Python 3.11+, async throughout, SQLite for all persistence

---

## Repository Structure

```
/                                    ← Project root (restaurant-mcp/)
├── .ai/
│   ├── AGENTS.md                    ← YOU ARE HERE — primary agent instructions
│   └── ENGINEERING-STANDARDS.md     ← Code patterns, architecture rules, testing mandate
│
├── docs/
│   ├── specs/                       ← Feature specifications
│   │   ├── ARCHITECTURE_PLAN.md     ← High-level architecture, API landscape, data models
│   │   ├── EPICS-INDEX.md           ← Master EPIC guide — dependency graph, tool inventory
│   │   ├── EPIC-01-PROJECT-FOUNDATION.md
│   │   ├── EPIC-02-DATA-LAYER.md
│   │   ├── EPIC-03-USER-PREFERENCES.md
│   │   ├── EPIC-04-RESTAURANT-DISCOVERY.md
│   │   ├── EPIC-05-RESY-INTEGRATION.md
│   │   ├── EPIC-06-OPENTABLE-INTEGRATION.md
│   │   ├── EPIC-07-INTELLIGENCE-LAYER.md
│   │   ├── EPIC-08-RESILIENCE-AND-PRODUCTION.md
│   │   └── RESEARCH.md              ← Background research on APIs, ecosystem, legal
│   └── adr/                         ← Architecture Decision Records (context on "why")
│
├── scripts/                         ← Agent feedback-loop scripts (deterministic validation)
│   ├── validate.sh                  ← Full validation: lint + typecheck + test + coverage
│   ├── test.sh                      ← Run tests with coverage reporting
│   └── lint.sh                      ← Ruff linting only
│
├── src/                             ← Application source code
│   ├── server.py                    ← FastMCP entry point
│   ├── config.py                    ← pydantic-settings configuration
│   ├── models/                      ← Pydantic data models (pure, no I/O)
│   ├── storage/                     ← SQLite database + encrypted credentials
│   ├── clients/                     ← External API clients (Google, Resy, OpenTable, Weather)
│   ├── matching/                    ← Cross-platform venue ID resolution
│   └── tools/                       ← MCP tool definitions (thin orchestrators)
│
├── tests/                           ← Test suite (mirrors src/ structure exactly)
│   ├── conftest.py
│   ├── factories.py
│   ├── fixtures/                    ← Sample API response JSON files
│   ├── models/
│   ├── storage/
│   ├── clients/
│   ├── matching/
│   └── tools/
│
├── data/                            ← Runtime data (gitignored except .gitkeep)
├── pyproject.toml
├── .env.example
├── .gitignore
└── README.md
```

---

## How to Work on This Project

### Before Writing Any Code

1. **Read the EPIC** you are implementing: `docs/specs/EPIC-{NN}-*.md`
2. **Read the engineering standards**: `.ai/ENGINEERING-STANDARDS.md` — this is mandatory. Every pattern, naming convention, and architectural rule must be followed.
3. **Check the EPIC dependency graph** in `docs/specs/EPICS-INDEX.md` — do not start an EPIC whose dependencies are incomplete.

### While Writing Code

1. **Follow the layer architecture strictly:**
   ```
   models → storage → clients → matching → tools → server
   ```
   Lower layers never import higher layers. See ENGINEERING-STANDARDS.md Section 2 for full import rules.

2. **Run the validation script after every meaningful change:**
   ```bash
   ./scripts/validate.sh
   ```
   This runs linting, type checking, tests, and coverage in sequence. Your work is not done until this passes cleanly.

3. **Run tests frequently during development:**
   ```bash
   ./scripts/test.sh
   ```
   This runs `pytest --cov=src --cov-report=term-missing` and will fail if coverage drops below 100%.

4. **Write tests alongside code, not after.** Every new file in `src/` must have a corresponding test file in `tests/` before the EPIC is complete.

### After Completing an EPIC

Run the full validation to confirm everything passes:

```bash
./scripts/validate.sh
```

Then verify against the EPIC completion checklist in `.ai/ENGINEERING-STANDARDS.md` (Quick Reference Checklist at the bottom).

---

## Key Rules (Summary)

These are extracted from ENGINEERING-STANDARDS.md. Read the full document for details and code examples.

### Architecture
- **Dependency injection** — `server.py` is the composition root. All dependencies are passed explicitly, never imported as singletons.
- **Models are pure data** — no I/O, no database calls, no business logic in `src/models/`.
- **All SQL in DatabaseManager** — no raw SQL outside `src/storage/database.py`.
- **Tools are thin orchestrators** — parse inputs, call client/DB, format output, return string. Max ~50 lines.
- **Clients own response parsing** — return Pydantic models, not raw dicts.

### Code Style
- Type hints on every function signature and return type
- Modern Python 3.11+ syntax: `str | None`, `list[str]`, `dict[str, Any]`
- f-strings for all formatting
- Guard clauses over deep nesting
- No bare `except` — always catch specific exceptions

### Testing (Non-Negotiable)
- **100% branch coverage** — enforced via `fail_under = 100` in pyproject.toml
- **Every `src/` file has a `tests/` counterpart** — `src/clients/resy.py` → `tests/clients/test_resy.py`
- **All external services are mocked** — no real HTTP requests or browser launches in tests
- **Arrange-Act-Assert** pattern for test structure
- **Test naming**: `test_{method}_{scenario}_{expected_outcome}`

### Error Handling
- Exception hierarchy rooted at `APIError` in `src/clients/resilience.py`
- Every MCP tool catches exceptions at the boundary and returns user-friendly strings
- Never swallow errors silently

---

## Scripts Reference

| Script | Purpose | When to Run |
|--------|---------|-------------|
| `./scripts/validate.sh` | Full pipeline: lint + typecheck + test + coverage | After completing any story/task |
| `./scripts/test.sh` | Tests with coverage report | During development, frequently |
| `./scripts/lint.sh` | Ruff linting only | Quick check while editing |

All scripts exit non-zero on failure. **If a script fails, fix the issue before moving on.**

---

## Architecture Decision Records

When you make a non-obvious architectural choice (choosing one library over another, a particular data model design, a caching strategy), document it in `docs/adr/` using this format:

```markdown
# ADR-{NNN}: {Title}

## Status
Accepted | Proposed | Deprecated

## Context
What is the situation that requires a decision?

## Decision
What is the chosen approach?

## Consequences
What are the trade-offs? What becomes easier or harder?
```

Name files as `docs/adr/ADR-001-{slug}.md`. Number sequentially.

---

## EPIC Implementation Order

Implement in this order (see `docs/specs/EPICS-INDEX.md` for full details):

1. **EPIC-01** — Project Foundation & MCP Server Skeleton
2. **EPIC-02** — Data Models & Storage Layer
3. **EPIC-03** — User Preferences & People Management
4. **EPIC-04** — Restaurant Discovery (Google Places)
5. **EPIC-05** — Resy Booking Platform
6. **EPIC-06** — OpenTable Booking Platform
7. **EPIC-07** — Intelligence & Recommendations
8. **EPIC-08** — Resilience, Caching & Production Readiness

---

## Important File References

| What | Where |
|------|-------|
| Engineering standards & patterns | `.ai/ENGINEERING-STANDARDS.md` |
| EPIC master index | `docs/specs/EPICS-INDEX.md` |
| Architecture & API landscape | `docs/specs/ARCHITECTURE_PLAN.md` |
| Background research | `docs/specs/RESEARCH.md` |
| Architecture decisions | `docs/adr/ADR-*.md` |
| Validation scripts | `scripts/validate.sh`, `scripts/test.sh`, `scripts/lint.sh` |
