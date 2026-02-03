# ProcureWatch CLI — Updated PRD + Full Implementation Blueprint (v1.3)

> Scope: A terminal-first procurement/tender scraper that ingests opportunities from many portals, normalizes them, tracks changes, and stores them in a clean local database (SQLite or PostgreSQL).  
> v1.2 update: replaces Firecrawl with **Crawl4AI** as an optional extraction backend; adds a built-in **daily scheduler** (plus cron-friendly mode).
> v1.3 update: adds **SearchFormPortal** specification, **form filling logic**, and **homepage→search navigation** capabilities for M2.

---

## 0. What changed in v1.2 / v1.3

### Added / Updated (v1.2)
1. **Scheduler**: first-class scheduling (daily by default), plus pause/resume, run windows, and overlap protection.
2. **Crawl4AI backend (optional)**: a pluggable backend for JS-heavy pages, clean markdown generation, content filtering, and extraction strategies.
3. **Backend selection per portal**: `backend=http|playwright|crawl4ai` + fallback rules.
4. **Operational guardrails**: run locks, jittered schedules, and "freshness windows" to avoid hammering portals at the same time daily.

### Added / Updated (v1.3)
5. **SearchFormPortal specification**: detailed design for portals requiring search form interaction (fill fields, submit, extract results).
6. **Homepage→Search navigation**: support for multi-step navigation from landing page to search interface.
7. **Form filling logic**: configurable form field mappings, input types, and submission strategies.
8. **Browser-based pagination**: click-based "Next" buttons, "Load More" patterns, and infinite scroll handling.
9. **PlaywrightBackend detailed spec**: comprehensive browser automation backend with action scripting.

---

## 1. Product Requirements Document (PRD)

### 1.1 Product name
**ProcureWatch CLI** (working name)

### 1.2 One-line description
A **console-based procurement data collector** with a strong terminal UI that can **scrape** tender portals, **normalize** postings, **dedupe and version** changes, and **persist** everything to a clean local relational database for later querying via MCP/ChatGPT.

### 1.3 Goals
- Reliable ingestion across portal archetypes:
  - HTML tables & lists
  - Pagination and search flows
  - JS-rendered pages
  - Portals requiring session/cookies
  - Document-heavy postings (PDF attachments)
- “Low-maintenance” dynamic extraction:
  - Heuristic header mapping
  - Confidence scoring + drift detection
  - Snapshots on extraction failure
- Clean database designed for:
  - expired/open/awarded filters
  - “closing soon”
  - “what changed since last run”
- First-class operations:
  - daily schedules
  - logging + run summaries
  - resume after crash
- **Quick-start UX (NEW)**:
  - run with URL + minimal criteria
  - auto-discover pagination where possible
  - write results to DB with inferred schema

### 1.4 Non-goals (v1)
- Automated CAPTCHA bypassing or circumventing security controls.
- Scraping behind paywalls.
- MCP server implementation (planned v2).

---

## 2. Functional Requirements

### FR1 — Portal Configuration & Management
**Capabilities**
- Add/edit/remove portals via:
  - `configs/portals/<portal>.yaml` (source of truth)
  - DB mirror for audit / runtime
- Portal config includes:
  - `name`, `base_url`, `portal_type`
  - `seed_urls` (entry points)
  - `discovery` (pagination rules)
  - `backend` preference and fallbacks
  - auth strategy: none / cookie import / interactive login
  - politeness: rate limit, concurrency, retries, robots policy
  - extraction schema (canonical fields + aliases)

**Acceptance**
- `portal test` validates:
  - connectivity
  - parsing
  - extraction confidence
  - writes a dry-run summary

---

### FR1.5 — Quick Mode (NEW)
**Goal**: Allow non-technical users to run a scrape with minimal input and still get useful data written to the database.

**Inputs (minimum)**
- `seed_url`
- `max_pages`
- optional: `keywords`, `status`, `since`

**Behavior**
- Use Crawl4AI backend with LLM extraction for inferred fields
- Apply lightweight pagination heuristics (next/load more) within a bounded depth
- Store results with field provenance and confidence scores
- Produce a draft portal config for promotion to deterministic mode

**Acceptance**
- `quick` run produces records in DB with inferred schema
- Draft YAML can be generated from a successful quick run

---

### FR2 — Discovery & Pagination
_toggleable per portal_
- next link detection
- page number iteration
- offset/limit cursor
- date-filtered search (if supported)

Stop conditions:
- max pages
- cutoff date reached
- duplicate page signature detected
- extraction confidence collapses repeatedly (trip breaker)

---

### FR3 — Extraction Engine (Dynamic)
Extraction strategy stack:
1. Structured data capture (JSON-LD, embedded JSON)
2. Heuristic table/list mapping (header synonym map + fuzzy match)
3. Config selectors (CSS/XPath hints)
4. JS-rendered fallback (Playwright OR Crawl4AI backend)
5. Human-in-the-loop pause (headed browser) for login/captcha blockers

