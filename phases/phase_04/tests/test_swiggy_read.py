"""Phase 4 — SwiggyReadClient tests (exit gates 4.E4, 4.E5).

Tests retry logic, order block, COD coupon filter, and address validation.
All LOCAL — uses tool overrides (no real Swiggy calls).
"""

from __future__ import annotations

import asyncio

import pytest

from phases.phase_04.services.swiggy_read import SwiggyReadClient, SwiggyUnavailableError
from phases.phase_00.services.swiggy_api import SwiggyApiError
from phases.phase_00.services.order_guard import OrderDisabledError


# ── Async sleep no-op (Python 3.11 compatible) ────────────────────────────────

async def _noop_sleep(_seconds: float) -> None:
    """Drop-in replacement for asyncio.sleep that returns immediately."""


# ── Fixture helpers ────────────────────────────────────────────────────────────

def _client() -> SwiggyReadClient:
    """Create a SwiggyReadClient with a fake API client (no real auth needed)."""
    from unittest.mock import MagicMock
    fake_api = MagicMock()
    fake_api.call_tool = MagicMock()  # replaced per test via set_tool_override
    client = SwiggyReadClient.__new__(SwiggyReadClient)
    client._api = fake_api
    client._tool_overrides = {}
    return client


# ── Retry logic — 4.E5 ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_retry_succeeds_on_third_attempt(monkeypatch):
    """First 2 calls return 503 → 3rd succeeds → result returned."""
    monkeypatch.setattr("asyncio.sleep", _noop_sleep)
    client = _client()
    call_count = 0

    async def flaky(args):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise SwiggyApiError("server error", status_code=503)
        return [{"addressId": "addr1"}]

    client.set_tool_override("get_addresses", flaky)
    result = await client.get_addresses()
    assert call_count == 3
    assert result[0]["addressId"] == "addr1"


@pytest.mark.asyncio
async def test_retry_exhausted_raises_unavailable(monkeypatch):
    """All 3 calls return 503 → SwiggyUnavailableError raised."""
    monkeypatch.setattr("asyncio.sleep", _noop_sleep)
    client = _client()

    async def always_fail(args):
        raise SwiggyApiError("server error", status_code=503)

    client.set_tool_override("get_addresses", always_fail)
    with pytest.raises(SwiggyUnavailableError):
        await client.get_addresses()


@pytest.mark.asyncio
async def test_non_retryable_4xx_raises_immediately(monkeypatch):
    """4xx error is NOT retried — surfaces immediately."""
    monkeypatch.setattr("asyncio.sleep", _noop_sleep)
    client = _client()
    call_count = 0

    async def bad_request(args):
        nonlocal call_count
        call_count += 1
        raise SwiggyApiError("bad request", status_code=400)

    client.set_tool_override("get_addresses", bad_request)
    with pytest.raises(SwiggyUnavailableError):
        await client.get_addresses()
    assert call_count == 1  # not retried


@pytest.mark.asyncio
async def test_transport_error_retried(monkeypatch):
    """Connection errors are retried just like 5xx."""
    monkeypatch.setattr("asyncio.sleep", _noop_sleep)
    client = _client()
    call_count = 0

    async def transport_err(args):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ConnectionError("connection refused")
        return []

    client.set_tool_override("search_restaurants", transport_err)
    result = await client.search_restaurants("biryani", "addr1")
    assert call_count == 3
    assert result == []


# ── address_id guard ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_restaurants_requires_address_id():
    client = _client()
    with pytest.raises(ValueError, match="address_id is required"):
        await client.search_restaurants("biryani", "")


@pytest.mark.asyncio
async def test_search_restaurants_requires_non_none_address():
    client = _client()
    with pytest.raises((ValueError, TypeError)):
        await client.search_restaurants("biryani", None)  # type: ignore[arg-type]


# ── COD coupon filter ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_coupons_filters_non_cod():
    client = _client()

    async def coupon_tool(args):
        return [
            {"code": "COD10", "paymentModes": ["cod"]},
            {"code": "ONLINE20", "paymentModes": ["online"]},
            {"code": "UPI15", "paymentModes": ["upi"]},
            {"code": "ANYCOUPON"},  # no restriction → COD compatible
        ]

    client.set_tool_override("fetch_food_coupons", coupon_tool)
    result = await client.fetch_food_coupons()
    codes = [c["code"] for c in result]
    assert "COD10" in codes
    assert "ANYCOUPON" in codes
    assert "ONLINE20" not in codes
    assert "UPI15" not in codes


@pytest.mark.asyncio
async def test_fetch_coupons_all_cod_compatible():
    client = _client()

    async def all_cod(args):
        return [
            {"code": "A", "paymentModes": ["cod", "card"]},
            {"code": "B"},
        ]

    client.set_tool_override("fetch_food_coupons", all_cod)
    result = await client.fetch_food_coupons()
    # "A" has "card" but also "cod" → compatible
    codes = [c["code"] for c in result]
    assert "A" in codes
    assert "B" in codes


# ── order blocked guard ────────────────────────────────────────────────────────

def test_order_disabled_error_with_order_enabled_false(monkeypatch):
    """place_food_order via SwiggyApiClient must raise OrderDisabledError."""
    import os
    monkeypatch.setenv("ORDER_ENABLED", "false")
    monkeypatch.setenv("EVAL_SUITE_PASSED", "false")
    from phases.phase_00.config import get_settings
    get_settings.cache_clear()

    from phases.phase_00.services.order_guard import assert_orders_enabled
    with pytest.raises(OrderDisabledError):
        assert_orders_enabled()

    get_settings.cache_clear()


# ── Response shape normalisation ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_addresses_normalises_list():
    client = _client()

    async def list_response(args):
        return [{"addressId": "a1"}, {"addressId": "a2"}]

    client.set_tool_override("get_addresses", list_response)
    result = await client.get_addresses()
    assert len(result) == 2
    assert result[0]["addressId"] == "a1"


@pytest.mark.asyncio
async def test_get_addresses_normalises_dict_wrapper():
    client = _client()

    async def dict_response(args):
        return {"addresses": [{"addressId": "a1"}]}

    client.set_tool_override("get_addresses", dict_response)
    result = await client.get_addresses()
    assert len(result) == 1


@pytest.mark.asyncio
async def test_search_restaurants_normalises_dict():
    client = _client()

    async def wrapped(args):
        return {"restaurants": [{"name": "Biryani House"}]}

    client.set_tool_override("search_restaurants", wrapped)
    result = await client.search_restaurants("biryani", "addr1")
    assert result[0]["name"] == "Biryani House"


@pytest.mark.asyncio
async def test_get_food_cart_returns_dict():
    client = _client()

    async def cart_data(args):
        return {"items": [], "total": 0}

    client.set_tool_override("get_food_cart", cart_data)
    result = await client.get_food_cart()
    assert isinstance(result, dict)
    assert result["total"] == 0
