# NYC restaurant reservation automation: the MCP landscape in 2026

**Three MCP servers for Resy reservations already exist, but the unofficial API approach they depend on is increasingly fragile — breakages occur every 3–6 months as Resy escalates anti-bot measures.** This is the central tension your project faces: the technical architecture for an MCP-based reservation assistant is well-proven, but the underlying platform integrations sit on shifting sand. Resy's API remains more automatable than OpenTable's, but both lack official public APIs, and New York's Restaurant Reservation Anti-Piracy Act (effective February 2025) adds legal risk to any commercial use. The good news: a rich ecosystem of open-source repos, blog posts, and MCP best practices provides a strong foundation for building, and the MCP protocol itself has exploded to ~97 million monthly SDK downloads with adoption across Claude, ChatGPT, Gemini, and Cursor.

---

## Existing MCP servers already solve parts of this problem

The most important discovery is that **several MCP restaurant reservation servers already exist**, ranging from production-quality to hackathon prototypes. These can serve as reference implementations or even starting points for your project.

**jrklein343-svg/restaurant-mcp** is arguably the most complete. This Node.js/TypeScript MCP server unifies search across both Resy and OpenTable, performs real-time availability checks, books Resy reservations directly, and includes a `snipe_reservation` tool for auto-booking the instant slots become available. It stores credentials in Windows Credential Manager with DPAPI encryption and supports email/password auto-login for token refresh. For OpenTable, it provides booking links rather than direct booking, acknowledging OpenTable's stricter automation resistance.

**musemen/resy-mcp-server** is a Python MCP server purpose-built for Claude Desktop. It offers encrypted token storage via Fernet symmetric encryption with SQLite, multi-account support, location-based search optimized for NYC, waitlist automation, calendar export (ICS with Google/Outlook/Yahoo links), and reservation history tracking. Its architecture cleanly separates concerns into `auth.py`, `search.py`, `booking.py`, `scheduler.py`, `waitlist.py`, and `calendar.py` — a pattern directly applicable to your project.

**agupta01/resy-mcp** is published on PyPI (`pip install resy-mcp`, v0.1.0 from April 2025) as a simpler, lightweight alternative. **samwang0723/mcp-booking** (9 stars, TypeScript) handles restaurant discovery via Google Maps Places API with mood-based and event-specific filtering but uses only mock booking — making it a complementary reference for the discovery half of your system. A Yelp MCP server also exists with official Yelp Fusion AI API integration and actual reservation booking support.

No MCP server combines Google Places discovery, weather integration, and real booking across both Resy and OpenTable — that gap is precisely your project's value proposition.

---

## Resy's API is well-mapped but the walls are closing in

Every Resy bot in the ecosystem follows the same **three-step booking flow** reverse-engineered from `api.resy.com`: `GET /4/find` returns available slots with `config_id` values, `GET /3/details` returns a `book_token` for a specific slot, and `POST /3/book` with the `book_token` plus a `struct_payment_method` JSON payload completes the reservation. Authentication requires two headers: `Authorization: ResyAPI api_key="<key>"` (an application-level key) and `X-Resy-Auth-Token` (a user-specific JWT). The API key `"youarewhereyoueat"` was once hardcoded in Resy's staging environment. Programmatic authentication is possible via `POST /3/auth/password` with email and password, which returns the user's token, payment methods, and profile data.

The ecosystem is substantial: **Alkaar/resy-booking-bot** (467 stars, Scala) is the seminal sniper bot. **jeffknaide/resy-bot** (Python/Pydantic) offers the cleanest Python implementation with data models directly usable in an MCP context. **korbinschulz/resybot-open** (38 stars) was a commercial SaaS product generating thousands monthly before being open-sourced when New York banned reservation resale. Its most notable contribution: discovering that **converting Resy's booking POST request to a GET with parameters appended to the URL bypasses CAPTCHA verification entirely** via what appears to be an undocumented/deprecated endpoint.

**However, brittleness is severe.** A timeline of documented breakages tells the story:

- **June 2023**: Resy began requiring valid browser User-Agent headers; bots returning HTTP 500 errors until patched
- **August–October 2023**: Multiple reports of bots running but failing to complete bookings; "no longer available" errors on valid `book_token` values
- **March 2024**: The resolved-bot maintainer declared the project non-functional after 3+ weeks of failures, citing increased CAPTCHA usage returning "Pardon Our Interruption" pages. He wrote: *"We currently have no plans to keep the bot up to date"*
- **April 2024**: Users reported being unable to access `api.resy.com` at all, asking *"Does anyone know how to get an API key now?"*
- **July 2025**: New issues still being opened on Alkaar's bot

