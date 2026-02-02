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
]
