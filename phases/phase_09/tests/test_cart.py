"""Eval suite for Phase 9 Cart sync and rules."""

import pytest
from unittest.mock import patch, AsyncMock
from fastapi import HTTPException

from phases.phase_09.router import add_to_cart, remove_from_cart, CartRequest, CartItem
from phases.phase_07.session import get_session, clear_session
from phases.phase_04.services.swiggy_read import SwiggyUnavailableError


@pytest.fixture
def clean_session():
    clear_session("test_session")
    session = get_session("test_session")
    session.address_id = "test_address"
    yield session
    clear_session("test_session")


@pytest.fixture
def base_req():
    return CartRequest(
        session_id="test_session",
        item=CartItem(id="123", name="Pizza", price=250.0, restaurant_id="r1"),
        quantity=1
    )


@pytest.mark.asyncio
@patch("phases.phase_09.router.SwiggyReadClient.update_food_cart")
async def test_add_remove_updates_state(mock_update, base_req, clean_session):
    """9.E1: add/remove updates cart_has_items."""
    mock_update.return_value = {"cart": {"total": 250}}
    
    assert not clean_session.cart_has_items
    
    await add_to_cart(base_req)
    assert clean_session.cart_has_items
    assert clean_session.cart_restaurant_id == "r1"
    
    mock_update.return_value = {"cart": {"total": 0}}
    await remove_from_cart(base_req)
    assert not clean_session.cart_has_items
    assert clean_session.cart_restaurant_id is None


@pytest.mark.asyncio
@patch("phases.phase_09.router.SwiggyReadClient.update_food_cart")
async def test_api_500_triggers_rollback(mock_update, base_req, clean_session):
    """9.E2: API 500 throws HTTP 500 causing frontend rollback."""
    mock_update.side_effect = Exception("Swiggy API Error")
    
    with pytest.raises(HTTPException) as exc:
        await add_to_cart(base_req)
        
    assert exc.value.status_code == 500
    # State should remain untouched since it failed
    assert not clean_session.cart_has_items


@pytest.mark.asyncio
@patch("phases.phase_09.router.SwiggyReadClient.flush_food_cart")
@patch("phases.phase_09.router.SwiggyReadClient.update_food_cart")
async def test_restaurant_switch_triggers_flush(mock_update, mock_flush, base_req, clean_session):
    """9.E3: restaurant switch triggers flush."""
    mock_update.return_value = {"cart": {"total": 250}}
    
    clean_session.cart_has_items = True
    clean_session.cart_restaurant_id = "r_old"
    
    await add_to_cart(base_req)
    
    mock_flush.assert_called_once()
    assert clean_session.cart_restaurant_id == "r1"


@pytest.mark.asyncio
@patch("phases.phase_09.router.SwiggyReadClient.update_food_cart")
async def test_cart_over_1000_blocked(mock_update, base_req, clean_session):
    """9.E4: cart > 1000 blocked immediately."""
    base_req.item.price = 1200.0
    
    with pytest.raises(HTTPException) as exc:
        await add_to_cart(base_req)
        
    assert exc.value.status_code == 400
    assert "₹1000" in exc.value.detail
    mock_update.assert_not_called()


@pytest.mark.asyncio
@patch("phases.phase_09.router.SwiggyReadClient.update_food_cart")
async def test_cart_timeout_raises_unavailable(mock_update, base_req, clean_session):
    """9.E5: update_cart timeout raises SwiggyUnavailableError."""
    mock_update.side_effect = SwiggyUnavailableError("Timeout")
    
    with pytest.raises(HTTPException) as exc:
        await add_to_cart(base_req)
        
    assert exc.value.status_code == 500
    assert "Timeout" in exc.value.detail
