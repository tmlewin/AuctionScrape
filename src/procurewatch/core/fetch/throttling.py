"""
Rate limiting and throttling utilities.

Provides per-domain rate limiting with configurable delays
and concurrency limits.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    pass


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""
    
    min_delay_ms: int = 500
    max_delay_ms: int = 2000
    max_concurrency: int = 2
    burst_limit: int = 5  # Max requests in burst window
    burst_window_seconds: float = 10.0


class RateLimiter:
    """Per-domain rate limiter with jittered delays.
    
    Features:
    - Configurable min/max delay between requests
    - Per-domain concurrency limiting
    - Burst protection
    - Async-safe with locks
    """
    
    def __init__(self, default_config: RateLimitConfig | None = None):
        """Initialize rate limiter.
        
        Args:
            default_config: Default config for domains without specific settings
        """
        self.default_config = default_config or RateLimitConfig()
        self._domain_configs: dict[str, RateLimitConfig] = {}
        
        # Per-domain state
        self._last_request: dict[str, float] = defaultdict(float)
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        
        # Burst tracking
        self._request_times: dict[str, list[float]] = defaultdict(list)
    
    def configure_domain(self, domain: str, config: RateLimitConfig) -> None:
        """Set rate limit configuration for a specific domain.
        
        Args:
            domain: Domain name (e.g., 'example.com')
            config: Rate limit configuration
        """
        self._domain_configs[domain] = config
        self._semaphores[domain] = asyncio.Semaphore(config.max_concurrency)
    
    def _get_config(self, domain: str) -> RateLimitConfig:
        """Get configuration for a domain."""
        return self._domain_configs.get(domain, self.default_config)
    
    def _get_domain(self, url: str) -> str:
        """Extract domain from URL."""
        parsed = urlparse(url)
        return parsed.netloc
    
    def _get_semaphore(self, domain: str) -> asyncio.Semaphore:
        """Get or create semaphore for domain."""
        if domain not in self._semaphores:
            config = self._get_config(domain)
            self._semaphores[domain] = asyncio.Semaphore(config.max_concurrency)
        return self._semaphores[domain]
    
    def _calculate_delay(self, config: RateLimitConfig) -> float:
        """Calculate jittered delay in seconds."""
        delay_ms = random.randint(config.min_delay_ms, config.max_delay_ms)
        return delay_ms / 1000.0
    
    def _check_burst(self, domain: str, config: RateLimitConfig) -> float:
        """Check burst limit and return additional wait time if needed.
        
        Returns:
            Additional seconds to wait (0 if within limits)
        """
        now = time.time()
        window_start = now - config.burst_window_seconds
        
        # Clean old entries
        self._request_times[domain] = [
            t for t in self._request_times[domain] if t > window_start
        ]
        
        if len(self._request_times[domain]) >= config.burst_limit:
            # Need to wait until oldest request falls out of window
            oldest = min(self._request_times[domain])
            wait_time = (oldest + config.burst_window_seconds) - now
            return max(0, wait_time)
        
        return 0
    
    async def acquire(self, url: str) -> None:
        """Acquire rate limit permit for a URL.
        
        Blocks until it's safe to make a request to the domain.
        
        Args:
            url: URL to acquire permit for
        """
        domain = self._get_domain(url)
        config = self._get_config(domain)
        semaphore = self._get_semaphore(domain)
        
        # Acquire concurrency permit
        await semaphore.acquire()
        
        try:
            async with self._locks[domain]:
                now = time.time()
                
                # Check burst limit
                burst_wait = self._check_burst(domain, config)
                if burst_wait > 0:
                    await asyncio.sleep(burst_wait)
                
                # Calculate delay since last request
                elapsed = now - self._last_request[domain]
                min_delay = config.min_delay_ms / 1000.0
                
                if elapsed < min_delay:
                    # Need to wait
                    delay = self._calculate_delay(config)
                    wait_time = max(0, delay - elapsed)
                    if wait_time > 0:
                        await asyncio.sleep(wait_time)
                
                # Record this request
                self._last_request[domain] = time.time()
                self._request_times[domain].append(time.time())
                
        except Exception:
            # Release semaphore on error
            semaphore.release()
            raise
    
    def release(self, url: str) -> None:
        """Release rate limit permit for a URL.
        
        Should be called after request completes.
        
        Args:
            url: URL to release permit for
        """
        domain = self._get_domain(url)
        if domain in self._semaphores:
            self._semaphores[domain].release()
    
    async def __call__(self, url: str):
        """Context manager for rate limiting.
        
        Usage:
            async with rate_limiter(url):
                await make_request(url)
        """
        return _RateLimitContext(self, url)
    
    def stats(self, domain: str | None = None) -> dict[str, any]:
        """Get rate limiter statistics.
        
        Args:
            domain: Specific domain or None for all
            
        Returns:
            Statistics dictionary
        """
        if domain:
            return {
                "domain": domain,
                "last_request": self._last_request.get(domain, 0),
                "requests_in_window": len(self._request_times.get(domain, [])),
                "config": self._get_config(domain),
            }
        
        return {
            "domains_tracked": len(self._last_request),
            "total_requests_tracked": sum(len(t) for t in self._request_times.values()),
        }


class _RateLimitContext:
    """Async context manager for rate limiting."""
    
    def __init__(self, limiter: RateLimiter, url: str):
        self.limiter = limiter
        self.url = url
    
    async def __aenter__(self) -> None:
        await self.limiter.acquire(self.url)
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        self.limiter.release(self.url)


class ThrottledBackend:
    """Wrapper that adds rate limiting to any backend.
    
    Usage:
        backend = HttpBackend()
        throttled = ThrottledBackend(backend, rate_limiter)
        result = await throttled.fetch(request)
    """
    
    def __init__(self, backend, rate_limiter: RateLimiter):
        self.backend = backend
        self.rate_limiter = rate_limiter
    
    @property
    def name(self) -> str:
        return f"throttled_{self.backend.name}"
    
    @property
    def supports_javascript(self) -> bool:
        return self.backend.supports_javascript
    
    async def fetch(self, request):
        """Fetch with rate limiting."""
        await self.rate_limiter.acquire(request.url)
        try:
            return await self.backend.fetch(request)
        finally:
            self.rate_limiter.release(request.url)
    
    async def render(self, request):
        """Render with rate limiting."""
        await self.rate_limiter.acquire(request.url)
        try:
            return await self.backend.render(request)
        finally:
            self.rate_limiter.release(request.url)
    
    async def close(self) -> None:
        await self.backend.close()
