"""Phase 9 — the browser basket is mirrored into Swiggy's (replace-whole-cart) API."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from phases.phase_04.services.swiggy_read import SwiggyUnavailableError
from phases.phase_07.session import clear_session, get_session
from phases.phase_09 import router as cart
from phases.phase_09.router import CartSyncRequest, SyncItem, sync_cart


def _live(*pairs):
    """update_food_cart response with the given (id, qty) items kept by Swiggy."""
    return {"statusCode": 0, "data": {"items": [{"menu_item_id": int(i), "quantity": q} for i, q in pairs],
                                      "pricing": {"to_pay": 470}}}


@pytest.fixture
def session():
    cart._sync_locks.clear()
    cart._last_seq.clear()
    clear_session("cart_s")
    s = get_session("cart_s")
    s.address_id = "addr1"
    yield s
    clear_session("cart_s")


def _req(*items, seq=1, rest="r1"):
    return CartSyncRequest(session_id="cart_s", seq=seq, restaurant_id=rest, restaurant_name="R",
                           items=[SyncItem(id=i, quantity=q, price=p) for i, q, p in items])


@pytest.mark.asyncio
async def test_sends_whole_basket_every_time(session):
    with patch.object(cart.SwiggyReadClient, "update_food_cart",
                      new=AsyncMock(return_value=_live(("1", 1), ("2", 2)))) as upd:
        out = await sync_cart(_req(("1", 1, 100), ("2", 2, 50)))
    sent = upd.call_args.kwargs["items"]
    assert sent == [{"menu_item_id": "1", "quantity": 1}, {"menu_item_id": "2", "quantity": 2}]
    assert out["ok"] and out["missing"] == [] and out["to_pay"] == 470
    assert session.cart_has_items and session.cart_restaurant_id == "r1"


@pytest.mark.asyncio
async def test_removing_a_dish_sends_the_rest_not_quantity_zero(session):
    with patch.object(cart.SwiggyReadClient, "update_food_cart",
                      new=AsyncMock(return_value=_live(("2", 1)))) as upd:
        await sync_cart(_req(("1", 0, 100), ("2", 1, 50)))
    assert upd.call_args.kwargs["items"] == [{"menu_item_id": "2", "quantity": 1}]


@pytest.mark.asyncio
async def test_empty_basket_flushes(session):
    session.cart_has_items = True
    with patch.object(cart.SwiggyReadClient, "flush_food_cart", new=AsyncMock()) as flush, \
         patch.object(cart.SwiggyReadClient, "update_food_cart", new=AsyncMock()) as upd:
        out = await sync_cart(_req())
    flush.assert_awaited_once()
    upd.assert_not_called()
    assert out["ok"] and not session.cart_has_items and session.cart_restaurant_id is None


@pytest.mark.asyncio
async def test_items_swiggy_dropped_are_reported(session):
    with patch.object(cart.SwiggyReadClient, "update_food_cart",
                      new=AsyncMock(return_value=_live(("1", 1)))):
        out = await sync_cart(_req(("1", 1, 100), ("2", 1, 50)))
    assert out["ok"] is False and out["missing"] == ["2"]


@pytest.mark.asyncio
async def test_swiggy_failure_is_502_and_state_untouched(session):
    with patch.object(cart.SwiggyReadClient, "update_food_cart",
                      new=AsyncMock(side_effect=SwiggyUnavailableError("Timeout"))):
        with pytest.raises(HTTPException) as e:
            await sync_cart(_req(("1", 1, 100)))
    assert e.value.status_code == 502 and "Timeout" in e.value.detail
    assert not session.cart_has_items


@pytest.mark.asyncio
async def test_over_1000_blocked_before_calling_swiggy(session):
    with patch.object(cart.SwiggyReadClient, "update_food_cart", new=AsyncMock()) as upd:
        with pytest.raises(HTTPException) as e:
            await sync_cart(_req(("1", 1, 1200)))
    assert e.value.status_code == 400 and "₹1000" in e.value.detail
    upd.assert_not_called()


@pytest.mark.asyncio
async def test_older_request_arriving_late_is_ignored(session):
    with patch.object(cart.SwiggyReadClient, "update_food_cart",
                      new=AsyncMock(return_value=_live(("1", 3)))) as upd:
        await sync_cart(_req(("1", 3, 100), seq=5))
        out = await sync_cart(_req(("1", 1, 100), seq=4))
    assert out.get("stale") is True and upd.await_count == 1


@pytest.mark.asyncio
async def test_concurrent_syncs_are_serialised(session):
    calls = []

    async def slow_update(self, **kw):
        calls.append(("start", kw["items"][0]["quantity"]))
        await asyncio.sleep(0.01)
        calls.append(("end", kw["items"][0]["quantity"]))
        return _live(("1", kw["items"][0]["quantity"]))

    with patch.object(cart.SwiggyReadClient, "update_food_cart", new=slow_update):
        await asyncio.gather(sync_cart(_req(("1", 1, 100), seq=1)),
                             sync_cart(_req(("1", 2, 100), seq=2)))
    assert calls == [("start", 1), ("end", 1), ("start", 2), ("end", 2)]
