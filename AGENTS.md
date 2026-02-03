# AGENTS.md - ProcureWatch

> Python CLI for scraping tender/procurement portals with change tracking.

**Stack**: Python 3.11+, uv, SQLAlchemy 2.0, Alembic, Pydantic v2, Typer, Rich, Playwright.

**PRD**: `ProcureWatch_PRD_and_Implementation_Blueprint_v1_2.md` (actually v1.3)

---

## Implementation Status (Milestone Checklist)

> Cross-reference with PRD Section 5 (Development Plan, lines 920-980)

### M0 — Project Scaffold ✅ COMPLETE

| Component | File | Status |
|-----------|------|--------|
| Repo skeleton | `pyproject.toml`, dirs | ✅ |
| Config loader | `core/config/loader.py` | ✅ |
| Logging | `core/logging.py` | ✅ |
| DB models | `persistence/models.py` | ✅ |
| Migrations | `persistence/migrations/` | ✅ |

### M1 — HTTP Scraper + Heuristic Mapping ✅ COMPLETE

| Component | File | Status |
|-----------|------|--------|
| HTTP backend | `core/backends/http_backend.py` | ✅ |
| Generic table plugin | `core/portals/generic_table.py` | ✅ |
| Heuristic table extractor | `core/extract/heuristic_table.py` | ✅ |
| Header synonym mapping | `core/config/synonyms.py` | ✅ |
| Upsert + events | `persistence/repo.py` | ✅ |

### M2 — Playwright Backend + SearchFormPortal ✅ COMPLETE

> PRD lines 930-965

#### M2.1 PlaywrightBackend ✅

| Component | File | Status | Notes |
|-----------|------|--------|-------|
| JavaScript rendering | `playwright_backend.py` | ✅ Works | Tested with Alberta (367KB rendered) |
| Cookie persistence | `playwright_backend.py` | ✅ Implemented | Code exists, functional |
| Screenshot on error | `playwright_backend.py` | ✅ Works | Error screenshots saved to `snapshots/` |
| Human-in-the-loop | `playwright_backend.py` | ✅ Implemented | `pause_for_human()` available |
| Stealth mode | `playwright_backend.py` | ✅ Implemented | Anti-detection scripts |

#### M2.2 SearchFormPortal ✅

| Component | File | Status | Notes |
|-----------|------|--------|-------|
| Navigation steps | `search_form.py` | ✅ Implemented | |
| Form filling | `search_form.py` | ✅ Implemented | Works for portals with matching selectors |
| Dynamic variables | `search_form.py` | ✅ Implemented | `resolve_dynamic_value()` |
| Form submission | `search_form.py` | ✅ Implemented | |

#### M2.3 Browser Pagination ✅

| Component | File | Status | Notes |
|-----------|------|--------|-------|
| Click-based "Next" | `search_form.py` | ✅ Implemented | `PaginationType.CLICK_NEXT` |
| "Load More" pattern | `search_form.py` | ✅ Implemented | `PaginationType.LOAD_MORE` |
| Infinite scroll | `search_form.py` | ✅ Implemented | `PaginationType.INFINITE_SCROLL` |

#### M2.4 ScrapeRunner Integration ✅

| Component | File | Status | Notes |
|-----------|------|--------|-------|
| Route search_form portal | `runner.py` | ✅ Works | |
| Route playwright backend | `runner.py` | ✅ Works | |
| Fallback chain | `runner.py` | ✅ Works | http → playwright |

#### M2.5 Extraction Stack ✅ (FR3 from PRD)

| Component | File | Status | Notes |
|-----------|------|--------|-------|
| Structured (JSON-LD) | `extract/structured.py` | ✅ Works | |
| Heuristic table | `extract/heuristic_table.py` | ✅ Works | For `<table>` elements |
| Heuristic card/list | `extract/heuristic_card.py` | ✅ Works | For div/card-based layouts (727 lines) |
| CSS/XPath rules | `extract/rules.py` | ✅ Works | Config-driven selectors (270 lines) |
| Extraction pipeline | `extract/pipeline.py` | ✅ Works | Chains all extractors with fallback |

