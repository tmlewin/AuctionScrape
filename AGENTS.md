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

### M2 — Playwright Backend + SearchFormPortal ⚠️ IN PROGRESS

> PRD lines 930-965

#### M2.1 PlaywrightBackend

| Component | File | Status | Notes |
|-----------|------|--------|-------|
| JavaScript rendering | `playwright_backend.py` | ✅ Works | Tested with Alberta (367KB rendered) |
| Cookie persistence | `playwright_backend.py` | ⚠️ Code exists | Needs end-to-end test |
| Screenshot on error | `playwright_backend.py` | ✅ Works | Error screenshots saved to `snapshots/` |
| Human-in-the-loop | `playwright_backend.py` | ⚠️ Code exists | `pause_for_human()` needs testing |
| Stealth mode | `playwright_backend.py` | ⚠️ Code exists | Needs testing |

#### M2.2 SearchFormPortal

| Component | File | Status | Notes |
|-----------|------|--------|-------|
| Navigation steps | `search_form.py` | ⚠️ Code exists | Needs testing |
| Form filling | `search_form.py` | ❌ Fails | Alberta selectors don't match |
| Dynamic variables | `search_form.py` | ⚠️ Code exists | `resolve_dynamic_value()` needs testing |
| Form submission | `search_form.py` | ❌ Fails | Alberta selectors don't match |

#### M2.3 Browser Pagination

| Component | File | Status | Notes |
|-----------|------|--------|-------|
| Click-based "Next" | `search_form.py` | ⚠️ Code exists | `PaginationType.CLICK_NEXT` |
| "Load More" pattern | `search_form.py` | ⚠️ Code exists | `PaginationType.LOAD_MORE` |
| Infinite scroll | `search_form.py` | ⚠️ Code exists | `PaginationType.INFINITE_SCROLL` |

#### M2.4 ScrapeRunner Integration

| Component | File | Status | Notes |
|-----------|------|--------|-------|
| Route search_form portal | `runner.py` | ⚠️ Needs verification | |
| Route playwright backend | `runner.py` | ⚠️ Needs verification | |
| Fallback chain | `runner.py` | ⚠️ Needs verification | http → playwright → crawl4ai |

#### M2.5 Extraction (FR3 from PRD)

| Component | File | Status | Notes |
|-----------|------|--------|-------|
| Structured (JSON-LD) | `extract/structured.py` | ✅ Works | |
| Heuristic table | `extract/heuristic_table.py` | ✅ Works | Only for `<table>` elements |
| Heuristic card/list | `extract/heuristic_card.py` | ❌ MISSING | PRD line 645 mentions this |
| CSS/XPath rules | `extract/rules.py` | ❌ MISSING | PRD line 659 mentions this |

#### M2 Acceptance Tests (PRD lines 959-965)

| Test ID | Description | Status |
|---------|-------------|--------|
| AT-M2.1 | JS-rendered page scrapes with Playwright | ⚠️ Partial - fetch works, extraction fails |
| AT-M2.2 | Search form fills, submits, extracts | ❌ Fails - Alberta selectors wrong |
| AT-M2.3 | Click pagination traverses pages | ❌ Not tested |
| AT-M2.4 | Cookie persistence across runs | ❌ Not tested |
| AT-M2.5 | Screenshot on extraction failure | ✅ Works |

#### M2 Blocking Issue

**Problem**: Alberta Purchasing uses Angular Material card components (`<apc-opportunity-search-result>`), not `<table>` elements. The `HeuristicTableExtractor` only finds `<table>` tags.

**Evidence**:
```
PlaywrightBackend.fetch() → 367,588 bytes, status 200 ✅
HTML contains mat-table: True
HTML contains <table>: False
HeuristicTableExtractor → 0 records, confidence 0.0 ❌
```

**Options to resolve**:
1. **Option A**: Test with a portal that uses actual `<table>` elements (low effort)
2. **Option B**: Create `HeuristicCardExtractor` for card-based layouts (medium effort)
3. **Option C**: Create `RuleExtractor` for config-driven CSS selectors (medium effort)

### M3 — Scheduler ❌ NOT STARTED

| Component | File | Status |
|-----------|------|--------|
| APScheduler service | `core/scheduler/service.py` | ❌ Missing |
| Schedule CLI | `cli/commands/schedule.py` | ⚠️ Stub exists |
| Job storage | | ❌ Missing |
| Run locks | `core/orchestrator/locks.py` | ❌ Missing |

### M4 — Crawl4AI Backend ❌ NOT STARTED

| Component | File | Status |
|-----------|------|--------|
| Crawl4AI adapter | `core/backends/crawl4ai_backend.py` | ❌ Missing |
| Per-portal backend selection | | ❌ Missing |
| Markdown capture | | ❌ Missing |

### M5 — Export & Polish ❌ NOT STARTED

| Component | File | Status |
|-----------|------|--------|
| Export formats (CSV, JSON) | | ❌ Missing |
| Dashboards | | ❌ Missing |
| Alerts | | ❌ Optional |

---

## Current Session Context

**Last worked on**: M2 - Playwright Backend + SearchFormPortal

**What was done**:
- Created `PlaywrightBackend` with full browser automation
- Created `SearchFormPortal` for form-based portals
- Added config models for navigation, forms, pagination
- Tested with Alberta Purchasing portal

**What's blocking**:
- Extraction fails because Alberta uses Angular cards, not tables
- Need to either fix extraction or test with a table-based portal

**Next action needed**:
- Decision: Which option (A, B, or C) to complete M2?

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
    core/extract/         # HTML extraction (heuristic table)
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
