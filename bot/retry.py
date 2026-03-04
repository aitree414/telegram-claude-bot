"""Generic retry mechanism for API calls and other operations.

Provides configurable retry decorators and utilities for handling
transient failures with exponential backoff, jitter, and customizable
retry conditions.
"""

import asyncio
import functools
import logging
import random
import time
from typing import Any, Callable, Optional, Type, Tuple, Union, List

logger = logging.getLogger(__name__)

# Default retry settings
DEFAULT_MAX_RETRIES = 3
DEFAULT_INITIAL_DELAY = 1.0  # seconds
DEFAULT_MAX_DELAY = 30.0  # seconds
DEFAULT_BACKOFF_FACTOR = 2.0
DEFAULT_JITTER = 0.1  # ±10% jitter


def retry(
    max_retries: int = DEFAULT_MAX_RETRIES,
    initial_delay: float = DEFAULT_INITIAL_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    jitter: float = DEFAULT_JITTER,
    retryable_exceptions: Optional[Tuple[Type[Exception], ...]] = None,
    retryable_status_codes: Optional[List[int]] = None,
    retry_condition: Optional[Callable[[Exception], bool]] = None,
    on_retry: Optional[Callable[[int, Exception], None]] = None,
):
    """Decorator for retrying a function on failure.

    Args:
        max_retries: Maximum number of retry attempts (excluding initial attempt)
        initial_delay: Initial delay between retries in seconds
        max_delay: Maximum delay between retries in seconds
        backoff_factor: Multiplier applied to delay after each retry
        jitter: Random jitter factor (0.0 to 1.0) to add to delays
        retryable_exceptions: Tuple of exception types that should trigger a retry
        retryable_status_codes: List of HTTP status codes that should trigger a retry
        retry_condition: Custom function that takes an exception and returns True if retryable
        on_retry: Callback function called before each retry attempt (attempt_num, exception)

    Returns:
        Decorated function that will retry on failure.

    Examples:
        >>> @retry(max_retries=3, retryable_exceptions=(ConnectionError, TimeoutError))
        >>> def api_call():
        >>>     ...

        >>> @retry(retryable_status_codes=[429, 500, 502, 503, 504])
        >>> def http_request():
        >>>     ...
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e

                    # Check if this exception should trigger a retry
                    should_retry = False

                    # Check exception type
                    if retryable_exceptions and isinstance(e, retryable_exceptions):
                        should_retry = True

                    # Check status code (for HTTP exceptions)
                    elif retryable_status_codes and hasattr(e, 'status_code'):
                        if e.status_code in retryable_status_codes:
                            should_retry = True

                    # Check custom condition
                    elif retry_condition and retry_condition(e):
                        should_retry = True

                    # If no retry condition specified, retry on any exception
                    elif not (retryable_exceptions or retryable_status_codes or retry_condition):
                        should_retry = True

                    # Should we retry?
                    if should_retry and attempt < max_retries:
                        # Calculate delay with exponential backoff
                        delay = min(
                            initial_delay * (backoff_factor ** attempt),
                            max_delay
                        )

                        # Add jitter
                        if jitter > 0:
                            jitter_amount = delay * jitter
                            delay = delay + random.uniform(-jitter_amount, jitter_amount)
                            delay = max(0.1, delay)  # Ensure positive delay

                        # Call on_retry callback
                        if on_retry:
                            try:
                                on_retry(attempt + 1, e)
                            except Exception:
                                pass  # Don't let callback failure break retry logic

                        logger.warning(
                            f"Retry attempt {attempt + 1}/{max_retries} for {func.__name__} "
                            f"after error: {e}. Waiting {delay:.2f}s before retry."
                        )

                        time.sleep(delay)
                        continue
                    else:
                        # No more retries or exception not retryable
                        raise

            # This point should never be reached due to raise in loop
            raise last_exception if last_exception else RuntimeError("Unexpected error in retry logic")

        return wrapper

    return decorator


def async_retry(
    max_retries: int = DEFAULT_MAX_RETRIES,
    initial_delay: float = DEFAULT_INITIAL_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    jitter: float = DEFAULT_JITTER,
    retryable_exceptions: Optional[Tuple[Type[Exception], ...]] = None,
    retryable_status_codes: Optional[List[int]] = None,
    retry_condition: Optional[Callable[[Exception], bool]] = None,
    on_retry: Optional[Callable[[int, Exception], None]] = None,
):
    """Async version of the retry decorator."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e

                    # Check if this exception should trigger a retry
                    should_retry = False

                    if retryable_exceptions and isinstance(e, retryable_exceptions):
                        should_retry = True
                    elif retryable_status_codes and hasattr(e, 'status_code'):
                        if e.status_code in retryable_status_codes:
                            should_retry = True
                    elif retry_condition and retry_condition(e):
                        should_retry = True
                    elif not (retryable_exceptions or retryable_status_codes or retry_condition):
                        should_retry = True

                    if should_retry and attempt < max_retries:
                        delay = min(
                            initial_delay * (backoff_factor ** attempt),
                            max_delay
                        )

                        if jitter > 0:
                            jitter_amount = delay * jitter
                            delay = delay + random.uniform(-jitter_amount, jitter_amount)
                            delay = max(0.1, delay)

                        if on_retry:
                            try:
                                on_retry(attempt + 1, e)
                            except Exception:
                                pass

                        logger.warning(
                            f"Retry attempt {attempt + 1}/{max_retries} for {func.__name__} "
                            f"after error: {e}. Waiting {delay:.2f}s before retry."
                        )

                        await asyncio.sleep(delay)
                        continue
                    else:
                        raise

            raise last_exception if last_exception else RuntimeError("Unexpected error in retry logic")

        return wrapper

    return decorator


