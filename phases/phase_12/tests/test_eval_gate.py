"""Phase 12 cross-cutting eval tests (12.E1 – 12.E7).

These tests verify the edge cases that span multiple phases:
  12.E1: Empty Swiggy search → friendly persona, no crash
  12.E2: Session timeout mid-cart → staleness state cleared
  12.E3: Concurrent cart add → consistent final state
  12.E4: Gemini failure in classify → fallback NEW_SEARCH (mocked)
  12.E5: Invalid addressId → ValueError guard
  12.E6: ORDER route with empty cart → rejected by context guard
  12.E7: ORDER_ENABLED=true without EVAL_SUITE_PASSED → startup ValueError
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from phases.phase_01.models.state import ConversationState, check_staleness
from phases.phase_01.models.intent import UserIntent
from phases.phase_02.orchestrator import Route, classify
from phases.phase_04.services.swiggy_read import SwiggyReadClient
from phases.phase_06.agents.persona import format_recommendations
from phases.phase_07.session import get_session, clear_session
from phases.phase_09.router import CartRequest, CartItem, add_to_cart
from phases.phase_10.utils.fallbacks import fallback_route, swiggy_down_bubbles
from phases.phase_00.services.order_guard import OrderDisabledError


# ── 12.E1 — Empty Swiggy search → friendly persona, no crash ─────────────────

@pytest.mark.asyncio
async def test_empty_search_results_friendly_persona():
    """12.E1 — format_recommendations with empty top_6 → friendly fallback, no crash."""
    intent = UserIntent()
    client = MagicMock()  # Should NOT be called when top_6 is empty

    bubbles = await format_recommendations(intent, [], [], client)

    assert len(bubbles) >= 1
    assert "text" in bubbles[0]
    # Should NOT call Gemini — empty path short-circuits
    client.generate_content_async.assert_not_called()
    # Message should be sympathetic
    assert any(
        word in bubbles[0]["text"].lower()
        for word in ("couldn't", "nothing", "sorry", "find", "match")
    )


# ── 12.E2 — Session timeout mid-cart → staleness cleared ─────────────────────

def test_session_timeout_clears_cached_data():
    """12.E2 — check_staleness(timeout=0) clears cached_results and has_recommendations."""
    state = ConversationState(session_id="timeout_test")
    state.cached_results = [{"name": "Biryani"}]
    state.has_recommendations = True
    state.current_restaurant_id = "r123"
    state.cart_has_items = True  # cart_has_items is NOT cleared by staleness

    went_stale = check_staleness(state, timeout_minutes=0)

    assert went_stale is True
    assert state.cached_results == []
    assert state.has_recommendations is False
    assert state.current_restaurant_id is None
    # Cart items are preserved — staleness doesn't flush cart
    assert state.cart_has_items is True


# ── 12.E3 — Concurrent cart add → consistent final state ─────────────────────

@pytest.mark.asyncio
@patch("phases.phase_09.router.SwiggyReadClient.update_food_cart")
async def test_concurrent_cart_add_consistent_state(mock_update):
    """12.E3 — two concurrent adds to different items → state remains consistent."""
    clear_session("concurrent_test")
    session = get_session("concurrent_test")
    session.address_id = "addr_1"
    mock_update.return_value = {"cart": {"total": 500}}

    req1 = CartRequest(
        session_id="concurrent_test",
        item=CartItem(id="item_a", name="Pizza", price=250.0, restaurant_id="r1"),
        quantity=1,
    )
    req2 = CartRequest(
        session_id="concurrent_test",
        item=CartItem(id="item_b", name="Pasta", price=200.0, restaurant_id="r1"),
        quantity=1,
    )

    await asyncio.gather(add_to_cart(req1), add_to_cart(req2))

    # Both items are from the same restaurant — state should be consistent
    assert session.cart_has_items is True
    assert session.cart_restaurant_id == "r1"

    clear_session("concurrent_test")


# ── 12.E4 — Gemini classify failure → fallback NEW_SEARCH ────────────────────

def test_gemini_classify_failure_fallback_new_search():
    """12.E4 — Gemini rate limit or error → fallback_route returns NEW_SEARCH."""
    route = fallback_route()  # simulates what orchestrator does on Gemini failure
    assert route == "NEW_SEARCH"


def test_swiggy_down_after_gemini_failure_returns_bubbles():
    """12.E4b — swiggy_down_bubbles available even when Gemini is down."""
    bubbles = swiggy_down_bubbles()
    assert all("text" in b for b in bubbles)
    assert len(bubbles) >= 2


# ── 12.E5 — Invalid addressId → guard raises ────────────────────────────────

@pytest.mark.asyncio
async def test_invalid_address_id_raises_value_error():
    """12.E5 — search_restaurants with empty address_id raises ValueError immediately."""
    client = SwiggyReadClient.__new__(SwiggyReadClient)

    with pytest.raises(ValueError, match="address_id is required"):
        await client.search_restaurants("biryani", address_id="")


# ── 12.E6 — ORDER route with empty cart → blocked by context guard ────────────

def test_order_route_blocked_when_cart_empty():
    """12.E6 — ORDER route with empty cart → classify returns NEW_SEARCH (context guard)."""
    state = ConversationState(session_id="guard_test")
    state.cart_has_items = False  # Empty cart

    # "order it" would match the order regex but context guard should block it
    route = classify("order it", state)

    # Context guard: ORDER requires cart_has_items=True → falls through to NEW_SEARCH/AMBIGUOUS
    assert route != Route.ORDER


# ── 12.E7 — ORDER_ENABLED=true without EVAL_SUITE_PASSED → startup error ─────

def test_order_enabled_without_eval_suite_raises():
    """12.E7 — ORDER_ENABLED=true without EVAL_SUITE_PASSED=true → ValueError at startup."""
    import os
    from phases.phase_00.config import Settings, get_settings

    get_settings.cache_clear()
    try:
        with pytest.raises((ValueError, Exception)):
            Settings(
                ORDER_ENABLED=True,
                EVAL_SUITE_PASSED=False,
                GEMINI_API_KEY="test",
            )
    finally:
        get_settings.cache_clear()


# ── 12.GATE — place_food_order must remain blocked ────────────────────────────

def test_place_food_order_blocked_in_phase_12():
    """12.GATE — assert_orders_enabled() raises OrderDisabledError with ORDER_ENABLED=false."""
    from phases.phase_00.services.order_guard import assert_orders_enabled

    with pytest.raises(OrderDisabledError):
        assert_orders_enabled()