Dynamic safeguards:
- field-level + record-level confidence scoring
- drift detection:
  - if confidence below threshold or headers can’t map, store snapshot and raise `LAYOUT_DRIFT`

---

### FR4 — Dedupe, Versioning, and Change Tracking
- Primary dedupe key: `(portal_id, external_id)`
- Fallback: content fingerprint hash from stable fields
- Write path:
  - upsert into `opportunities`
  - append change events to `opportunity_events`
- Event types: `NEW`, `UPDATED`, `CLOSED`, `AWARDED`, `EXPIRED`, `LAYOUT_DRIFT`, `BLOCKED`, `ERROR`

---

### FR5 — Persistence (Local DB)
Supported engines:
- SQLite (default)
- PostgreSQL (recommended)

Migrations:
- Alembic

---

### FR6 — Terminal UI + CLI
- CLI: Typer + Rich
- Optional full-screen TUI: Textual
- Must provide:
  - run progress
  - per-portal summaries
  - error inbox with snapshots
  - exports

---

### FR6.5 — Quick Mode CLI (NEW)
**Commands**
- `procurewatch quick --url <seed> --max-pages N [--keywords "..."] [--since 30d]`
- `procurewatch quick promote --run-id <id>` (generate draft YAML)

---

### FR7 — Scheduling (NEW)
**Goal**: Run daily scrapes automatically to capture changes and freshness.

Scheduler capabilities:
- Define schedules:
  - daily at fixed time (default)
  - weekday-only
  - hourly (optional)
- Run controls:
  - `enabled/disabled`
  - per-portal or group
  - jitter window (±N minutes)
  - blackout window (don’t run during certain hours)
- Overlap protection:
  - global lock
  - per-portal lock
  - backoff if still running
- Resume:
  - if run crashed, next schedule can resume from checkpoint (optional in v1.2, recommended)

---

### FR8 — “CORS / Captcha / Anti-bot / Auth”
- Server-side scraping is not blocked by browser CORS rules; however JS-driven flows and bot defenses can still block.
Supported approaches:
- public-only mode
- cookie import (manual or from headed Playwright/Crawl4AI session)
- interactive login run mode (operator completes login)
- proxies (optional per portal)

---

### FR9 — AI-Assisted Dynamic Browsing (NEW)
**Goal**: Enable an optional agent-driven mode that can dynamically navigate portals, discover structures, and extract data when deterministic configs are too brittle or costly to maintain.

**Capabilities**
- AI agent controls a browser session through an MCP-compatible Playwright interface
- Dynamic discovery of navigation paths, forms, and pagination patterns
- Adaptive extraction strategy using LLM-guided field inference (with provenance)
- Ability to generate or refine portal configs for future deterministic runs

**When to use**
- Portal layout is unknown or frequently changing
- One-off scraping where manual config investment is not justified
- Extraction fails repeatedly due to drift or dynamic rendering patterns

**Operational constraints**
- Must be explicitly enabled per portal: `backend: agent` or `portal_type: dynamic`
- Clear audit trail of AI decisions (actions taken, selectors chosen, fields inferred)
- Respect existing non-goals: no automated CAPTCHA bypassing, no paywall scraping

**Acceptance**
- Agent mode can complete a full scrape on a JS-heavy portal with minimal config
- Agent mode can export a draft YAML config based on discovered structure
- Deterministic mode remains the default and unchanged behavior

---

## 3. Crawl4AI Integration (replaces Firecrawl)

### 3.1 Why Crawl4AI fits this product
Crawl4AI is a Python package designed for “AI-ready” crawling:
- Produces **clean markdown** output and can apply “noise filtering” strategies (“fit markdown”)
- Uses browser automation under the hood (Playwright) for dynamic pages
- Supports configurable crawling via `BrowserConfig` and `CrawlerRunConfig`, with optional LLM-driven extraction strategies when needed

**Key principle for ProcureWatch**  
Crawl4AI is an **optional backend** — you only enable it for portals where it adds value (JS-heavy, messy DOM, content cleaning), keeping the default stack (httpx/lxml/Playwright) for maximum control and lowest dependency surface.

### 3.2 Crawl4AI installation notes for your repo
Baseline install steps:
- `pip install crawl4ai`
- run setup/diagnostics (`crawl4ai-setup`, `crawl4ai-doctor`)
- install Playwright browsers (`playwright install`)

(Reference: Crawl4AI installation and setup docs.)

### 3.3 How ProcureWatch uses Crawl4AI
ProcureWatch adds a backend interface:
- `HttpBackend` (httpx + parsers)
- `PlaywrightBackend` (direct Playwright scripting)
- `Crawl4AIBackend` (Crawl4AI orchestration)

