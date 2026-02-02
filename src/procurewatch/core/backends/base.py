"""
Backend base classes and data structures.

Defines the interface contract for all scraping backends.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class RequestSpec:
    """Specification for an HTTP request."""
    
    url: str
    method: str = "GET"
    headers: dict[str, str] = field(default_factory=dict)
    cookies: dict[str, str] = field(default_factory=dict)
    params: dict[str, str] = field(default_factory=dict)
    data: dict[str, Any] | None = None
    json_data: dict[str, Any] | None = None
    timeout: float = 30.0
    follow_redirects: bool = True
    
    # Metadata for logging/debugging
    portal_name: str | None = None
    page_type: str | None = None  # "listing", "detail", "search"


@dataclass
class FetchResult:
    """Result of a fetch operation."""
    
    url: str
    final_url: str  # After redirects
    status_code: int
    html: str
    headers: dict[str, str]
    cookies: dict[str, str]
    
    # Timing
    elapsed_ms: float
    fetched_at: datetime = field(default_factory=datetime.utcnow)
    
    # Metadata
    from_cache: bool = False
    retry_count: int = 0
    
    # Error info (if partial failure)
    error: str | None = None
    
    @property
    def ok(self) -> bool:
        """Check if request was successful (2xx status)."""
        return 200 <= self.status_code < 300
    
    @property
    def content_length(self) -> int:
        """Get content length in bytes."""
        return len(self.html.encode("utf-8"))


@dataclass
class RenderResult(FetchResult):
    """Result of a render operation (JavaScript execution).
    
    Extends FetchResult with browser-specific data.
    """
    
    # Clean markdown (from Crawl4AI or similar)
    markdown: str | None = None
    
    # Screenshot for debugging
    screenshot: bytes | None = None
    screenshot_path: str | None = None
    
    # Browser console logs
    console_logs: list[str] = field(default_factory=list)
    
    # Network requests made during render
    network_requests: list[dict[str, Any]] = field(default_factory=list)


class Backend(ABC):
    """Abstract base class for scraping backends.
    
    All backends must implement the fetch method. Browser-based
    backends should also implement render.
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Backend identifier."""
        pass
    
    @property
    def supports_javascript(self) -> bool:
        """Whether this backend can execute JavaScript."""
        return False
    
    @abstractmethod
    async def fetch(self, request: RequestSpec) -> FetchResult:
        """Fetch a URL and return the response.
        
        Args:
            request: Request specification
            
        Returns:
            FetchResult with response data
            
        Raises:
            BackendError: On unrecoverable fetch failure
        """
        pass
    
    async def render(self, request: RequestSpec) -> RenderResult:
        """Render a page with JavaScript execution.
        
        Only available for browser-based backends.
        
        Args:
            request: Request specification
            
        Returns:
            RenderResult with rendered content
            
        Raises:
            NotImplementedError: If backend doesn't support rendering
            BackendError: On unrecoverable render failure
        """
        raise NotImplementedError(f"{self.name} backend does not support JavaScript rendering")
    
    async def close(self) -> None:
        """Clean up backend resources.
        
        Called when the backend is no longer needed.
        """
        pass
    
    async def __aenter__(self) -> "Backend":
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.close()


class BackendError(Exception):
    """Base exception for backend errors."""
    
    def __init__(
        self,
        message: str,
        url: str | None = None,
        status_code: int | None = None,
        cause: Exception | None = None,
    ):
        super().__init__(message)
        self.url = url
        self.status_code = status_code
        self.cause = cause


class FetchError(BackendError):
    """Error during fetch operation."""
    pass


class RenderError(BackendError):
    """Error during render operation."""
    pass


class RateLimitError(BackendError):
    """Rate limit hit (429 or similar)."""
    
    def __init__(
        self,
        message: str,
        url: str | None = None,
        retry_after: float | None = None,
    ):
        super().__init__(message, url, status_code=429)
        self.retry_after = retry_after


class BlockedError(BackendError):
    """Request blocked by anti-bot measures."""
    pass
