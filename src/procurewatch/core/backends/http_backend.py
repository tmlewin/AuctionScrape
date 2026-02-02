"""
HTTP Backend implementation using httpx.

Provides async HTTP fetching with:
- Configurable headers and cookies
- Automatic retry with exponential backoff
- Rate limit detection
- Response caching support
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .base import (
    Backend,
    BackendError,
    BlockedError,
    FetchError,
    FetchResult,
    RateLimitError,
    RequestSpec,
)

if TYPE_CHECKING:
    pass


# Common user agents for rotation
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]

# Status codes that indicate blocking
BLOCKED_STATUS_CODES = {403, 406, 418, 451}

# Status codes that should trigger retry
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


class HttpBackend(Backend):
    """HTTP backend using httpx for async requests.
    
    Features:
    - Persistent connection pooling
    - Automatic redirect following
    - Cookie persistence across requests
    - Retry with exponential backoff
    - Rate limit detection
    """
    
    def __init__(
        self,
        timeout: float = 30.0,
        max_retries: int = 3,
        retry_backoff: float = 2.0,
        user_agent: str | None = None,
        default_headers: dict[str, str] | None = None,
    ):
        """Initialize HTTP backend.
        
        Args:
            timeout: Default request timeout in seconds
            max_retries: Maximum retry attempts
            retry_backoff: Exponential backoff multiplier
            user_agent: Custom user agent (default: rotates common agents)
            default_headers: Default headers for all requests
        """
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self.user_agent = user_agent or USER_AGENTS[0]
        
        self.default_headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            **(default_headers or {}),
        }
        
        self._client: httpx.AsyncClient | None = None
        self._cookie_jar: dict[str, dict[str, str]] = {}  # domain -> cookies
    
    @property
    def name(self) -> str:
        return "http"
    
    @property
    def supports_javascript(self) -> bool:
        return False
    
    async def _ensure_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                follow_redirects=True,
                headers=self.default_headers,
                limits=httpx.Limits(
                    max_connections=20,
                    max_keepalive_connections=10,
                ),
            )
        return self._client
    
    def _get_domain(self, url: str) -> str:
        """Extract domain from URL for cookie scoping."""
        parsed = urlparse(url)
        return parsed.netloc
    
    def _merge_cookies(self, url: str, request_cookies: dict[str, str]) -> dict[str, str]:
        """Merge stored cookies with request-specific cookies."""
        domain = self._get_domain(url)
        stored = self._cookie_jar.get(domain, {})
        return {**stored, **request_cookies}
    
    def _store_cookies(self, url: str, response: httpx.Response) -> dict[str, str]:
        """Extract and store cookies from response."""
        domain = self._get_domain(url)
        cookies = dict(response.cookies)
        
        if domain not in self._cookie_jar:
            self._cookie_jar[domain] = {}
        self._cookie_jar[domain].update(cookies)
        
        return cookies
    
    def _check_blocked(self, response: httpx.Response, html: str) -> None:
        """Check if response indicates blocking."""
        # Status code check
        if response.status_code in BLOCKED_STATUS_CODES:
            raise BlockedError(
                f"Request blocked with status {response.status_code}",
                url=str(response.url),
                status_code=response.status_code,
            )
        
        # Content-based detection
        blocked_indicators = [
            "access denied",
            "blocked",
            "captcha",
            "challenge-platform",
            "cf-browser-verification",
            "please verify you are human",
            "unusual traffic",
        ]
        
        html_lower = html.lower()
        for indicator in blocked_indicators:
            if indicator in html_lower and len(html) < 50000:
                # Small page with blocking indicator
                raise BlockedError(
                    f"Possible anti-bot block detected: '{indicator}' in response",
                    url=str(response.url),
                    status_code=response.status_code,
                )
    
    def _check_rate_limit(self, response: httpx.Response) -> None:
        """Check for rate limiting."""
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            retry_seconds = None
            
            if retry_after:
                try:
                    retry_seconds = float(retry_after)
                except ValueError:
                    pass
            
            raise RateLimitError(
                "Rate limit exceeded",
                url=str(response.url),
                retry_after=retry_seconds,
            )
    
    async def fetch(self, request: RequestSpec) -> FetchResult:
        """Fetch a URL with automatic retry.
        
        Args:
            request: Request specification
            
        Returns:
            FetchResult with response data
        """
        client = await self._ensure_client()
        cookies = self._merge_cookies(request.url, request.cookies)
        
        # Merge headers
        headers = {**self.default_headers, **request.headers}
        
        last_error: Exception | None = None
        retry_count = 0
        
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self.max_retries),
                wait=wait_exponential(multiplier=1, min=1, max=30),
                retry=retry_if_exception_type((httpx.TransportError, RateLimitError)),
                reraise=True,
            ):
                with attempt:
                    retry_count = attempt.retry_state.attempt_number - 1
                    
                    start_time = datetime.utcnow()
                    
                    try:
                        if request.method.upper() == "GET":
                            response = await client.get(
                                request.url,
                                headers=headers,
                                cookies=cookies,
                                params=request.params or None,
                                follow_redirects=request.follow_redirects,
                            )
                        elif request.method.upper() == "POST":
                            response = await client.post(
                                request.url,
                                headers=headers,
                                cookies=cookies,
                                params=request.params or None,
                                data=request.data,
                                json=request.json_data,
                                follow_redirects=request.follow_redirects,
                            )
                        else:
                            raise FetchError(f"Unsupported method: {request.method}")
                        
                        elapsed_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
                        
                        # Check for rate limiting
                        self._check_rate_limit(response)
                        
                        # Get response content
                        html = response.text
                        
                        # Check for blocking (non-fatal, just raises for logging)
                        try:
                            self._check_blocked(response, html)
                        except BlockedError:
                            # Re-raise but don't retry blocked responses
                            raise
                        
                        # Store cookies
                        response_cookies = self._store_cookies(request.url, response)
                        
                        return FetchResult(
                            url=request.url,
                            final_url=str(response.url),
                            status_code=response.status_code,
                            html=html,
                            headers=dict(response.headers),
                            cookies=response_cookies,
                            elapsed_ms=elapsed_ms,
                            retry_count=retry_count,
                        )
                        
                    except httpx.TimeoutException as e:
                        last_error = e
                        raise httpx.TransportError(f"Timeout: {e}") from e
                        
        except BlockedError:
            raise
        except RateLimitError:
            raise
        except httpx.TransportError as e:
            raise FetchError(
                f"Transport error after {retry_count + 1} attempts: {e}",
                url=request.url,
                cause=e,
            ) from e
        except Exception as e:
            raise FetchError(
                f"Fetch failed: {e}",
                url=request.url,
                cause=e,
            ) from e
    
    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
    
    def clear_cookies(self, domain: str | None = None) -> None:
        """Clear stored cookies.
        
        Args:
            domain: Specific domain to clear, or None for all
        """
        if domain:
            self._cookie_jar.pop(domain, None)
        else:
            self._cookie_jar.clear()