**Quick Mode usage (NEW)**
- Default backend for `quick` runs
- Enables LLM extraction strategies to infer fields
- Produces draft YAML for deterministic promotion

Portal config selects:
- `backend: http` (default)  
- `backend: crawl4ai` for certain portals  
- `fallback_backends: [playwright, http]`

### 3.4 When to use Crawl4AI (decision rule)
Use `crawl4ai` backend if:
- page is heavily JS-rendered and selectors are unstable
- you want clean markdown extraction for “description” sections
- you want to use Crawl4AI’s filtering strategies to remove nav/ads/noise
- deep crawling needs to be configured quickly (seed → follow)

Stay on `http` backend if:
- portal is classic HTML table/list
- data fields are already structured
- you need strict HTTP-level control (e.g., weird headers, special caching, custom client certs)

### 3.5 Crawl4AI vs direct Playwright in ProcureWatch
- Direct Playwright: maximum control; best for custom flows and tricky auth.
- Crawl4AI: faster to get "good enough" content and structured extraction, especially when you want markdown + filtering.

---

## 3.6 SearchFormPortal Specification (NEW in v1.3)

### 3.6.1 Overview
Many procurement portals don't expose a direct listing URL. Instead, they require:
1. Navigation from homepage to search area
2. Filling out a search form (optionally with filters)
3. Submitting the form
4. Extracting results from dynamically-loaded content
5. Handling pagination (often JS-based)

The `SearchFormPortal` plugin type handles this complete workflow.

### 3.6.2 Portal Type: `search_form`
```yaml
portal_type: search_form
```

**Requires**: `PlaywrightBackend` (cannot use HTTP backend)

### 3.6.3 Navigation Steps Configuration
Portals may require multiple navigation steps before reaching the search form:

```yaml
navigation:
  # Steps to reach the search form from seed_url
  steps:
    - action: click
      selector: "a[href*='search']"
      wait_for: ".search-form"
    - action: wait
      duration_ms: 1000
    - action: click
      selector: "#advanced-search-toggle"
      optional: true  # Don't fail if not found
```

**Supported Actions**:
| Action | Parameters | Description |
|--------|------------|-------------|
| `click` | `selector`, `wait_for`, `optional` | Click element, optionally wait for result |
| `wait` | `duration_ms` | Fixed delay |
| `wait_for` | `selector`, `timeout_ms` | Wait for element to appear |
| `scroll` | `direction`, `amount` | Scroll page |
| `hover` | `selector` | Hover over element |

### 3.6.4 Form Filling Configuration
```yaml
search_form:
  # Form container selector
  form_selector: "form#search-form"
  
  # Field mappings
  fields:
    - name: keyword
      selector: "input[name='q']"
      type: text
      value: ""  # Empty = search all
      
    - name: status
      selector: "select#status"
      type: select
      value: "open"  # Only open opportunities
      
    - name: category
      selector: "input#category"
      type: text
      value: ""
      
    - name: date_from
      selector: "input[name='from_date']"
      type: date
      value: "${LAST_RUN_DATE}"  # Dynamic: use last scrape date
      optional: true
      
    - name: results_per_page
      selector: "select#per_page"
      type: select
      value: "100"  # Maximize results per page
      optional: true
  
  # Submit configuration
  submit:
    method: click  # or "enter" to press Enter key
    selector: "button[type='submit']"
    wait_for: ".results-container"
    wait_timeout_ms: 30000
```

**Field Types**:
| Type | Description | Value Format |
|------|-------------|--------------|
| `text` | Text input | String |
| `select` | Dropdown select | Option value or visible text |
| `checkbox` | Checkbox | `true`/`false` |
| `radio` | Radio button | Value of option to select |
| `date` | Date picker | `YYYY-MM-DD` or dynamic variable |
| `autocomplete` | Autocomplete input | Text to type, then select from dropdown |

**Dynamic Variables**:
| Variable | Description |
|----------|-------------|
| `${LAST_RUN_DATE}` | Date of last successful scrape |
| `${TODAY}` | Current date |
| `${TODAY-7d}` | 7 days ago |
| `${TODAY+30d}` | 30 days from now |

### 3.6.5 Results Extraction
After form submission, results are extracted using the standard extraction configuration:

```yaml
extraction:
  listing:
    mode: heuristic_table  # or css_rules, xpath_rules
    # Wait for results to load (important for JS sites)
    wait_for_selector: ".results-table tbody tr"
    wait_timeout_ms: 15000
    # Standard extraction config follows...
```

### 3.6.6 Browser-Based Pagination (NEW in v1.3)
For JS-rendered sites, pagination often requires clicking buttons rather than following URLs:

```yaml
discovery:
  pagination:
    type: click_next  # NEW: click-based pagination
    next_button_selector: "button.next-page, a.pagination-next"
    disabled_class: "disabled"  # Stop when button has this class
    wait_after_click_ms: 2000
    wait_for_selector: ".results-table tbody tr"
    max_pages: 50
    
    # Alternative: load_more pattern
    # type: load_more
    # button_selector: "button.load-more"
    # wait_for_new_items_ms: 2000
    
    # Alternative: infinite_scroll
    # type: infinite_scroll
    # scroll_container: ".results-container"
    # item_selector: ".result-item"
    # scroll_pause_ms: 1500
    # max_scrolls: 20
```

**Pagination Types**:
| Type | Description | Use Case |
|------|-------------|----------|
| `next_link` | Follow href URLs | Static HTML sites |
| `click_next` | Click next button | JS-rendered pagination |
| `load_more` | Click "Load More" button | Single-page load more |
| `infinite_scroll` | Scroll to load content | Infinite scroll sites |
| `page_number` | Click numbered pages | Numbered pagination |

### 3.6.7 Complete SearchFormPortal Example

```yaml
name: alberta_purchasing
display_name: Alberta Purchasing Connection
base_url: https://purchasing.alberta.ca
portal_type: search_form

seed_urls:
  - https://purchasing.alberta.ca/search

backend:
  preferred: playwright
  headless: true
  timeout_seconds: 60

# Navigation to reach search (if needed)
navigation:
  steps: []  # Direct to search page, no navigation needed

# Search form configuration
search_form:
  form_selector: "form, .search-container"
  
  fields:
    - name: keyword
      selector: "input[type='search'], input[name='q']"
      type: text
      value: ""
      
    - name: status
      selector: "select[name='status'], .status-filter"
      type: select
      value: "Open"
      optional: true
  
  submit:
    method: click
    selector: "button[type='submit'], .search-button"
    wait_for: ".search-results, .results-table, table"
    wait_timeout_ms: 30000

# Politeness
politeness:
  concurrency: 1
  min_delay_ms: 2000
  max_delay_ms: 4000

# Discovery
discovery:
  pagination:
    type: click_next
    next_button_selector: "[aria-label='Next'], .next-page, button:has-text('Next')"
    disabled_class: "disabled"
    wait_after_click_ms: 3000
    max_pages: 100
  follow_detail_pages: true

# Extraction
extraction:
  listing:
    mode: heuristic_table
    wait_for_selector: "table tbody tr, .result-row"
    wait_timeout_ms: 15000
    table_selector: "table"
    row_selector: "tbody tr"
    header_aliases:
      external_id:
        - "tender number"
        - "solicitation"
        - "reference"
        - "id"
      title:
        - "title"
        - "description"
        - "name"
      closing_at:
        - "closing date"
        - "deadline"
        - "close date"
      status:
        - "status"
        - "state"
      agency:
        - "ministry"
        - "department"
        - "organization"
        - "buyer"

enabled: true
tags:
  - canada
  - alberta
  - provincial
```

---

## 3.7 PlaywrightBackend Specification (Enhanced in v1.3)

### 3.7.1 Responsibilities
The PlaywrightBackend provides browser automation for:
- JavaScript rendering
- Form interactions (fill, click, submit)
- Navigation sequences
- Screenshot capture for debugging
- Cookie/session persistence
- Human-in-the-loop pause (headed mode for login/captcha)

### 3.7.2 Interface
```python
class PlaywrightBackend(Backend):
    async def fetch(self, request: RequestSpec) -> FetchResult:
        """Fetch URL with JS rendering."""
        
    async def execute_actions(self, actions: list[BrowserAction]) -> ActionResult:
        """Execute a sequence of browser actions."""
        
    async def fill_form(self, form_config: FormConfig) -> FormResult:
        """Fill and submit a form based on config."""
        
    async def wait_for(self, selector: str, timeout_ms: int) -> bool:
        """Wait for element to appear."""
        
    async def click(self, selector: str, wait_for: str | None = None) -> ClickResult:
        """Click element, optionally wait for result."""
        
    async def screenshot(self, path: str, full_page: bool = False) -> str:
        """Capture screenshot for debugging."""
        
    async def get_cookies(self) -> list[dict]:
        """Get current cookies for session persistence."""
        
    async def set_cookies(self, cookies: list[dict]) -> None:
        """Restore cookies from previous session."""
        
    async def pause_for_human(self, message: str) -> None:
        """Pause in headed mode for human intervention (login/captcha)."""
        
    async def close(self) -> None:
        """Close browser."""
```