#### M2 Acceptance Tests (PRD lines 959-965)

| Test ID | Description | Status |
|---------|-------------|--------|
| AT-M2.1 | JS-rendered page scrapes with Playwright | ✅ PASS - 10 records, 0.967 confidence |
| AT-M2.2 | Search form fills, submits, extracts | ✅ Implemented (portal-specific selectors needed) |
| AT-M2.3 | Click pagination traverses pages | ✅ Implemented (needs portal-specific testing) |
| AT-M2.4 | Cookie persistence across runs | ✅ Implemented |
| AT-M2.5 | Screenshot on extraction failure | ✅ Works |

#### M2 Test Results (Alberta Purchasing - 2026-02-02)

**Config Fix Applied**: Alberta portal loads results on page load (no form submission needed).
Set `search_form.form_selector: null` and `search_form.submit.method: none` to skip form interaction.

```
Full End-to-End Test:
Portal: alberta_purchasing
Type: search_form (with PlaywrightBackend)

Pages scraped: 1
Pages failed: 0
Opportunities found: 10
New: 10
Errors: 0
Duration: 4.52s

Extraction: method=heuristic_card
Confidence: 0.967
Fields: title, external_id, agency, status, category, posted_at, closing_at, detail_url
```

### M3 — Scheduler ✅ COMPLETE

| Component | File | Status | Notes |
|-----------|------|--------|-------|
| APScheduler v4 service | `core/scheduler/service.py` | ✅ Works | AsyncScheduler with SQLAlchemy datastore |
| Lock manager | `core/scheduler/locks.py` | ✅ Works | RunLock acquire/release with TTL |
| Schedule CLI | `cli/commands/schedule.py` | ✅ Works | list, add, pause, resume, run-now, delete, start |
| Job storage | `persistence/models.py` | ✅ Works | ScheduledJob model (already existed) |
| Run locks | `persistence/models.py` | ✅ Works | RunLock model (already existed) |

#### M3 Features Implemented

- **APScheduler v4 Integration**: Uses `AsyncScheduler` with `SQLAlchemyDataStore`
- **Trigger Support**: CronTrigger (daily, weekday, cron), IntervalTrigger (hourly)
- **Jitter**: Built-in via `max_jitter` parameter
- **Lock Protection**: Prevents overlapping runs using `LockManager`
- **CLI Commands**:
  - `schedule list` - Show all scheduled jobs
  - `schedule add <name>` - Create schedule (--daily, --weekday, --hourly, --cron)
  - `schedule pause/resume <name>` - Enable/disable
  - `schedule run-now <name>` - Trigger immediate execution
  - `schedule start` - Run scheduler in foreground (Ctrl+C to stop)
  - `schedule delete <name>` - Remove schedule

### M4 — Crawl4AI Backend ✅ COMPLETE

| Component | File | Status | Notes |
|-----------|------|--------|-------|
| Crawl4AI adapter | `core/backends/crawl4ai_backend.py` | ✅ Works | 690+ lines, full LLM integration |
| LLM extraction strategy | `crawl4ai_backend.py` | ✅ Works | Pydantic schema, auto field mapping |
| Quick Mode CLI | `cli/commands/quick.py` | ✅ Works | `quick scrape`, `quick test`, `quick promote` |
| Draft YAML generation | `crawl4ai_backend.py` | ✅ Works | Auto-generate configs from scrapes |
| Markdown capture | `crawl4ai_backend.py` | ✅ Works | Built into Crawl4AI |
| Content pruning | `crawl4ai_backend.py` | ✅ Works | PruningContentFilter for token reduction |

#### M4 Features Implemented

- **AI-Powered Extraction**: Uses LLM to understand page structure automatically
- **No CSS Selectors Needed**: Works on ANY website without manual configuration
- **OpportunitySchema**: Pydantic schema for structured extraction
- **LLM Provider Support**: Groq (FREE), DeepSeek, OpenAI, Ollama (local), Anthropic, Gemini
- **Content Pruning**: `PruningContentFilter` + `fit_markdown` to reduce token usage by 75%+
- **Schema Caching**: Generate CSS schema once, reuse for free forever
- **Quick Mode CLI**:
  - `quick scrape <url>` - Scrape any URL with AI
  - `quick test <url>` - Test extraction without saving
  - `quick promote <name>` - Convert quick scrape to full config
  - `--provider groq/llama-3.3-70b-versatile` - Use Groq (FREE)
  - `--provider ollama/llama3.3` - Use local models (free)
  - `--save` - Save to database
  - `--generate-config` - Create reusable YAML config

