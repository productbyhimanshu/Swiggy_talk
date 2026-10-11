"""Placing an order only reports success when Swiggy really created one."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from phases.phase_13.routes import place_order as po


class FakeRead:
    def __init__(self, live_items, active_before=(), active_after=()):
        self.live_items = live_items
        self.active = [list(active_before), list(active_after)]
        self.calls: list = []

    async def flush_food_cart(self):
        self.calls.append("flush")

    async def update_food_cart(self, items, restaurant_id, address_id, restaurant_name=None):
        self.calls.append(("update", items, restaurant_id))

    async def get_food_cart(self, address_id, restaurant_name=None):
        if self.live_items is None:
            return {"statusCode": 0, "data": None}
        return {"data": {"cartItems": self.live_items, "restaurantId": "r1",
                         "restaurantName": "Chhabra's", "bill": {"toPay": 248}}}

    async def get_food_orders(self, address_id, active_only=False):
        return self.active.pop(0) if self.active else []


class FakeApi:
    def __init__(self, result=None, exc=None):
        self.result, self.exc, self.calls = result, exc, 0

    async def place_food_order(self, address_id, payment_method="Cash"):
        self.calls += 1
        assert payment_method == "Cash" and address_id == "addr1"
        if self.exc:
            raise self.exc
        return self.result


@pytest.fixture(autouse=True)
def wiring(monkeypatch):
    po._place_locks.clear()
    po._unconfirmed_attempt_at.clear()
    monkeypatch.setattr(po, "get_session", lambda sid: SimpleNamespace(address_id="addr1"))
    recorded: list = []
    from phases.phase_00.services import memory
    monkeypatch.setattr(memory, "record_order", lambda **kw: recorded.append(kw))
    yield recorded


def _install(monkeypatch, read, api):
    monkeypatch.setattr(po, "SwiggyReadClient", lambda: read)
    monkeypatch.setattr(po, "SwiggyApiClient", lambda: api)


def _req(**kw):
    base = dict(session_id="s1", confirmed=True, restaurant_id="r1", restaurant_name="Chhabra's",
                items=[po.ClientCartItem(id="111", name="Paneer", price=248, quantity=1)])
    return po.PlaceOrderRequest(**{**base, **kw})


LIVE = [{"menu_item_id": "111", "name": "Paneer", "price": 248, "quantity": 1}]


@pytest.mark.asyncio
async def test_success_requires_order_id(monkeypatch, wiring):
    read, api = FakeRead(LIVE), FakeApi({"orderId": "50999"})
    _install(monkeypatch, read, api)
    out = await po.place_order(_req())
    assert out["ok"] and out["order_id"] == "50999"
    assert read.calls[0] == "flush" and read.calls[1][1] == [{"menu_item_id": "111", "quantity": 1}]
    assert len(wiring) == 1  # memory recorded only on real success


@pytest.mark.asyncio
async def test_no_order_id_and_no_new_active_order_is_failure(monkeypatch, wiring):
    read, api = FakeRead(LIVE), FakeApi({"statusMessage": "something odd"})
    _install(monkeypatch, read, api)
    with pytest.raises(HTTPException) as e:
        await po.place_order(_req())
    assert e.value.status_code == 502 and "didn't confirm" in e.value.detail
    assert wiring == []
    # a quick retry is held off so it can't create a duplicate
    with pytest.raises(HTTPException) as e2:
        await po.place_order(_req())
    assert e2.value.status_code == 409 and api.calls == 1


@pytest.mark.asyncio
async def test_missing_id_but_new_active_order_counts(monkeypatch, wiring):
    after = [{"orderId": "777", "restaurantId": "r1", "restaurantName": "Chhabra's"}]
    read, api = FakeRead(LIVE, active_before=[], active_after=after), FakeApi({})
    _install(monkeypatch, read, api)
    out = await po.place_order(_req())
    assert out["order_id"] == "777"


@pytest.mark.asyncio
async def test_cart_mismatch_never_places(monkeypatch):
    wrong = [{"menu_item_id": "999", "name": "Other", "price": 100, "quantity": 2}]
    read, api = FakeRead(wrong), FakeApi({"orderId": "1"})
    _install(monkeypatch, read, api)
    with pytest.raises(HTTPException) as e:
        await po.place_order(_req())
    assert e.value.status_code == 409 and api.calls == 0


@pytest.mark.asyncio
async def test_empty_swiggy_cart_never_places(monkeypatch):
    read, api = FakeRead(None), FakeApi({"orderId": "1"})
    _install(monkeypatch, read, api)
    with pytest.raises(HTTPException):
        await po.place_order(_req())
    assert api.calls == 0


@pytest.mark.asyncio
async def test_existing_active_order_from_same_restaurant_blocks(monkeypatch):
    active = [{"orderId": "5", "restaurantId": "r1", "restaurantName": "Chhabra's"}]
    read, api = FakeRead(LIVE, active_before=active), FakeApi({"orderId": "6"})
    _install(monkeypatch, read, api)
    with pytest.raises(HTTPException) as e:
        await po.place_order(_req())
    assert e.value.status_code == 409 and api.calls == 0


@pytest.mark.asyncio
async def test_double_click_rejected_while_placing(monkeypatch):
    read, api = FakeRead(LIVE), FakeApi({"orderId": "1"})
    _install(monkeypatch, read, api)
    lock = po._place_locks.setdefault("s1", po.asyncio.Lock())
    await lock.acquire()
    try:
        with pytest.raises(HTTPException) as e:
            await po.place_order(_req())
        assert e.value.status_code == 409 and api.calls == 0
    finally:
        lock.release()


def test_real_swiggy_cart_shape_parses_full_bill():
    # Shape captured from a live get_food_cart (personal details replaced).
    raw = {"statusCode": 0, "statusMessage": "done", "data": {
        "cart_id": 1, "result": "success",
        "restaurant": {"name": "Chhabra's Pure Veg", "deliverySubtitle": "10-15 mins to Someone: Somewhere"},
        "items": [{"menu_item_id": 168702323, "name": "Dal Makhani With Jeera Rice", "quantity": 1,
                   "is_veg": "1", "subtotal": 220, "total": 220, "final_price": 220, "in_stock": 1}],
        "item_count": 1,
        "pricing": {"item_total": 220, "delivery_charge": 0, "delivery_charge_strikeoff": 31,
                    "taxes_and_charges": 49.98, "to_pay": 470},
    }}
    s = po._extract_cart_summary(raw)
    assert s["items"] == [{"id": "168702323", "name": "Dal Makhani With Jeera Rice", "price": 220.0,
                           "quantity": 1, "veg": True, "image": None}]
    assert s["total"] == 470 and s["subtotal"] == 220 and s["taxes"] == 49.98
    assert s["other_charges"] == 200.02  # charged but not itemised — must be visible
    assert s["restaurant"]["name"] == "Chhabra's Pure Veg" and s["restaurant"]["eta"] == "10-15"


def test_quantity_two_uses_unit_price_not_line_total():
    # Live shape: final_price/total are the line total for qty 2.
    raw = {"data": {"items": [{"menu_item_id": 177379645, "name": "Chicken Biryani Bowl", "quantity": 2,
                               "subtotal": 658, "total": 658, "final_price": 658}],
                    "pricing": {"item_total": 658, "delivery_charge": 0, "taxes_and_charges": 50.88,
                                "to_pay": 909}}}
    s = po._extract_cart_summary(raw)
    assert s["items"][0]["price"] == 329 and s["items"][0]["quantity"] == 2
    assert s["subtotal"] == 658 and s["total"] == 909


@pytest.mark.asyncio
async def test_status_reads_swiggy_orders_list(monkeypatch):
    class _R:
        async def track_food_order(self, order_id):
            return {"orders": [{"orderId": "123", "orderStatus": "Picked up"}],
                    "statusMessage": "Tracking information retrieved successfully"}

    monkeypatch.setattr(po, "SwiggyReadClient", lambda: _R())
    out = await po.order_status("123")
    assert out["status"] == "Picked up"

    class _Empty:
        async def track_food_order(self, order_id):
            return {"orders": [], "statusMessage": "No tracking information found"}

    monkeypatch.setattr(po, "SwiggyReadClient", lambda: _Empty())
    out = await po.order_status("123")
    assert out["status"] == "" and out["message"].startswith("No tracking")


@pytest.mark.asyncio
async def test_review_disables_placing_when_swiggy_cart_unconfirmed(monkeypatch):
    read = FakeRead(None)
    _install(monkeypatch, read, FakeApi())
    req = po.ReviewRequest(session_id="s1", restaurant_id="r1", restaurant_name="Chhabra's",
                           items=[po.ClientCartItem(id="111", name="Paneer", price=248)])
    out = await po.order_review(req)
    assert out["can_place_order"] is False and out["issues"]
    assert out["_source"] == "client-fallback"


@pytest.mark.asyncio
async def test_review_uses_live_cart_when_it_matches(monkeypatch):
    read = FakeRead(LIVE)
    _install(monkeypatch, read, FakeApi())
    req = po.ReviewRequest(session_id="s1", restaurant_id="r1", restaurant_name="Chhabra's",
                           items=[po.ClientCartItem(id="111", name="Paneer", price=248)])
    out = await po.order_review(req)
    assert out["issues"] == [] and out["total"] == 248 and "_source" not in out
