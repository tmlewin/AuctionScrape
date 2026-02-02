"""Backend implementations for fetching and rendering pages."""

from .base import (
    Backend,
    BackendError,
    BlockedError,
    FetchError,
    FetchResult,
    RateLimitError,
    RenderError,
    RenderResult,
    RequestSpec,
)
from .http_backend import HttpBackend
from .playwright_backend import (
    PlaywrightBackend,
    BrowserAction,
    ActionResult,
    FormField,
    FormResult,
    BrowserError,
    NavigationTimeout,
    ElementNotFound,
    ActionFailed,
    PageBlocked,
)

# Crawl4AI backend (optional - requires crawl4ai package)
try:
    from .crawl4ai_backend import (
        Crawl4AIBackend,
        Crawl4AIResult,
        LLMConfig,
        OpportunitySchema,
        quick_scrape,
        generate_portal_config,
    )
    _CRAWL4AI_AVAILABLE = True
except ImportError:
    _CRAWL4AI_AVAILABLE = False

__all__ = [
    # Base classes
    "Backend",
    "RequestSpec",
    "FetchResult",
    "RenderResult",
    # Base errors
    "BackendError",
    "FetchError",
    "RenderError",
    "RateLimitError",
    "BlockedError",
    # HTTP backend
    "HttpBackend",
    # Playwright backend
    "PlaywrightBackend",
    "BrowserAction",
    "ActionResult",
    "FormField",
    "FormResult",
    "BrowserError",
    "NavigationTimeout",
    "ElementNotFound",
    "ActionFailed",
    "PageBlocked",
    # Crawl4AI backend (conditional)
    "Crawl4AIBackend",
    "Crawl4AIResult",
    "LLMConfig",
    "OpportunitySchema",
    "quick_scrape",
    "generate_portal_config",
]