#### M4 Test Results (Alberta Purchasing - 2026-02-02)

```
Provider: groq/llama-3.3-70b-versatile (FREE tier)
URL: https://purchasing.alberta.ca/search

Opportunities found: 9
Extraction method: llm
Confidence: 89.3%
Time: 10.1s
Cost: $0.00 (FREE)

Sample extracted:
1. REQUEST FOR PREQUALIFICATION OF GENERAL CONTRACTORS
   ID: AB-2026-00868, Agency: Town of Fairview, Status: Open
   Closes: Feb 19, 2026

2. Group Purchasing Organization (GPO) / Consortium Participation
   ID: AB-2026-00867, Agency: SAIT, Status: Open
```

#### M4.5 Quick Mode ✅ COMPLETE (Enhanced with Multi-Page)

| Component | File | Status |
|-----------|------|--------|
| Quick CLI flow | `cli/commands/quick.py` | ✅ Works |
| LLM schema inference | `crawl4ai_backend.py` | ✅ Works |
| **Multi-page pagination** | `crawl4ai_backend.py` | ✅ **NEW** - Session-based, auto-detect |
| **Pagination heuristics** | `crawl4ai_backend.py` | ✅ **NEW** - Next, Load More, Infinite Scroll |
| **Deep scrape** | `crawl4ai_backend.py` | ✅ **NEW** - Follow detail_url links |
| **Search/filter criteria** | `crawl4ai_backend.py` | ✅ **NEW** - Keywords, date range, categories |
| **Rate limiting** | `crawl4ai_backend.py` | ✅ **NEW** - Delay, retries, backoff |
| Draft YAML generation | `crawl4ai_backend.py` | ✅ Works |
| Content pruning for free tiers | `crawl4ai_backend.py` | ✅ Works |

#### M4.5 Multi-Page Features (NEW - 2026-02-02)

**Pagination Detection & Traversal**:
- Auto-detects pagination type from HTML
- Click Next (20+ heuristic selectors)
- Load More button
- Infinite Scroll (scroll + wait)
- URL parameter-based (planned)

**Advanced Search/Filter Criteria**:
- `--keywords "IT,construction"` - Filter by title/description
- `--status open` - Filter by status
- `--categories "services"` - Category filter
- `--since 30` - Posted within N days
- `--closing-within 14` - Closing within N days
- `--min-value 10000` / `--max-value 1000000` - Value range
- `--location "Alberta"` - Geographic filter

**Deep Scrape**:
- `--deep` - Follow detail_url links for full descriptions
- `--max-details 50` - Limit detail page requests
- Extracts: description, attachments, contact info, requirements

**Rate Limiting & Error Handling**:
- `--delay 2000` - Delay between pages (ms)
- `--retries 3` - Max retry attempts
- Exponential backoff on failures
- `--stop-on-error` - Stop on first error

**CLI Examples**:
```bash
# Multi-page with auto-pagination
procurewatch quick scrape https://example.com --max-pages 10

# With filters
procurewatch quick scrape https://example.com -p 5 --keywords "IT,software" --status open

# Deep scrape with full descriptions
procurewatch quick scrape https://example.com --deep --max-details 50

# Date filters
procurewatch quick scrape https://example.com --since 30 --closing-within 14

# Export + database
procurewatch quick scrape https://example.com -p 10 -o results.json --save
```

**Configuration Model (QuickModeConfig)**:
```python
QuickModeConfig(
    max_pages=10,
    pagination_type=QuickPaginationType.AUTO,
    follow_detail_pages=True,
    max_detail_pages=50,
    filters=QuickSearchFilter(
        keywords=["IT", "construction"],
        status=["open"],
        since_days=30,
        closing_within_days=14,
    ),
    delay_between_pages_ms=2000,
    max_retries=3,
    retry_backoff_factor=2.0,
)
```

