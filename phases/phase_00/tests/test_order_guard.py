"""Phase 0 — order guard and place_food_order blocking."""

import pytest

from phases.phase_00.config import get_settings
from phases.phase_00.services.order_guard import OrderDisabledError, assert_orders_enabled
from phases.phase_00.services.swiggy_api import SwiggyApiClient, SwiggyApiError


def test_assert_orders_enabled_blocks_by_default(clean_env):
    with pytest.raises(OrderDisabledError, match="disabled"):
        assert_orders_enabled()


@pytest.mark.asyncio
async def test_call_tool_blocks_place_food_order(clean_env):
    client = SwiggyApiClient()
    with pytest.raises(SwiggyApiError, match="forbidden"):
        await client.call_tool("place_food_order", {})


@pytest.mark.asyncio
async def test_place_food_order_raises_when_disabled(clean_env):
    client = SwiggyApiClient()
    with pytest.raises(OrderDisabledError):
        await client.place_food_order()
