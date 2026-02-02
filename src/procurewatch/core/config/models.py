"""
Pydantic configuration models for ProcureWatch.

These models provide type-safe configuration with validation for:
- Application settings
- Portal configurations
- Scheduler settings
- Backend preferences
"""

from __future__ import annotations

from datetime import time
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, HttpUrl, field_validator


# =============================================================================
# Enums
# =============================================================================


class BackendType(str, Enum):
    """Supported scraping backend types."""

    HTTP = "http"
    PLAYWRIGHT = "playwright"
    CRAWL4AI = "crawl4ai"


class PortalType(str, Enum):
    """Portal archetype classifications."""

    GENERIC_TABLE = "generic_table"
    GENERIC_CARDS = "generic_cards"
    SEARCH_FORM = "search_form"
    API_BASED = "api_based"
    CUSTOM = "custom"


class ExtractionMode(str, Enum):
    """Extraction strategy modes."""

    HEURISTIC_TABLE = "heuristic_table"
    STRUCTURED = "structured"
    CSS_RULES = "css_rules"
    XPATH_RULES = "xpath_rules"
    LLM = "llm"


class PaginationType(str, Enum):
    """Pagination strategy types."""

    NEXT_LINK = "next_link"
    PAGE_NUMBER = "page_number"
    OFFSET_LIMIT = "offset_limit"
    LOAD_MORE = "load_more"
    INFINITE_SCROLL = "infinite_scroll"
    CLICK_NEXT = "click_next"  # NEW: Browser-based click pagination
    NONE = "none"


class AuthStrategy(str, Enum):
    """Authentication strategies for portals."""

    NONE = "none"
    COOKIE_IMPORT = "cookie_import"
    INTERACTIVE_LOGIN = "interactive_login"
    API_KEY = "api_key"


class ScheduleType(str, Enum):
    """Schedule frequency types."""

    DAILY = "daily"
    WEEKDAY = "weekday"
    HOURLY = "hourly"
    CRON = "cron"


class EventType(str, Enum):
    """Opportunity event types for tracking changes."""

    NEW = "NEW"
    UPDATED = "UPDATED"
    CLOSED = "CLOSED"
    AWARDED = "AWARDED"
    EXPIRED = "EXPIRED"
    LAYOUT_DRIFT = "LAYOUT_DRIFT"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"