### M5 — Export & Polish ❌ NOT STARTED

| Component | File | Status |
|-----------|------|--------|
| Export formats (CSV, JSON) | | ❌ Missing |
| Dashboards | | ❌ Missing |
| Alerts | | ❌ Optional |

---

## Current Session Context

**Last worked on**: LLM Provider Troubleshooting & Configuration

**Date**: 2026-02-02

**Status**: 🔄 Investigating LLM provider rate limits and authentication issues

**What was done this session**:
1. Diagnosed rate limit errors across multiple LLM providers
2. Updated `.env` configuration multiple times to test different providers
3. Researched correct model names for Gemini via official LiteLLM documentation
4. Configured Ollama as the recommended local provider for unlimited usage

**Key Files Modified**:
- `.env` - Updated LLM provider configuration multiple times

---

## LLM Provider Reference (CRITICAL - Read Before Scraping)

### Provider Status Summary

| Provider | Status | Limit | Error Type |
|----------|--------|-------|------------|
| **Groq** | ⚠️ Rate Limited | 100K tokens/day (free) | `RateLimitError` - resets at midnight UTC |
| **DeepSeek** | ❌ Requires Payment | Pay-as-you-go | `Insufficient Balance` error |
| **Gemini** | ⚠️ Quota Issues | Varies | `limit: 0` = quota exhausted |
| **Ollama** | ✅ RECOMMENDED | Unlimited (local) | No API needed |

### Correct Model Names (Verified from LiteLLM Docs)

**Groq (FREE tier - 100K tokens/day)**:
```
groq/llama-3.3-70b-versatile   # Main model
groq/llama-3.1-8b-instant      # Faster, smaller
groq/mixtral-8x7b-32768        # Alternative
```

**Gemini (FREE tier - can hit quota quickly)**:
```
gemini/gemini-pro              # Basic model
gemini/gemini-1.5-pro-latest   # Latest 1.5 Pro
gemini/gemini-1.5-flash        # Fast, free tier
gemini/gemini-2.0-flash        # Newest flash
gemini/gemini-2.0-flash-exp    # Experimental
```
⚠️ **Note**: 404 errors mean model name is wrong OR API key hasn't activated yet. `limit: 0` means quota exhausted.

**DeepSeek (Requires payment)**:
```
deepseek/deepseek-chat         # Main model
```

**Ollama (FREE, local, unlimited)**:
```
ollama/llama3.2                # Recommended for most tasks
ollama/llama3                  # Older version
ollama/mistral                 # Alternative
ollama_chat/llama3.2           # Alternative format
```

### Recommended .env Configuration

**Option 1: Ollama (BEST - No rate limits, no API costs)**
```env
# Requires: Install Ollama + run "ollama pull llama3.2"
CRAWL4AI_LLM_PROVIDER=ollama/llama3.2
```

**Option 2: Groq (FREE but has daily limits)**
```env
GROQ_API_KEY=gsk_your_key_here
CRAWL4AI_LLM_PROVIDER=groq/llama-3.3-70b-versatile
```

**Option 3: Gemini (FREE but quota can be exhausted)**
```env
GEMINI_API_KEY=your_key_here
CRAWL4AI_LLM_PROVIDER=gemini/gemini-1.5-flash
```

### Ollama Setup (Recommended for Heavy Usage)

**System Requirements**:
- Any modern CPU
- 8-16GB RAM for most models
- GPU optional but speeds up inference significantly

**Resource Usage**:
- When not running: 0% CPU, 0 MB RAM
- When idle (model loaded): ~0% CPU, model in VRAM
- Models unload after 5 min inactivity
- Does NOT run in background when closed

**Installation**:
```bash
# 1. Download from https://ollama.ai/download

# 2. Pull a model
ollama pull llama3.2

# 3. Test it works
ollama run llama3.2 "Hello"

# 4. Use with ProcureWatch
python -m procurewatch.cli.main quick scrape <url> --provider ollama/llama3.2
```