### 3.7.3 Configuration
```yaml
backend:
  preferred: playwright
  
  # Playwright-specific options
  playwright:
    headless: true  # false for debugging or human-in-the-loop
    browser: chromium  # chromium, firefox, webkit
    viewport:
      width: 1920
      height: 1080
    user_agent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ..."
    
    # Cookie persistence
    cookies:
      persist: true
      path: "data/cookies/${portal_name}.json"
    
    # Screenshot on error
    screenshots:
      on_error: true
      path: "snapshots/${portal_name}/${run_id}/"
    
    # Timeouts
    navigation_timeout_ms: 30000
    action_timeout_ms: 10000
    
    # Stealth mode (avoid bot detection)
    stealth: true
```

### 3.7.4 Action Scripting
For complex navigation flows, actions can be scripted:

```yaml
navigation:
  steps:
    - action: goto
      url: "${base_url}/login"
      
    - action: fill
      selector: "#username"
      value: "${env:PORTAL_USERNAME}"
      
    - action: fill
      selector: "#password"
      value: "${env:PORTAL_PASSWORD}"
      
    - action: click
      selector: "button[type='submit']"
      wait_for: ".dashboard"
      
    - action: pause_for_human
      condition: ".captcha-container"  # Only pause if captcha detected
      message: "Please solve the captcha and press Enter to continue..."
      
    - action: goto
      url: "${base_url}/opportunities/search"
```

### 3.7.5 Error Handling
```python
class BrowserError(Exception):
    """Base exception for browser errors."""

class NavigationTimeout(BrowserError):
    """Page didn't load in time."""

class ElementNotFound(BrowserError):
    """Selector didn't match any element."""

class ActionFailed(BrowserError):
    """Click/fill/submit failed."""

class PageBlocked(BrowserError):
    """Bot detection or access denied."""
```

On errors:
1. Capture screenshot
2. Save page HTML to snapshots
3. Log detailed error with selectors tried
4. Raise appropriate exception for retry/fallback logic

---

## 4. Implementation Blueprint

## 4.1 Architecture overview

**Layers**
1. CLI/TUI (operator interface)
2. Orchestrator (run coordination)
3. Portal plugins (discovery + extraction policy)
4. Backends (http / playwright / crawl4ai)
5. Extract/Normalize (canonical mapping + confidence)
6. Persistence (DB + migrations)
7. Observability (logs, snapshots, run metrics)
8. Scheduler (APScheduler + run locks)

---

## 4.2 Repository layout (recommended)

```
procurewatch/
  apps/
    cli/                        # Typer commands, Rich output
    tui/                        # Textual (optional)
  core/
    config/
      loader.py                 # YAML->Pydantic model
      models.py                 # PortalConfig, SchedulerConfig
      synonyms.py               # header aliases dictionary
    orchestrator/
      runner.py                 # runs, checkpointing, backoff
      locks.py                  # run locks
    portals/
      base.py                   # PortalPlugin interface
      generic_table.py          # table/list portals
      generic_cards.py          # card/list portals
      platform_s2g.py           # platform-like portals (optional)
    backends/
      base.py                   # Backend interface
      http_backend.py           # httpx + parser
      playwright_backend.py     # direct Playwright
      crawl4ai_backend.py       # Crawl4AI adapter
    fetch/
      throttling.py             # rate limits, concurrency
      retries.py                # tenacity wrappers
      caching.py                # ETag/If-Modified-Since
    extract/
      structured.py             # JSON-LD, embedded json
      heuristic_table.py        # header mapping + row parsing
      rules.py                  # selectors + portal hints
      confidence.py             # scoring + drift triggers
    normalize/
      canonical.py              # canonical Opportunity model
      parsing.py                # dates, money, status, vendors
      diff.py                   # compute differences
    persistence/
      db.py                     # engine/session
      models.py                 # SQLAlchemy tables
      repo.py                   # repositories
      migrations/               # Alembic
    scheduler/
      service.py                # APScheduler wiring
      jobs.py                   # job definitions
  configs/
    app.yaml
    portals/
      nevadaepro.yaml
      clarkcounty.yaml
      apc_alberta.yaml
  snapshots/                    # HTML / artifacts (optional)
  logs/
  tests/
  pyproject.toml
```

---

## 4.3 Core Interfaces (contracts)

### 4.3.1 PortalPlugin (core/portals/base.py)
**Responsibilities**
- define discovery policy (seed urls, pagination)
- choose extraction approach (backend + extractors)
- produce canonical `OpportunityDraft` objects from listing + detail pages

**Interface**
- `get_seed_requests(config) -> list[RequestSpec]`
- `discover_listing_pages(ctx) -> AsyncIterator[PageSpec]`
- `extract_listing(ctx, page) -> list[ListingItem]`
- `extract_detail(ctx, listing_item) -> OpportunityDraft`
- `postprocess(ctx, opportunity) -> OpportunityDraft`

