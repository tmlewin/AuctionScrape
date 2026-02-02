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
| Crawl4AI adapter | `core/backends/crawl4ai_backend.py` | ✅ Works | 500+ lines, full LLM integration |
| LLM extraction strategy | `crawl4ai_backend.py` | ✅ Works | Pydantic schema, auto field mapping |
| Quick Mode CLI | `cli/commands/quick.py` | ✅ Works | `quick scrape`, `quick test`, `quick promote` |
| Draft YAML generation | `crawl4ai_backend.py` | ✅ Works | Auto-generate configs from scrapes |
| Markdown capture | `crawl4ai_backend.py` | ✅ Works | Built into Crawl4AI |

#### M4 Features Implemented

- **AI-Powered Extraction**: Uses LLM to understand page structure automatically
- **No CSS Selectors Needed**: Works on ANY website without manual configuration
- **OpportunitySchema**: Pydantic schema for structured extraction
- **LLM Provider Support**: OpenAI, Ollama (local), Anthropic, Groq, etc.
- **Schema Caching**: Generate CSS schema once, reuse for free forever
- **Quick Mode CLI**:
  - `quick scrape <url>` - Scrape any URL with AI
  - `quick test <url>` - Test extraction without saving
  - `quick promote <name>` - Convert quick scrape to full config
  - `--provider ollama/llama3.3` - Use local models (free)
  - `--save` - Save to database
  - `--generate-config` - Create reusable YAML config

#### M4.5 Quick Mode ✅ COMPLETE

| Component | File | Status |
|-----------|------|--------|
| Quick CLI flow | `cli/commands/quick.py` | ✅ Works |
| LLM schema inference | `crawl4ai_backend.py` | ✅ Works |
| Pagination heuristics | Built into Crawl4AI | ✅ Works |
| Draft YAML generation | `crawl4ai_backend.py` | ✅ Works |

### M5 — Export & Polish ❌ NOT STARTED

| Component | File | Status |
|-----------|------|--------|
| Export formats (CSV, JSON) | | ❌ Missing |
| Dashboards | | ❌ Missing |
| Alerts | | ❌ Optional |

---

## Current Session Context

**Last worked on**: M4 - Crawl4AI Backend + Quick Mode

**Status**: ✅ M4 COMPLETE

**What was done**:
- Installed crawl4ai v0.8.0 with all dependencies
- Created `Crawl4AIBackend` with LLM-powered extraction
- Created `OpportunitySchema` Pydantic model for structured extraction
- Implemented Quick Mode CLI (`quick scrape`, `quick test`, `quick promote`)
- Added automatic YAML config generation from successful scrapes
- Registered quick command in main CLI

**Key Capability Unlocked**:
- **Point at ANY URL → Get structured procurement data**
- No CSS selectors needed - AI understands page structure
- Works on any website without manual configuration
- Supports multiple LLM providers (OpenAI, Ollama, Anthropic, etc.)

**Next action**: Test with real procurement sites, then M5 (Export & Polish)
- Tested with Alberta Purchasing portal: 10 records, 0.967 confidence

**Next action**: M3 (Scheduler) or additional portal testing

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