class OpportunityStatus(str, Enum):
    """Opportunity lifecycle status."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"
    AWARDED = "AWARDED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


# =============================================================================
# Backend Configuration
# =============================================================================


class BackendConfig(BaseModel):
    """Backend selection and fallback configuration."""

    preferred: BackendType = Field(
        default=BackendType.HTTP,
        description="Primary backend to use for this portal",
    )
    fallbacks: list[BackendType] = Field(
        default_factory=lambda: [BackendType.PLAYWRIGHT],
        description="Fallback backends if preferred fails",
    )
    timeout_seconds: float = Field(
        default=30.0,
        ge=1.0,
        le=300.0,
        description="Request timeout in seconds",
    )
    headless: bool = Field(
        default=True,
        description="Run browser backends in headless mode",
    )


# =============================================================================
# Politeness Configuration
# =============================================================================


class PolitenessConfig(BaseModel):
    """Rate limiting and politeness settings."""

    concurrency: int = Field(
        default=2,
        ge=1,
        le=20,
        description="Max concurrent requests to this portal",
    )
    min_delay_ms: int = Field(
        default=500,
        ge=0,
        description="Minimum delay between requests in milliseconds",
    )
    max_delay_ms: int = Field(
        default=2000,
        ge=0,
        description="Maximum delay between requests in milliseconds",
    )
    respect_robots_txt: bool = Field(
        default=True,
        description="Honor robots.txt directives",
    )
    max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Maximum retry attempts on failure",
    )
    retry_backoff_factor: float = Field(
        default=2.0,
        ge=1.0,
        le=10.0,
        description="Exponential backoff multiplier for retries",
    )

    @field_validator("max_delay_ms")
    @classmethod
    def max_delay_gte_min(cls, v: int, info: Any) -> int:
        """Ensure max delay is at least min delay."""
        min_delay = info.data.get("min_delay_ms", 0)
        if v < min_delay:
            raise ValueError("max_delay_ms must be >= min_delay_ms")
        return v


# =============================================================================
# Pagination Configuration
# =============================================================================


class PaginationConfig(BaseModel):
    """Pagination discovery settings."""

    type: PaginationType = Field(
        default=PaginationType.NEXT_LINK,
        description="Pagination strategy to use",
    )
    selector_hint: str | None = Field(
        default=None,
        description="CSS selector hint for pagination element",
    )
    max_pages: int = Field(
        default=50,
        ge=1,
        le=1000,
        description="Maximum pages to scrape per run",
    )
    cutoff_days: int | None = Field(
        default=None,
        ge=1,
        description="Stop pagination when items are older than N days",
    )
    # Browser-based pagination options (NEW in v1.3)
    next_button_selector: str | None = Field(
        default=None,
        description="Selector for next page button (click_next, load_more types)",
    )
    disabled_class: str | None = Field(
        default="disabled",
        description="Class indicating pagination button is disabled",
    )
    wait_after_click_ms: int = Field(
        default=2000,
        ge=500,
        le=30000,
        description="Time to wait after clicking pagination button",
    )
    wait_for_selector: str | None = Field(
        default=None,
        description="Selector to wait for after pagination",
    )
    scroll_container: str | None = Field(
        default=None,
        description="Container selector for infinite scroll",
    )
    item_selector: str | None = Field(
        default=None,
        description="Item selector for counting items (infinite scroll)",
    )
    scroll_pause_ms: int = Field(
        default=1500,
        ge=500,
        le=10000,
        description="Pause between scroll actions",
    )
    max_scrolls: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum scroll actions for infinite scroll",
    )


class DiscoveryConfig(BaseModel):
    """Discovery and pagination settings."""

    pagination: PaginationConfig = Field(default_factory=PaginationConfig)
    detail_link_selector: str | None = Field(
        default=None,
        description="CSS selector for detail page links",
    )
    follow_detail_pages: bool = Field(
        default=True,
        description="Whether to scrape individual detail pages",
    )


# =============================================================================
# Extraction Configuration
# =============================================================================


class FieldExtractionRule(BaseModel):
    """Extraction rule for a single field."""

    selectors: list[str] = Field(
        default_factory=list,
        description="CSS or XPath selectors to try in order",
    )
    attribute: str | None = Field(
        default=None,
        description="Attribute to extract (default: text content)",
    )
    regex: str | None = Field(
        default=None,
        description="Regex pattern to apply to extracted value",
    )
    clean: bool = Field(
        default=True,
        description="Apply text cleaning (trim, normalize whitespace)",
    )
    required: bool = Field(
        default=False,
        description="Whether this field is required for valid extraction",
    )


class ListingExtractionConfig(BaseModel):
    """Extraction settings for listing pages."""

    mode: ExtractionMode = Field(
        default=ExtractionMode.HEURISTIC_TABLE,
        description="Extraction strategy for listing pages",
    )
    table_selector: str | None = Field(
        default=None,
        description="CSS selector for the data table/list",
    )
    row_selector: str | None = Field(
        default=None,
        description="CSS selector for individual rows",
    )
    container_selector: str | None = Field(
        default=None,
        description="CSS/XPath selector for listing item containers",
    )
    header_aliases: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Map of canonical field names to possible header texts",
    )
    fields: dict[str, FieldExtractionRule] = Field(
        default_factory=dict,
        description="Field-specific extraction rules for listings",
    )


class DetailExtractionConfig(BaseModel):
    """Extraction settings for detail pages."""

    mode: ExtractionMode = Field(
        default=ExtractionMode.CSS_RULES,
        description="Extraction strategy for detail pages",
    )
    fields: dict[str, FieldExtractionRule] = Field(
        default_factory=dict,
        description="Field-specific extraction rules",
    )
    description_selector: str | None = Field(
        default=None,
        description="Selector for main description content",
    )
    use_markdown: bool = Field(
        default=True,
        description="Convert description to markdown (Crawl4AI)",
    )


class ExtractionConfig(BaseModel):
    """Complete extraction configuration."""

    listing: ListingExtractionConfig = Field(default_factory=ListingExtractionConfig)
    detail: DetailExtractionConfig = Field(default_factory=DetailExtractionConfig)
    confidence_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum confidence for valid extraction",
    )
    snapshot_on_low_confidence: bool = Field(
        default=True,
        description="Save page snapshot when confidence is low",
    )


# =============================================================================
# Authentication Configuration
# =============================================================================


class AuthConfig(BaseModel):
    """Authentication settings for portals requiring login."""

    strategy: AuthStrategy = Field(
        default=AuthStrategy.NONE,
        description="Authentication strategy",
    )
    cookie_file: Path | None = Field(
        default=None,
        description="Path to cookie file for cookie_import strategy",
    )
    login_url: str | None = Field(
        default=None,
        description="Login page URL for interactive login",
    )
    credentials_env_prefix: str | None = Field(
        default=None,
        description="Environment variable prefix for credentials",
    )


# =============================================================================
# Browser Navigation Configuration (NEW in v1.3)
# =============================================================================


class NavigationActionType(str, Enum):
    """Types of browser navigation actions."""

    CLICK = "click"
    WAIT = "wait"
    WAIT_FOR = "wait_for"
    SCROLL = "scroll"
    HOVER = "hover"
    FILL = "fill"
    GOTO = "goto"
    PAUSE_FOR_HUMAN = "pause_for_human"


class NavigationAction(BaseModel):
    """Single navigation step for browser automation."""

    action: NavigationActionType = Field(
        ...,
        description="Type of action to perform",
    )
    selector: str | None = Field(
        default=None,
        description="CSS selector for the target element",
    )
    value: str | None = Field(
        default=None,
        description="Value to fill or URL to navigate to",
    )
    wait_for: str | None = Field(
        default=None,
        description="Selector to wait for after action",
    )
    duration_ms: int | None = Field(
        default=None,
        ge=0,
        description="Duration in milliseconds (for wait action)",
    )
    timeout_ms: int = Field(
        default=30000,
        ge=1000,
        le=120000,
        description="Timeout for this action",
    )
    optional: bool = Field(
        default=False,
        description="Don't fail if element not found",
    )
    condition: str | None = Field(
        default=None,
        description="Only execute if this selector exists",
    )
    message: str | None = Field(
        default=None,
        description="Message for human-in-the-loop pause",
    )


class NavigationConfig(BaseModel):
    """Configuration for multi-step navigation to reach search form."""

    steps: list[NavigationAction] = Field(
        default_factory=list,
        description="Ordered list of navigation steps",
    )


# =============================================================================
# Search Form Configuration (NEW in v1.3)
# =============================================================================


class FormFieldType(str, Enum):
    """Types of form fields."""

    TEXT = "text"
    SELECT = "select"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    DATE = "date"
    AUTOCOMPLETE = "autocomplete"


class FormField(BaseModel):
    """Configuration for a single form field."""

    name: str = Field(
        ...,
        description="Human-readable field name for logging",
    )
    selector: str = Field(
        ...,
        description="CSS selector for the field",
    )
    type: FormFieldType = Field(
        default=FormFieldType.TEXT,
        description="Field input type",
    )
    value: str = Field(
        default="",
        description="Value to enter (supports dynamic variables like ${TODAY})",
    )
    optional: bool = Field(
        default=False,
        description="Don't fail if field not found",
    )
    clear_first: bool = Field(
        default=True,
        description="Clear existing value before filling",
    )


class FormSubmitConfig(BaseModel):
    """Configuration for form submission."""

    method: str = Field(
        default="click",
        description="Submit method: 'click' or 'enter'",
    )
    selector: str | None = Field(
        default=None,
        description="Submit button selector (for click method)",
    )
    wait_for: str | None = Field(
        default=None,
        description="Selector to wait for after submission",
    )
    wait_timeout_ms: int = Field(
        default=30000,
        ge=1000,
        le=120000,
        description="Timeout for waiting after submission",
    )


class SearchFormConfig(BaseModel):
    """Configuration for search form interaction."""

    form_selector: str | None = Field(
        default=None,
        description="CSS selector for the form container",
    )
    fields: list[FormField] = Field(
        default_factory=list,
        description="Form fields to fill",
    )
    submit: FormSubmitConfig = Field(
        default_factory=FormSubmitConfig,
        description="Form submission configuration",
    )


# =============================================================================
# Playwright Backend Configuration (NEW in v1.3)
# =============================================================================


class PlaywrightConfig(BaseModel):
    """Playwright-specific backend configuration."""

    browser: str = Field(
        default="chromium",
        description="Browser to use: chromium, firefox, webkit",
    )
    viewport_width: int = Field(
        default=1920,
        ge=320,
        le=3840,
        description="Browser viewport width",
    )
    viewport_height: int = Field(
        default=1080,
        ge=240,
        le=2160,
        description="Browser viewport height",
    )
    user_agent: str | None = Field(
        default=None,
        description="Custom user agent string",
    )
    stealth: bool = Field(
        default=True,
        description="Enable stealth mode to avoid bot detection",
    )
    cookies_persist: bool = Field(
        default=True,
        description="Persist cookies across runs",
    )
    cookies_path: str | None = Field(
        default=None,
        description="Path to cookies file (default: data/cookies/{portal_name}.json)",
    )
    screenshots_on_error: bool = Field(
        default=True,
        description="Capture screenshot on errors",
    )
    screenshots_path: str | None = Field(
        default=None,
        description="Path for error screenshots",
    )
    navigation_timeout_ms: int = Field(
        default=30000,
        ge=5000,
        le=120000,
        description="Timeout for page navigation",
    )
    action_timeout_ms: int = Field(
        default=10000,
        ge=1000,
        le=60000,
        description="Timeout for individual actions",
    )


# =============================================================================
# Portal Configuration
# =============================================================================


class PortalConfig(BaseModel):
    """Complete configuration for a tender portal.
    
    This is the primary configuration object that defines how to
    scrape, extract, and process data from a single tender portal.
    """

    # Identity
    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Unique portal identifier",
    )
    display_name: str | None = Field(
        default=None,
        description="Human-readable portal name",
    )
    base_url: HttpUrl = Field(
        ...,
        description="Portal base URL",
    )
    portal_type: PortalType = Field(
        default=PortalType.GENERIC_TABLE,
        description="Portal archetype classification",
    )

    # Entry points
    seed_urls: list[str] = Field(
        ...,
        min_length=1,
        description="Starting URLs for scraping",
    )

    # Configuration sections
    backend: BackendConfig = Field(default_factory=BackendConfig)
    politeness: PolitenessConfig = Field(default_factory=PolitenessConfig)
    discovery: DiscoveryConfig = Field(default_factory=DiscoveryConfig)
    extraction: ExtractionConfig = Field(default_factory=ExtractionConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    
    # Browser automation (NEW in v1.3)
    navigation: NavigationConfig = Field(
        default_factory=NavigationConfig,
        description="Navigation steps to reach search form",
    )
    search_form: SearchFormConfig | None = Field(
        default=None,
        description="Search form configuration (for search_form portal type)",
    )
    playwright: PlaywrightConfig = Field(
        default_factory=PlaywrightConfig,
        description="Playwright-specific configuration",
    )

    # Metadata
    enabled: bool = Field(
        default=True,
        description="Whether this portal is active",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Tags for organizing/filtering portals",
    )
    notes: str | None = Field(
        default=None,
        description="Operator notes about this portal",
    )

    @property
    def effective_display_name(self) -> str:
        """Get display name, falling back to name."""
        return self.display_name or self.name


# =============================================================================
# Scheduler Configuration
# =============================================================================


class ScheduleConfig(BaseModel):
    """Individual schedule definition."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Unique schedule identifier",
    )
    enabled: bool = Field(
        default=True,
        description="Whether this schedule is active",
    )
    portals: list[str] = Field(
        default_factory=list,
        description="Portal names to include (empty = all)",
    )
    schedule_type: ScheduleType = Field(
        default=ScheduleType.DAILY,
        description="Schedule frequency",
    )
    time_of_day: time = Field(
        default=time(6, 0),
        description="Time to run (for daily/weekday)",
    )
    cron_expression: str | None = Field(
        default=None,
        description="Cron expression (for cron type)",
    )
    timezone: str = Field(
        default="UTC",
        description="Timezone for schedule",
    )
    jitter_minutes: int = Field(
        default=0,
        ge=0,
        le=60,
        description="Random jitter window in minutes",
    )
    blackout_start: time | None = Field(
        default=None,
        description="Start of blackout window (no runs)",
    )
    blackout_end: time | None = Field(
        default=None,
        description="End of blackout window",
    )
    max_runtime_minutes: int = Field(
        default=120,
        ge=1,
        le=1440,
        description="Maximum run duration before timeout",
    )