### 4.3.2 Backend (core/backends/base.py)
**Responsibilities**
- fetch a URL and return HTML/DOM + response metadata
- optional “render” for JS
- session/cookies handling

**Interface**
- `fetch(request: RequestSpec) -> FetchResult`
- `render(request: RequestSpec) -> RenderResult` (optional)
- `close()`

### 4.3.3 Extractors (core/extract/*)
- `StructuredExtractor.extract(dom) -> dict`
- `HeuristicTableExtractor.extract(dom) -> list[dict] + mapping_report`
- `RuleExtractor.extract(dom, rules) -> dict`

### 4.3.4 Normalizer (core/normalize/*)
- `normalize_opportunity(raw: OpportunityDraft) -> OpportunityCanonical`
- `compute_fingerprint(opportunity) -> str`
- `compute_diff(old, new) -> dict`

### 4.3.5 Persistence (core/persistence/repo.py)
- `upsert_opportunity(opportunity) -> (opportunity_id, event_type, diff)`
- `append_event(opportunity_id, event_type, diff, run_id)`
- `record_run_summary(run)`

### 4.3.6 Scheduler (core/scheduler/service.py)
- `schedule_add(name, portals, rrule, jitter_minutes, enabled)`
- `schedule_run(job_id)`
- `schedule_pause(job_id)`
- `schedule_list()`

---

## 4.4 Data Model (SQL tables)

### 4.4.1 Tables
- `portals`
- `opportunities`
- `opportunity_events`
- `documents`
- `awards`
- `scrape_runs`
- `page_snapshots`
- `scheduled_jobs` (NEW)
- `job_runs` (NEW, optional; link schedule → scrape_run)

### 4.4.2 scheduled_jobs (fields)
- `id`
- `name`
- `enabled`
- `portals_json` (list of portal names/ids)
- `schedule_type` (daily/weekday/hourly/cron)
- `time_of_day` (HH:MM)
- `timezone` (default: local)
- `jitter_minutes`
- `blackout_start`, `blackout_end` (optional)
- `max_runtime_minutes`
- `created_at`, `updated_at`

### 4.4.3 Overlap protection
- `locks` table (optional) or OS file lock + DB advisory locks for Postgres
- On schedule trigger:
  - attempt to acquire global run lock
  - attempt per-portal lock(s)
  - if locked, skip or reschedule with backoff

---

## 4.5 Portal YAML Config Schema (example)

```yaml
name: "clarkcounty_current_opportunities"
base_url: "https://www.clarkcountynv.gov"
portal_type: "generic_table"
seed_urls:
  - "https://www.clarkcountynv.gov/business/business_opportunities/current-opportunities/"
backend:
  preferred: "http"
  fallbacks: ["playwright", "crawl4ai"]
politeness:
  concurrency: 2
  min_delay_ms: 800
  max_delay_ms: 2500
  respect_robots_txt: true
discovery:
  pagination:
    type: "next_link"
    selector_hint: "a[rel='next']"
extraction:
  listing:
    mode: "heuristic_table"
    header_aliases:
      solicitation: ["bid #", "solicitation #", "reference", "id"]
      closing_at: ["closing", "deadline", "bid due", "due date"]
  detail:
    mode: "rules"
    fields:
      description_summary:
        selectors: ["#main-content", "article", ".content"]
        clean: true
```

---

## 4.6 Crawl4AI Backend Adapter (design)

### 4.6.1 Adapter goals
- Make Crawl4AI “look like” a backend that returns:
  - rendered HTML (if needed)
  - clean markdown for description extraction
  - optional structured extraction results

### 4.6.2 Inputs from portal config
- whether to:
  - run headless or headed
  - enable caching
  - run JS code
  - store state (cookies/session)
  - apply content filters (noise removal)

### 4.6.3 Outputs
- `RenderResult.html`
- `RenderResult.markdown`
- `RenderResult.screenshots` (optional)
- `RenderResult.links` (optional)
- `RenderResult.metadata` (status, timing, etc.)

---

## 4.7 CLI commands (expanded)

### 4.7.1 Setup
- `procurewatch init`
- `procurewatch db migrate`
- `procurewatch portal add`
- `procurewatch portal test <portal>`

### 4.7.2 Running scrapes
- `procurewatch scrape --portal <name> [--since 30d] [--max-pages N]`
- `procurewatch scrape --all [--since 7d]`

### 4.7.2a Quick mode (NEW)
- `procurewatch quick --url <seed> --max-pages N [--keywords "..."] [--since 30d]`
- `procurewatch quick promote --run-id <id>`

### 4.7.3 Scheduler (NEW)
- `procurewatch schedule add --name daily_nv --portals nevadaepro,clarkcounty --daily 06:15 --jitter 12m`
- `procurewatch schedule list`
- `procurewatch schedule pause <job>`
- `procurewatch schedule resume <job>`
- `procurewatch schedule run-now <job>`