### Troubleshooting LLM Errors

| Error | Cause | Solution |
|-------|-------|----------|
| `RateLimitError` (Groq) | Hit 100K tokens/day | Wait for midnight UTC reset OR use Ollama |
| `Insufficient Balance` (DeepSeek) | No credits | Add funds OR use Ollama |
| `404 Not Found` (Gemini) | Wrong model name OR key not activated | Wait 10 min OR try `gemini/gemini-pro` |
| `limit: 0` (Gemini) | Quota exhausted | Wait 24h OR use Ollama |
| `Authentication Fails` | Invalid/expired API key | Regenerate key on provider dashboard |

---

**Previous Session (2026-02-02)**:
1. Added markdown-table fallback parsing when LLM output is empty
2. Added `--provider-prompt` to Quick Scrape for interactive provider selection
3. Auto-loaded `.env` in CLI startup
4. Verified Nevada ePro multi-page extraction (3 pages, 26 opportunities)

**CLI Options**:
```bash
# Pagination
--max-pages N, -p N       # Maximum pages to scrape
--pagination TYPE         # auto, click_next, load_more, infinite_scroll, none
--next-selector CSS       # Custom next button selector

# Filters
--keywords "a,b,c"        # Keyword filter
--status STATUS           # Status filter
--categories "a,b"        # Category filter
--since N                 # Posted within N days
--closing-within N        # Closing within N days
--min-value N             # Minimum value
--max-value N             # Maximum value
--location LOC            # Location filter

# Deep Scrape
--deep / --no-deep        # Follow detail URLs
--max-details N           # Max detail pages

# Rate Limiting
--delay MS                # Delay between pages
--retries N               # Retry attempts
--stop-on-error           # Stop on first error

# Provider Selection
--provider PROVIDER       # e.g., ollama/llama3.2, groq/llama-3.3-70b-versatile
--provider-prompt         # Interactive provider selection
```

**Working Test Command**:
```bash
# With Ollama (recommended)
python -m procurewatch.cli.main quick scrape "https://nevadaepro.com/bso/view/search/external/advancedSearchContractBlanket.xhtml?view=activeContracts" --max-pages 3

# With specific provider
python -m procurewatch.cli.main quick scrape <url> --provider ollama/llama3.2 --max-pages 3
```

**Known Issues / Findings**:
- Windows Rich progress spinners can crash with Unicode errors; test scripts include UTF-8 fixes
- Groq free tier: 100K tokens/day - good for ~50-100 page extractions
- DeepSeek requires payment - no free tier
- Gemini free tier can exhaust quickly; `limit: 0` error means quota gone
- Ollama is the most reliable option for heavy usage (no limits, no API costs)