class SchedulerConfig(BaseModel):
    """Global scheduler settings."""

    enabled: bool = Field(
        default=True,
        description="Master scheduler enable/disable",
    )
    schedules: list[ScheduleConfig] = Field(
        default_factory=list,
        description="Defined schedules",
    )
    max_concurrent_runs: int = Field(
        default=1,
        ge=1,
        le=10,
        description="Maximum concurrent scrape runs",
    )
    default_jitter_minutes: int = Field(
        default=5,
        ge=0,
        description="Default jitter if not specified per-schedule",
    )


# =============================================================================
# Database Configuration
# =============================================================================


class DatabaseConfig(BaseModel):
    """Database connection settings."""

    url: str = Field(
        default="sqlite:///data/procurewatch.db",
        description="SQLAlchemy database URL",
    )
    echo: bool = Field(
        default=False,
        description="Echo SQL statements (debugging)",
    )
    pool_size: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Connection pool size",
    )


# =============================================================================
# Logging Configuration
# =============================================================================


class LoggingConfig(BaseModel):
    """Logging settings."""

    level: str = Field(
        default="INFO",
        description="Log level (DEBUG, INFO, WARNING, ERROR)",
    )
    file: Path | None = Field(
        default=Path("logs/procurewatch.log"),
        description="Log file path",
    )
    json_format: bool = Field(
        default=True,
        description="Use JSON format for file logs",
    )
    rich_console: bool = Field(
        default=True,
        description="Use Rich for console output",
    )


# =============================================================================
# Application Configuration
# =============================================================================


class AppConfig(BaseModel):
    """Root application configuration.
    
    This is the main configuration object loaded from app.yaml.
    """

    # Paths
    config_dir: Path = Field(
        default=Path("configs"),
        description="Configuration directory",
    )
    data_dir: Path = Field(
        default=Path("data"),
        description="Data storage directory",
    )
    snapshot_dir: Path = Field(
        default=Path("snapshots"),
        description="HTML snapshot directory",
    )

    # Components
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)

    # Defaults for portals
    default_backend: BackendConfig = Field(default_factory=BackendConfig)
    default_politeness: PolitenessConfig = Field(default_factory=PolitenessConfig)

    # Feature flags
    enable_crawl4ai: bool = Field(
        default=False,
        description="Enable Crawl4AI backend (requires optional dependency)",
    )
    enable_tui: bool = Field(
        default=False,
        description="Enable Textual TUI (requires optional dependency)",
    )

    def ensure_directories(self) -> None:
        """Create required directories if they don't exist."""
        for dir_path in [self.config_dir, self.data_dir, self.snapshot_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)
        
        # Create logs directory from logging config
        if self.logging.file:
            self.logging.file.parent.mkdir(parents=True, exist_ok=True)