### 4.7.4 Data views
- `procurewatch opportunities list --status OPEN --closing-within 7d`
- `procurewatch opportunities show <id>`
- `procurewatch runs list`
- `procurewatch runs show <run_id>`
- `procurewatch export --format csv --query "<sqlish filter>"`

---

## 4.8 Checkpointing & Resume (recommended)
Checkpoint granularity:
- per portal
- per listing page
- per detail page

Store:
- last successful page cursor
- last successful opportunity id
- run id

If interrupted:
- resume from last checkpoint
- do not double-write duplicates (dedupe protects)

---

## 4.9 Logging & Snapshots

### 4.9.1 Structured logs
- JSON logs to file
- Rich console rendering for operator

### 4.9.2 Snapshot rules
Store HTML snapshot when:
- extraction confidence < threshold
- unexpected 403/429 loops
- DOM mismatch vs historical signature
- “blocked” events

Snapshots indexed by:
- portal
- run id
- url
- failure reason

---

## 4.10 Acceptance Tests (must-pass)

### AT1 — Dedupe
- Same portal run twice yields zero duplicate opportunities.

### AT2 — Updates tracked
- Change a closing date and confirm an `UPDATED` event with diff.

### AT3 — Scheduling
- Daily schedule triggers run at expected time (+ jitter) and writes `scrape_runs`.

### AT4 — Backends
- For a JS-heavy page:
  - `http` fails to extract, then fallback `crawl4ai` or `playwright` succeeds.
- For a table page:
  - `http` succeeds without browser overhead.

### AT5 — Drift detection
- Break header mapping; confirm `LAYOUT_DRIFT` event + snapshot saved.

---

## 5. Development Plan (milestones)

### M0 — Project scaffold ✅ COMPLETE
- repo skeleton, config loader, logging, DB models/migrations

### M1 — Generic HTTP scraper + heuristic mapping ✅ COMPLETE
- http backend
- generic_table plugin
- upsert + events

### M2 — Playwright Backend + SearchFormPortal ✅ COMPLETE (ENHANCED in v1.3)
**Components**:
- `PlaywrightBackend` - browser automation backend
  - JavaScript rendering
  - Cookie persistence and session handling
  - Screenshot capture on errors
  - Human-in-the-loop pause (headed mode for login/captcha)
  - Stealth mode for bot detection avoidance
- `SearchFormPortal` - form-based portal plugin
  - Homepage → search navigation steps
  - Form field filling (text, select, checkbox, date, autocomplete)
  - Dynamic variables (${LAST_RUN_DATE}, ${TODAY}, etc.)
  - Form submission and result waiting
- Browser-based pagination
  - Click-based "Next" button
  - "Load More" pattern
  - Infinite scroll handling
  - Wait-for-element logic
- `ScrapeRunner` enhancements
  - Route `search_form` portal type to `SearchFormPortal`
  - Route `playwright` backend preference to `PlaywrightBackend`
  - Fallback chain: http → playwright → crawl4ai

**Deliverables**:
- `src/procurewatch/core/backends/playwright_backend.py`
- `src/procurewatch/core/portals/search_form.py`
- Updated `ScrapeRunner._create_backend()` and `_create_plugin()`
- Example config: `configs/portals/alberta_purchasing.yaml`

**Acceptance Tests**:
- AT-M2.1: JS-rendered page scrapes successfully with Playwright
- AT-M2.2: Search form fills, submits, and extracts results
- AT-M2.3: Click-based pagination traverses multiple pages
- AT-M2.4: Cookie persistence works across runs
- AT-M2.5: Screenshot captured on extraction failure

### M3 — Scheduler ✅ COMPLETE
- APScheduler service
- schedule CLI
- job storage + run locks

### M4 — Crawl4AI backend ✅ COMPLETE
- crawl4ai adapter
- per-portal backend selection
- markdown capture for descriptions
- LLM extraction with content pruning
- Multi-provider support: Groq (FREE), DeepSeek, OpenAI, Ollama, Gemini

### M4.5 — Quick Mode ✅ COMPLETE (NEW)
- quick CLI flow
- crawl4ai LLM extraction integration for inferred schema
- pagination heuristics for quick runs (single-page only for now)
- draft YAML generation from quick runs
- content pruning for free tier LLM limits

### M4.6 — Smart Extraction Enhancement (Phase 1) ✅ COMPLETE (2026-02-03)
**Reference**: `SMART_EXTRACTION_PLAN.md` Phase 1