JonLuca DeCaro's 2022 analysis noted Resy's APIs *"didn't seem to have any rate limiting"* and their webpack config *"isn't mangling their code or removing comments."* Both observations are likely outdated. Resy now operates an active Platform Security team that deactivates bot accounts, cancels suspicious reservations, and blocks bot traffic. Restaurants have added their own defenses: **$2.50/person booking fees** (requiring valid payment), ID checks matching reservation names, and blocking multiple bookings from the same account.

One important technical note: **AmEx cardholders see additional reservation inventory** not visible to regular users. Since AmEx owns Resy, AmEx-linked accounts are more valuable for automation. Token refresh strategies vary: JonLuca's bot refreshes hourly via cron (`cron.scheduleJob("1 * * * *", regenerateHeaders)`), while most others require manual extraction from browser DevTools.

---

## OpenTable is harder to automate and the community is smaller

OpenTable's automation landscape is thinner than Resy's — roughly **3–4 repos with under 30 total stars** compared to Resy's 10+ repos with 400+ stars. The most successful approach was documented by JonLuca DeCaro, who intercepted OpenTable's mobile API via BurpSuite rather than using browser automation.

The mobile API lives at `mobile-api.opentable.com` and follows a four-step flow: check availability via `PUT /api/v3/restaurant/availability` (with `dateTime`, `partySize`, `rids`, and an `availabilityToken` JWT), lock a slot via `POST /api/v1/reservation/<id>/lock`, complete booking via `POST /api/v1/reservation/<id>`, and cancel via `DELETE /api/v3/reservation/<id>/<confirmation>`. Only `Authorization: Bearer <token>` and `Content-Type` headers are required. As of JonLuca's 2021 analysis, the mobile API had no CAPTCHA, no certificate stapling, and returned clean JSON.

**Rate limiting is the primary defense.** The nohren/Open-Table-Bot project explicitly warns: *"Beware of checking < 30 seconds. That seems to get you blocked."* The website itself uses JavaScript rendering requirements and IP blocking that mandate residential proxy rotation for scraping. OpenTable does maintain a Partner API at `docs.opentable.com` with a sandbox environment, but it is **restaurant-facing only** — approval takes 3–4 weeks, requires passing QA review, and does not enable consumer-side programmatic booking.

The critical comparison: **Resy is significantly easier to automate than OpenTable.** JonLuca, who built bots for both, found Resy's APIs "fairly straightforward" with similar web and mobile endpoints and no rate limiting, while OpenTable required mobile API interception via BurpSuite. The key differences:

| Factor | Resy | OpenTable |
|--------|------|-----------|
| **Bot ecosystem** | 10+ repos, 467 stars on lead repo | 3–4 repos, <30 stars |
| **Auth complexity** | API key + token from browser Network tab | Bearer token via BurpSuite mobile interception |
| **Rate limiting** | Minimal/none reported historically | Blocks at <30s polling intervals |
| **CAPTCHA** | Increasing since 2024 (bypassable via GET trick) | None observed on mobile API |
| **Code obfuscation** | Webpack unmangled with comments | Standard |
| **Market share** | 12.75% (~8,975 restaurants) | 31.88% (~22,437 restaurants) |

For your project, this means **Resy integration should come first** (easier, better documented) with OpenTable as a second phase using Playwright browser automation as the more maintainable approach given the lack of community documentation for OpenTable's API.

---

## The legal landscape has shifted significantly

The **New York Restaurant Reservation Anti-Piracy Act** (S.9365A), signed by Governor Hochul in December 2024 and effective February 17, 2025, adds a new section §391-w to General Business Law. It prohibits third-party services from listing, advertising, or selling restaurant reservations without a written agreement with the restaurant. Violations carry penalties of **$1,000 per violation per day**, with each unauthorized listing for each restaurant constituting a separate violation. Both consumers charged fees and restaurants whose reservations were listed without authorization have a private right of action for injunctive relief, actual damages, and attorneys' fees.

Florida followed with SB 940 (effective July 1, 2025), and similar bills have been proposed in California, Illinois, Louisiana, Hawaii, and Nevada. The law primarily targets resale platforms like Appointment Trader and Cita Reservations — it does **not explicitly ban personal-use automation**. However, any commercial deployment or multi-user service that books reservations programmatically sits in a gray zone. Resy's CEO called the law "a huge win" and pledged advocacy for similar legislation federally and in other states.

For your project, the key implication: **personal-use automation for your own reservations remains legally ambiguous but not explicitly prohibited.** Building a multi-user service or commercializing the tool introduces significant legal risk. Both Resy's and OpenTable's Terms of Service explicitly prohibit automated access, meaning account deactivation is a real risk regardless of legal status.

---

## MCP best practices point toward outcome-oriented tool design

