"""Phase 10 — httpx retry with exponential backoff (architecture §14).

Policy:
  3× retries on 5xx / transport timeout with 1s, 2s, 4s backoff.
  4xx errors are NOT retried (non-retryable).
  After exhaustion → raises SwiggyUnavailableError.

This module provides a standalone `retry_call` coroutine that wraps any
async callable. The SwiggyReadClient already applies this logic internally;
this util is used for any other async Swiggy calls that live outside that class.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")

_RETRY_DELAYS = (1.0, 2.0, 4.0)  # seconds between attempts (3 retries = 4 total attempts)
_RETRYABLE_STATUS_CODES = frozenset(range(500, 600))


class RetryExhaustedError(Exception):
    """Raised when all retry attempts are exhausted."""


async def retry_call(
    fn: Callable[..., Awaitable[T]],
    *args: Any,
    retries: int = 3,
    delays: tuple[float, ...] = _RETRY_DELAYS,
    label: str = "call",
    **kwargs: Any,
) -> T:
    """
    Call an async function with exponential-backoff retry.

    Args:
        fn:      Async callable to invoke.
        *args:   Positional args forwarded to fn.
        retries: Max number of retry attempts (default 3; total attempts = retries + 1).
        delays:  Tuple of sleep durations between attempts.
        label:   Log label for observability.
        **kwargs: Keyword args forwarded to fn.

    Returns:
        Return value of fn on success.

    Raises:
        RetryExhaustedError: After all retries fail with a retryable error.
        Exception:            Re-raised immediately on non-retryable (4xx) errors.
    """
    last_exc: Exception | None = None
    attempt_delays = (*delays[:retries], None)  # None signals final attempt

    for attempt, backoff in enumerate(attempt_delays, start=1):
        try:
            result = await fn(*args, **kwargs)
            if attempt > 1:
                log.info("retry_succeeded label=%s attempt=%d", label, attempt)
            return result

        except Exception as exc:
            last_exc = exc
            status = _extract_status(exc)
            retryable = status is None or status in _RETRYABLE_STATUS_CODES

            log.warning(
                "retry_attempt_failed label=%s attempt=%d status=%s retrying=%s error=%s",
                label, attempt, status, retryable and backoff is not None, exc,
            )

            if not retryable:
                # 4xx — surface immediately, no retry
                raise

            if backoff is not None:
                await asyncio.sleep(backoff)

    raise RetryExhaustedError(
        f"{label} failed after {retries + 1} attempts: {last_exc}"
    ) from last_exc


def _extract_status(exc: Exception) -> int | None:
    """Try to extract an HTTP status code from common exception types."""
    # httpx.HTTPStatusError
    if hasattr(exc, "response") and hasattr(exc.response, "status_code"):
        return exc.response.status_code
    # Our own SwiggyApiError
    if hasattr(exc, "status_code"):
        return exc.status_code
    return None
