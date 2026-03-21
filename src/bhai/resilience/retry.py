"""
Shared retry-with-backoff utility for all external API calls.
Replaces ad-hoc retry loops in STT, LLM, and TTS backends.
"""

import logging
import time
from typing import Callable, Optional, TypeVar

T = TypeVar("T")
logger = logging.getLogger("bhai.resilience.retry")


def retry_with_backoff(
    fn: Callable[..., T],
    *args,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
    on_failure: Optional[Callable[[Exception, int], None]] = None,
    **kwargs,
) -> T:
    """
    Call *fn* with retries and exponential backoff.

    Args:
        fn: Callable to invoke.
        max_attempts: Total tries before giving up (default 3).
        base_delay: Initial delay in seconds (default 1.0).
        max_delay: Cap on delay between retries (default 10.0).
        on_failure: Optional callback(exception, attempt_number) on each failure.
        *args, **kwargs: Forwarded to *fn*.

    Returns:
        The return value of *fn* on success.

    Raises:
        The last exception raised by *fn* after all attempts are exhausted.
    """
    last_exc: Exception = RuntimeError("unreachable")
    for attempt in range(1, max_attempts + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if on_failure:
                on_failure(exc, attempt)

            if attempt == max_attempts:
                logger.error(
                    "All %d attempts failed for %s: %s",
                    max_attempts,
                    getattr(fn, "__name__", repr(fn)),
                    exc,
                )
                raise

            delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
            logger.warning(
                "Attempt %d/%d for %s failed (%s), retrying in %.1fs",
                attempt,
                max_attempts,
                getattr(fn, "__name__", repr(fn)),
                exc,
                delay,
            )
            time.sleep(delay)

    raise last_exc  # unreachable, but keeps type checkers happy