The most important architectural guidance comes from Philipp Schmid's January 2026 article "MCP is Not the Problem, It's Your Server." His core thesis: **MCP is a user interface for AI agents, not a REST API wrapper.** Six principles apply directly:

1. **Design for outcomes, not operations.** Don't expose `search_restaurants()`, `get_availability()`, and `make_reservation()` as separate tools. Instead, expose `find_and_book_restaurant(cuisine, location, date, party_size)` that orchestrates the full flow internally.
2. **Flatten arguments to primitives and enums.** Use `Literal` types for constrained choices (cuisine types, price ranges) and sensible defaults to minimize the decisions Claude needs to make.
3. **Treat docstrings as instructions.** Your tool docstrings are the primary way Claude understands what each tool does — they should be detailed, include examples, and describe edge cases.
4. **Curate ruthlessly.** Keep to 5–15 tools per server. The musemen/resy-mcp-server's architecture (auth, search, booking, scheduler, waitlist, calendar) is a good template.
5. **Name tools with service-prefix pattern.** Use `resy_search_restaurants`, `opentable_check_availability` for clear disambiguation.
6. **Paginate large results.** Restaurant search results should return a manageable subset with pagination support.

FastMCP (the Python framework at `gofastmcp.com`) is the right tool for implementation. The `@mcp.tool` decorator auto-generates tool names from function names, descriptions from docstrings, and JSON schemas from type hints. Resources can be exposed with `@mcp.resource("reservations://{user_id}")` for read-only data like reservation history.

The MCP ecosystem has grown explosively: **~97 million monthly SDK downloads**, 10,000+ active servers, and adoption by OpenAI, Google DeepMind, Microsoft, Cursor, and others. In December 2025, Anthropic donated MCP to the Agentic AI Foundation under the Linux Foundation, co-founded with OpenAI and Block. Thoughtworks' Technology Radar Vol. 33 specifically warned against "naive API-to-MCP conversion" — reinforcing the outcome-oriented design principle.

---

## Key GitHub repositories for reference

| Repository | Stars | Language | What it does |
|-----------|-------|----------|-------------|
| `Alkaar/resy-booking-bot` | 467 | Scala | Seminal Resy sniper; sleeps until drop time, rapid-fires for 10s |
| `korbinschulz/resybot-open` | 38 | Python | Former SaaS with CAPTCHA bypass via GET endpoint trick |
| `21Bruce/resolved-bot` | 46 | Go | CLI with `rats` (snipe at time) and `rais` (interval polling) modes |
| `jeffknaide/resy-bot` | 14 | Python | Clean Pydantic-modeled Resy API wrapper |
| `musemen/resy-mcp-server` | — | Python | Full MCP server with encrypted storage, multi-account, scheduling |
| `jrklein343-svg/restaurant-mcp` | — | TypeScript | Unified Resy+OpenTable MCP with snipe_reservation tool |
| `jonluca/OpenTable-Reservation-Maker` | 7 | Python | Mobile API reverse-engineering with Twilio SMS |
| `nohren/Open-Table-Bot` | 20 | JS | Tampermonkey userscript + Node.js email alerts |
| `samwang0723/mcp-booking` | 9 | TypeScript | Google Maps restaurant discovery MCP (mock booking) |
| `agupta01/resy-mcp` | — | Python | PyPI-published lightweight Resy MCP (v0.1.0) |
| `Satloff/resy_api` | — | Python | Clean API wrapper library (not a bot) |

---

## Academic foundations and recommendation system design

Several research papers validate and inform your architectural choices. The **SMART Restaurant Recommender** (MDPI, 2025) directly demonstrates integrating Google Places API with GPT-4 for context-aware recommendations, claiming **15% accuracy improvement** over traditional models. The **PolyResponse** system (Henderson et al., EMNLP 2019) builds a retrieval-based conversational search engine trained on hundreds of millions of real conversations, specifically for restaurant search and booking — a task-oriented dialogue reference architecture.

For recommendation algorithms, the research points toward hybrid approaches: **collaborative filtering** (matrix factorization per Koren et al.) combined with **content-based filtering** (cuisine, price, ambiance matching) and **context-aware post-filtering** (occasion, weather, time of day, dining companions). The ML-TOPSIS approach (Atlantis Press, 2024) adds multi-criteria decision making with nutritional/dietary evaluation — relevant for handling preferences like allergies and dietary restrictions.

The **R-cube** system (2015) is the closest academic precedent to your project: a hybrid dialogue agent handling both restaurant recommendation and reservation through natural conversation. More recently, the **OSTOD** (One-Step Task-Oriented Dialogue) paper tested on MultiWOZ restaurant domains shows how synchronous state-and-response generation avoids error propagation in multi-turn booking conversations.

