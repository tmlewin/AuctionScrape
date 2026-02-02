"""
Retry utilities with tenacity.

Provides configurable retry decorators for handling
transient failures in network operations.
"""

from __future__ import annotations

import logging
from functools import wraps
from typing import TYPE_CHECKING, Any, Callable, TypeVar

from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_random_exponential,
    before_sleep_log,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

T = TypeVar("T")


# Default retry configuration
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_MIN_WAIT = 1  # seconds
DEFAULT_MAX_WAIT = 30  # seconds
DEFAULT_MULTIPLIER = 2


class RetryConfig:
    """Configuration for retry behavior."""
    
    def __init__(
        self,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        min_wait: float = DEFAULT_MIN_WAIT,
        max_wait: float = DEFAULT_MAX_WAIT,
        multiplier: float = DEFAULT_MULTIPLIER,
        jitter: bool = True,
        retry_exceptions: tuple[type[Exception], ...] | None = None,
    ):
        """Initialize retry configuration.
        
        Args:
            max_attempts: Maximum number of attempts
            min_wait: Minimum wait time in seconds
            max_wait: Maximum wait time in seconds
            multiplier: Exponential backoff multiplier
            jitter: Add random jitter to wait times
            retry_exceptions: Exception types to retry on
        """
        self.max_attempts = max_attempts
        self.min_wait = min_wait
        self.max_wait = max_wait
        self.multiplier = multiplier
        self.jitter = jitter
        self.retry_exceptions = retry_exceptions or (Exception,)


def with_retry(
    func: Callable[..., T] | None = None,
    *,
    config: RetryConfig | None = None,
    max_attempts: int | None = None,
    min_wait: float | None = None,
    max_wait: float | None = None,
    retry_on: tuple[type[Exception], ...] | None = None,
) -> Callable[..., T]:
    """Decorator to add retry logic to a function.
    
    Can be used with or without arguments:
    
        @with_retry
        async def my_func(): ...
        
        @with_retry(max_attempts=5, retry_on=(ValueError,))
        async def my_func(): ...
    
    Args:
        func: Function to wrap (when used without parens)
        config: Full retry configuration
        max_attempts: Override max attempts
        min_wait: Override minimum wait
        max_wait: Override maximum wait
        retry_on: Exception types to retry
        
    Returns:
        Decorated function with retry logic
    """
    # Build config
    if config is None:
        config = RetryConfig()
    
    # Apply overrides
    if max_attempts is not None:
        config.max_attempts = max_attempts
    if min_wait is not None:
        config.min_wait = min_wait
    if max_wait is not None:
        config.max_wait = max_wait
    if retry_on is not None:
        config.retry_exceptions = retry_on
    
    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            # Build wait strategy
            if config.jitter:
                wait_strategy = wait_random_exponential(
                    multiplier=config.multiplier,
                    min=config.min_wait,
                    max=config.max_wait,
                )
            else:
                wait_strategy = wait_exponential(
                    multiplier=config.multiplier,
                    min=config.min_wait,
                    max=config.max_wait,
                )
            
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(config.max_attempts),
                wait=wait_strategy,
                retry=retry_if_exception_type(config.retry_exceptions),
                before_sleep=before_sleep_log(logger, logging.WARNING),
                reraise=True,
            ):
                with attempt:
                    return await fn(*args, **kwargs)
        
        return wrapper
    
    # Handle both @with_retry and @with_retry()
    if func is not None:
        return decorator(func)
    return decorator


async def retry_async(
    coro_func: Callable[..., T],
    *args: Any,
    config: RetryConfig | None = None,
    **kwargs: Any,
) -> T:
    """Execute an async function with retry logic.
    
    Alternative to decorator when you want more control.
    
    Args:
        coro_func: Async function to call
        *args: Positional arguments
        config: Retry configuration
        **kwargs: Keyword arguments
        
    Returns:
        Function result
        
    Raises:
        RetryError: If all attempts fail
    """
    if config is None:
        config = RetryConfig()
    
    if config.jitter:
        wait_strategy = wait_random_exponential(
            multiplier=config.multiplier,
            min=config.min_wait,
            max=config.max_wait,
        )
    else:
        wait_strategy = wait_exponential(
            multiplier=config.multiplier,
            min=config.min_wait,
            max=config.max_wait,
        )
    
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(config.max_attempts),
        wait=wait_strategy,
        retry=retry_if_exception_type(config.retry_exceptions),
        reraise=True,
    ):
        with attempt:
            return await coro_func(*args, **kwargs)


class RetryBudget:
    """Tracks retry budget to prevent infinite retry storms.
    
    Useful when you want to limit total retries across multiple
    operations, not just per-operation.
    """
    
    def __init__(self, max_total_retries: int = 100):
        """Initialize retry budget.
        
        Args:
            max_total_retries: Maximum total retries before refusing
        """
        self.max_total_retries = max_total_retries
        self._retry_count = 0
        self._exhausted = False
    
    @property
    def exhausted(self) -> bool:
        """Check if budget is exhausted."""
        return self._exhausted or self._retry_count >= self.max_total_retries
    
    @property
    def remaining(self) -> int:
        """Get remaining retry budget."""
        return max(0, self.max_total_retries - self._retry_count)
    
    def record_retry(self) -> bool:
        """Record a retry attempt.
        
        Returns:
            True if retry is allowed, False if budget exhausted
        """
        if self.exhausted:
            return False
        self._retry_count += 1
        if self._retry_count >= self.max_total_retries:
            self._exhausted = True
        return True
    
    def reset(self) -> None:
        """Reset the retry budget."""
        self._retry_count = 0
        self._exhausted = False
