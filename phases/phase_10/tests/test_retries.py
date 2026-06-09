"""Phase 10 eval suite — retries (architecture §14, 10.E1).

Tests:
  10.E1: Swiggy 503 → 3 retries → raises RetryExhaustedError
  10.E1b: 4xx error → NOT retried, raised immediately
  10.E1c: Success on 2nd attempt → returned normally
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch, call

from phases.phase_10.utils.retries import retry_call, RetryExhaustedError
from phases.phase_04.services.swiggy_read import SwiggyUnavailableError


# ── Helpers ───────────────────────────────────────────────────────────────────

class Fake5xxError(Exception):
    """Simulates a 5xx Swiggy API error."""
    status_code = 503


class Fake4xxError(Exception):
    """Simulates a 4xx (non-retryable) error."""
    status_code = 404


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_503_retried_3_times_then_raises():
    """10.E1 — Swiggy 503 → retried 3 times → RetryExhaustedError."""
    call_count = 0

    async def always_fail():
        nonlocal call_count
        call_count += 1
        raise Fake5xxError("Service Unavailable")

    with pytest.raises(RetryExhaustedError):
        await retry_call(always_fail, retries=3, delays=(0, 0, 0), label="test_503")

    # 1 initial + 3 retries = 4 total attempts
    assert call_count == 4


@pytest.mark.asyncio
async def test_4xx_not_retried():
    """10.E1b — 4xx error is NOT retried; raised immediately."""
    call_count = 0

    async def always_404():
        nonlocal call_count
        call_count += 1
        raise Fake4xxError("Not Found")

    with pytest.raises(Fake4xxError):
        await retry_call(always_404, retries=3, delays=(0, 0, 0), label="test_404")

    # Should only be called once — no retry on 4xx
    assert call_count == 1


@pytest.mark.asyncio
async def test_success_on_second_attempt():
    """10.E1c — fails once, succeeds on 2nd attempt → result returned."""
    attempt = 0

    async def flaky():
        nonlocal attempt
        attempt += 1
        if attempt < 2:
            raise Fake5xxError("momentary blip")
        return {"ok": True}

    result = await retry_call(flaky, retries=3, delays=(0, 0, 0), label="test_flaky")

    assert result == {"ok": True}
    assert attempt == 2


@pytest.mark.asyncio
async def test_transport_error_retried():
    """10.E1d — plain connection error (no status code) is also retried."""
    call_count = 0

    async def connection_refused():
        nonlocal call_count
        call_count += 1
        raise ConnectionRefusedError("Connection refused")

    with pytest.raises(RetryExhaustedError):
        await retry_call(connection_refused, retries=2, delays=(0, 0), label="test_conn")

    assert call_count == 3  # 1 + 2 retries