---

## Implementation patterns that will determine success or failure

**Credential management** is the most critical implementation detail. Store Resy auth tokens and API keys using `cryptography.Fernet` symmetric encryption with SQLite at rest. Use the Python `keyring` library for local development. Never hardcode tokens. Implement proactive token refresh — monitor `expires_in` values and refresh *before* expiration rather than waiting for 401 errors. JonLuca's pattern of hourly cron-based refresh is the minimum viable approach.

**Caching strategy** should use a three-tier architecture: in-memory LRU cache for hot data (current conversation context), SQLite for persistent cache (restaurant metadata, user preferences), and live API calls as source of truth. Cache restaurant metadata aggressively (name, location, cuisine — **24-hour TTL**), but availability data needs **5–15 minute TTL** at most. Implement cache-aside with stale fallback: if the API fails, serve stale cached availability with a clear disclaimer.

**Error handling** requires classifying errors as transient (429, 500, 502, 503, 504 — retryable with exponential backoff plus jitter) versus permanent (400, 401, 403, 404 — not retryable). Use the circuit breaker pattern via Python's `pybreaker` or `tenacity` libraries: after a threshold of failures, temporarily stop calling the failing service. For booking operations specifically, implement **idempotency keys** to prevent duplicate reservations on retry.

**Monitoring unofficial API changes** is essential for long-term survival. Periodically snapshot API response schemas and diff against baselines. Track response time, payload structure, and HTTP status codes. Run daily end-to-end Playwright tests that simulate actual booking flows. When schema changes are detected, implement adaptive parsing:

```python
class ResilientResyClient:
    async def book(self, params):
        try:
            return await self._book_via_post(params)  # Standard POST /3/book
        except SchemaChangeDetected:
            return await self._book_via_get(params)    # Fallback GET endpoint
        except CriticalFailure:
            return await self._notify_and_queue(params) # Alert + queue for manual booking
```

**Browser automation via Playwright** should be your OpenTable strategy rather than API reverse-engineering, given the thinner community documentation. Use the Page Object Model pattern, wait for specific DOM elements rather than arbitrary timeouts, and implement resilient selectors (prefer `data-` attributes over CSS class names). For scheduling, GitHub Actions with cron triggers and a shell `wait` command can ensure execution starts at the exact reservation drop time.

---

## What you haven't considered yet

**Calendar integration** should be a day-one feature, not an afterthought. The musemen/resy-mcp-server already generates ICS files with direct links to Google Calendar, Outlook, and Yahoo — and confirmed reservations naturally belong on a calendar. Use the Google Calendar API to create events with location, confirmation details, and cancellation links.

**OpenTable's Voice AI partner ecosystem** signals the industry direction. OpenTable has partnered with Slang AI, PolyAI, Voiceplug, and others for voice-driven reservations. Designing your MCP server to be voice-assistant compatible from the start (stateless tools, clear structured responses) positions you for integration with voice interfaces.

**Multi-platform search aggregation** is the killer feature. The jrklein343-svg/restaurant-mcp already implements unified search across Resy and OpenTable. Extend this to Yelp (which has an official MCP server with booking support), Tock (for ticketed dining experiences), and SevenRooms. Many NYC restaurants use exactly one platform — aggregation eliminates the user's need to know which.

**Emerging platforms** worth monitoring include EatApp (growing from Middle East into North America, affordable pricing), Toast Tables (integrated with the Toast POS ecosystem used by many NYC restaurants), and resOS (transparent flat-rate pricing). The reservation platform market is consolidating: AmEx now owns both Resy and Tock, and integration with POS systems is the dominant trend.

**Group dining coordination** is an underserved use case: aggregate dietary restrictions and cuisine preferences across a group, find restaurants that satisfy all constraints, and manage RSVPs. This aligns naturally with the multi-user patterns that an MCP server could support.

## Conclusion

Your project sits at a well-validated intersection — the MCP protocol provides the integration layer, Google Places provides discovery, and the Resy API provides the most automatable booking path. But **the primary risk is not technical, it's operational**: Resy's anti-bot measures are accelerating on a 3–6 month breakage cycle, the NY Anti-Piracy Act creates legal ambiguity for any commercial use, and account deactivation is a real consequence. The three existing Resy MCP servers (musemen's, agupta01's, jrklein343-svg's) prove the concept works today but face the same brittleness. Your best strategic move is to build with explicit fallback layers — API-first for Resy, Playwright browser automation for OpenTable, cached deep links as a last resort — and invest heavily in automated monitoring that detects API changes before they cause user-facing failures. The CAPTCHA bypass via GET endpoint discovered by korbinschulz is the kind of fragile trick that works until it doesn't; design your system to degrade gracefully when it stops working.