def retry_with_exponential_backoff(
    func: Callable,
    max_retries: int = DEFAULT_MAX_RETRIES,
    initial_delay: float = DEFAULT_INITIAL_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    jitter: float = DEFAULT_JITTER,
    **retry_kwargs
) -> Any:
    """Functional version of retry for inline use.

    Example:
        >>> result = retry_with_exponential_backoff(
        >>>     lambda: api_call(arg1, arg2),
        >>>     max_retries=3
        >>> )
    """
    retry_decorator = retry(
        max_retries=max_retries,
        initial_delay=initial_delay,
        max_delay=max_delay,
        backoff_factor=backoff_factor,
        jitter=jitter,
        **retry_kwargs
    )

    return retry_decorator(func)()


def is_retryable_http_error(status_code: int) -> bool:
    """Check if an HTTP status code represents a retryable error.

    Returns True for:
    - 429 Too Many Requests
    - 5xx Server Errors
    """
    return status_code == 429 or (500 <= status_code < 600)


def create_retry_context(
    max_retries: int = DEFAULT_MAX_RETRIES,
    initial_delay: float = DEFAULT_INITIAL_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    jitter: float = DEFAULT_JITTER,
    retryable_exceptions: Optional[Tuple[Type[Exception], ...]] = None,
    retryable_status_codes: Optional[List[int]] = None,
) -> dict:
    """Create a retry configuration dictionary for consistent use across the application.

    Returns:
        Dictionary with retry configuration that can be passed to retry() decorator.
    """
    return {
        'max_retries': max_retries,
        'initial_delay': initial_delay,
        'max_delay': max_delay,
        'backoff_factor': backoff_factor,
        'jitter': jitter,
        'retryable_exceptions': retryable_exceptions,
        'retryable_status_codes': retryable_status_codes,
    }


# Pre-configured retry contexts for common use cases
API_RETRY_CONTEXT = create_retry_context(
    max_retries=3,
    initial_delay=1.0,
    max_delay=10.0,
    backoff_factor=2.0,
    retryable_exceptions=(
        ConnectionError,
        TimeoutError,
    ),
    retryable_status_codes=[429, 500, 502, 503, 504],
)

DEEPSEEK_RETRY_CONTEXT = create_retry_context(
    max_retries=3,
    initial_delay=1.0,
    max_delay=10.0,
    backoff_factor=2.0,
    retryable_exceptions=(
        # OpenAI/DeepSeek specific exceptions
        # Note: These need to be imported where used
    ),
    retryable_status_codes=[429, 500, 502, 503, 504],
)

NETWORK_RETRY_CONTEXT = create_retry_context(
    max_retries=3,
    initial_delay=0.5,
    max_delay=5.0,
    backoff_factor=1.5,
    retryable_exceptions=(ConnectionError, TimeoutError),
)