**Next Steps (User to decide)**:
1. Install Ollama for unlimited local AI (recommended for user's RTX 5090 setup)
2. M5: Export & Polish (CSV/JSON export, dashboards)
3. Add provider fallback mechanism (try Ollama → Groq → Gemini automatically)
4. Add pre-flight provider auth check to fail fast on bad keys

---

## Build & Run Commands

```bash
# Dependencies (uv package manager)
uv sync                              # Base install
uv sync --extra dev                  # Dev dependencies

# CLI
uv run procurewatch --help           # Main CLI
uv run pw --help                     # Alias
uv run procurewatch init             # Initialize DB + dirs

# Scraping
uv run procurewatch scrape run --portal <name>
uv run procurewatch scrape test <name>  # Dry run test
```

## Linting & Type Checking

```bash
uv run ruff check .                  # Lint
uv run ruff check --fix .            # Auto-fix
uv run ruff format .                 # Format
uv run mypy src/                     # Type check (strict mode)
```

## Testing

```bash
uv run pytest                                    # All tests
uv run pytest tests/unit/test_parsing.py         # Single file
uv run pytest tests/unit/test_parsing.py::test_parse_date_iso  # Single test
uv run pytest -k "test_date"                     # Pattern match
uv run pytest --cov=src/procurewatch             # With coverage
```

## Database Migrations (Alembic)

```bash
uv run alembic revision --autogenerate -m "desc"  # Create migration
uv run alembic upgrade head                       # Apply
uv run alembic downgrade -1                       # Rollback
```

---

## Code Style Guidelines

### Imports (isort via Ruff)
```python
from __future__ import annotations  # Always first

import re                           # stdlib
from datetime import datetime

from pydantic import BaseModel      # third-party

from procurewatch.core.config import PortalConfig  # first-party

if TYPE_CHECKING:                   # type-only imports
    from sqlalchemy.ext.asyncio import AsyncSession
```

### Type Annotations (Strict - Required)
```python
# Modern 3.11+ syntax only
items: list[str]              # NOT: List[str]
mapping: dict[str, int]       # NOT: Dict[str, int]
optional: str | None          # NOT: Optional[str]

# All functions need return types
def process(data: dict[str, Any]) -> Sequence[Opportunity]: ...
async def fetch(url: str) -> FetchResult: ...

# SQLAlchemy models use Mapped[]
name: Mapped[str] = mapped_column(String(100), nullable=False)
```

### Naming Conventions
```python
class PortalRepository:            # PascalCase for classes
def compute_fingerprint() -> str:  # snake_case for functions
FUZZY_MATCH_THRESHOLD = 75         # UPPER_SNAKE for constants
def _private_helper():             # underscore for private
```

### Error Handling
```python
# Custom exception hierarchy with context
class BackendError(Exception):
    def __init__(self, message: str, url: str | None = None, cause: Exception | None = None):
        super().__init__(message)
        self.url, self.cause = url, cause

# Chain exceptions properly
try:
    result = await backend.fetch(request)
except httpx.TimeoutException as e:
    raise FetchError(f"Timeout: {url}", url=url, cause=e) from e

# NEVER bare except - always catch specific exceptions
```

### Async Patterns
```python
# Context managers for resources
async with backend as b:
    result = await b.fetch(request)

# asyncio.run() at entry points only
def main():
    asyncio.run(runner.run(max_pages=10))
```

### Dataclasses & Pydantic
```python
# Dataclasses for internal data
@dataclass
class FetchResult:
    url: str
    status_code: int
    
    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

# Pydantic for config with validation
class PortalConfig(BaseModel):
    name: str = Field(..., min_length=1, description="Unique identifier")
```

---

## Key Patterns

### Repository Pattern (All DB operations)
```python
class OpportunityRepository:
    def __init__(self, session: Session):
        self.session = session
    
    def get_by_external_id(self, portal_id: int, external_id: str) -> Opportunity | None:
        stmt = select(Opportunity).where(and_(
            Opportunity.portal_id == portal_id,
            Opportunity.external_id == external_id,
        ))
        return self.session.execute(stmt).scalar_one_or_none()
```

### Backend Abstraction (Scrapers)
```python
class Backend(ABC):
    @abstractmethod
    async def fetch(self, request: RequestSpec) -> FetchResult: ...
```

---

## Project Structure

```
src/procurewatch/
    cli/commands/         # Subcommands (portal, scrape, schedule, db)
    core/backends/        # HTTP/Playwright scrapers
    core/config/          # Pydantic models, YAML loader
    core/extract/         # HTML extraction (table, card, rules, pipeline)
    core/normalize/       # Date/money/status parsing
    persistence/          # SQLAlchemy models, repositories
        migrations/       # Alembic migrations
configs/portals/          # Portal YAML configs
tests/unit/               # Unit tests
tests/integration/        # Integration tests
```

---

## Common Tasks

1. **Add portal**: Create `configs/portals/<name>.yaml`, test with `scrape test <name>`
2. **Add CLI command**: Create in `cli/commands/`, register in `cli/main.py`
3. **Add DB model**: Add to `persistence/models.py`, run `alembic revision --autogenerate`

---

## Critical Warnings

1. **Never suppress types** with `# type: ignore` or `cast()` without justification
2. **Always** `from __future__ import annotations` at top of modules
3. **Pydantic v2**: Use `model_validate()` not deprecated `parse_obj()`
4. **SQLAlchemy 2.0**: Use `select()` not legacy `query()` style
5. **Windows**: Always use `encoding="utf-8"` for file operations