**Components Delivered**:
- `PageAnalyzer` class (`core/analysis/page_analyzer.py`, 850+ lines)
  - DOM-based page structure analysis (no LLM needed)
  - Page type classification: `search_form`, `results_table`, `results_cards`, `error_page`, `empty_results`
  - Pagination metadata extraction: "1-25 of 1448" → `total_records=1448`, `records_per_page=25`
  - Search form detection with submit button identification
  - Error page detection with strict patterns (no false positives)
  - CAPTCHA and login requirement detection
- Pre-flight integration in `crawl4ai_backend.py`
  - Runs analysis BEFORE LLM extraction
  - Auto-clicks search button when form detected
- CLI output enhancement (`cli/commands/quick.py`)
  - Shows total records detected, page type, pre-flight timing

**Test Results**:
- Alberta Purchasing: 10 opps, 96.4% confidence, `results_cards` ✅
- Nevada ePro: Pagination detected (1,448 records), no false positive errors ✅
- Unit tests: All passing (`test_phase1.py`) ✅

**Acceptance Criteria Met**:
- ✅ Pagination metadata extracted from DOM (no LLM)
- ✅ Search form auto-detection and auto-click
- ✅ Page type classification accurate
- ✅ Error page detection strict (no false positives)
- ✅ Pre-flight analysis adds ~3-4s but provides valuable metadata

### M5 — Export & operational polish
- export formats
- dashboards
- alerts (optional)

---

## 6. Appendix — Commercial Readiness (Phase 2 Addendum)

**Purpose**: Extend the current roadmap without changing scope. This addendum targets commercial-scale reliability and Firecrawl-level extraction density while preserving the existing milestones.

**Out of scope for current PRD**:
- No public API/PaaS in this phase
- No customer-facing UI/dashboard buildout beyond M5
- No billing, tenancy, or enterprise auth

**Phase 2 Themes (aligned to current plans)**:
- Confidence Overhaul (SMART_EXTRACTION_PLAN Phase 2)
- Deep Scrape Enhancement (M4.5 baseline)
- IP/Proxy Rotation (future enhancement in AGENTS.md)
- Export & Polish (M5)
- Validation across more portals

### CR-1 — Auth Reliability Layer
**Goal**: Eliminate partial/blocked pages mixed with results.

**Deliverables**:
- Detect login-required states and pause/auto-login before extraction
- Session manager for storage-state reuse and re-login triggers
- Portal-level auth scripts (replayable steps)

**Success metrics**:
- 95%+ pages classified as clean results vs login/blocked
- 80%+ reduction in mixed-content pages on protected portals

### CR-2 — Proxy + Anti-Bot Layer
**Goal**: Scale to protected procurement sites at volume.

**Deliverables**:
- Proxy configuration in all backends (single + rotation)
- Adaptive throttling on 429/blocked signals
- Per-domain rate budgets with jitter

**Success metrics**:
- 2x successful page throughput on protected portals
- <5% blocked pages on repeat runs (same portal)

### CR-3 — Extraction Fidelity for Tables
**Goal**: Preserve dense, Firecrawl-level data with canonical fields.

**Deliverables**:
- Table schema inference (dedupe repeated headers, map to canonical fields)
- Preserve link/value pairs and column order
- Capture unmapped columns into structured custom_fields

**Success metrics**:
- 90%+ of table columns preserved across 10+ complex portals
- 95%+ of rows retain primary identifiers and links

### CR-4 — Deep Scrape Enrichment
**Goal**: High-value detail capture at scale.

**Deliverables**:
- Always follow detail URLs when present
- Detail extraction cache + resume
- Attachments, contact info, requirements

**Success metrics**:
- 80%+ of listings enriched with detail fields
- 50%+ increase in average field count per opportunity

### CR-5 — Warehouse-Ready Normalization
**Goal**: Enable downstream data warehouse use.

**Deliverables**:
- Normalize agency/organization names
- Standardize location + classification codes
- Preserve raw_data for reprocessing

**Success metrics**:
- 95%+ of records mapped to normalized organization dimension
- 80%+ of records carry standardized location metadata

### CR-6 — Export & Interop
**Goal**: Make data portable for BI and warehousing.

**Deliverables**:
- JSONL/CSV exports at scale
- Stable schema versioning for exports
- Portal-level export filters

**Success metrics**:
- 1M+ records exported without memory failures
- Zero schema breaking changes within a release

## 7. Appendix — Recommended Dependencies (pyproject)

**CLI/TUI**
- typer, rich, textual (optional)

**HTTP/Parsing**
- httpx, lxml or selectolax, beautifulsoup4 (fallback), orjson

**Browser**
- playwright
- crawl4ai (optional backend)

**DB**
- sqlalchemy, alembic, psycopg (postgres), aiosqlite (sqlite async optional)

**Resilience**
- tenacity
- apscheduler

---

## 8. Notes on “free vs paid”
Crawl4AI is open-source and installable locally as a Python package, making it a better fit for your “local-first, no paid API dependency” requirement.

---

END
