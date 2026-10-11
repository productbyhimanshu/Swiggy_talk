"""Phase 13 — review summary + user-confirmed place_food_order (cash on delivery).

Order safety (architecture §5, §19):
  • Real `place_food_order` is guarded by ORDER_ENABLED (set in .env); when
    false the endpoint returns 403 with an explanation the UI renders.
  • Swiggy places whatever is in the user's *Swiggy* cart, so the only cart
    that counts is the live one from get_food_cart. Before placing, the cart
    is rebuilt from the items the user confirmed and must read back matching.
  • Success means Swiggy returned an order id, or the order is visible in the
    user's active orders. Anything else is reported as a failure.
  • One placement at a time per session, no placement while an order from
    the same restaurant is still active, and after an unconfirmed attempt the
    session is held off briefly so a retry can't create a duplicate.
  • confirmed=True is mandatory; missing it returns 400.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from phases.phase_00.config import get_settings
from phases.phase_00.logging_setup import get_logger
from phases.phase_00.services.order_guard import OrderDisabledError
from phases.phase_00.services.swiggy_api import SwiggyApiClient
from phases.phase_04.services.swiggy_read import SwiggyReadClient
from phases.phase_07.session import get_session

log = get_logger(__name__)
router = APIRouter(prefix="/api/order", tags=["order"])

_CART_CAP = 1000  # ₹ — Swiggy Builders Club cap (architecture §2)
_RETRY_HOLDOFF_SECONDS = 180

# Per-process guards (single worker today; move to Redis with more workers).
_place_locks: dict[str, asyncio.Lock] = {}
_unconfirmed_attempt_at: dict[str, float] = {}


# ── Schemas ───────────────────────────────────────────────────────────────────

class ClientCartItem(BaseModel):
    id: str
    name: str
    price: float
    quantity: int = 1
    veg: bool | None = None
    restaurant_id: str | None = None
    restaurant: str | None = None
    image: str | None = None


class ReviewRequest(BaseModel):
    session_id: str
    # The basket the user sees. Pushed into Swiggy's cart before reading it
    # back; shown (with placing disabled) only if Swiggy's cart can't be read.
    items: list[ClientCartItem] = Field(default_factory=list)
    restaurant_id: str | None = None
    restaurant_name: str | None = None


class PlaceOrderRequest(BaseModel):
    session_id: str
    confirmed: bool = Field(
        default=False,
        description="User must explicitly confirm via the Review screen CTA.",
    )
    payment_method: str = Field(default="COD", description="Cash on delivery only in v1.")
    items: list[ClientCartItem] = Field(default_factory=list)
    restaurant_id: str | None = None
    restaurant_name: str | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _unwrap_cart(raw: Any) -> dict[str, Any]:
    """get_food_cart's structuredContent keeps the cart under `data` (None when empty)."""
    if not isinstance(raw, dict):
        return {}
    data = raw.get("data")
    if isinstance(data, dict):
        return data
    return raw


def _first(d: dict, *keys: str, default: Any = None) -> Any:
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return default


def _num(v: Any) -> float:
    try:
        return float(str(v).replace("₹", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _extract_cart_summary(raw: Any) -> dict[str, Any]:
    """Normalise Swiggy's cart payload into the shape the Review UI expects."""
    cart = _unwrap_cart(raw)
    items_raw = _first(cart, "cartItems", "items", "cart_items", default=[]) or []
    items: list[dict] = []
    subtotal = 0.0
    for it in items_raw:
        if not isinstance(it, dict):
            continue
        qty = int(_num(_first(it, "quantity", "qty", default=1)) or 1)
        # Swiggy's final_price / total are LINE totals (₹658 for 2 × ₹329).
        unit = _num(_first(it, "price", "unitPrice", "unit_price", default=0))
        line_total = _num(_first(it, "final_price", "finalPrice", "total", "subtotal", default=0))
        price = unit or (round(line_total / qty, 2) if line_total else 0.0)
        veg = _first(it, "isVeg", "is_veg", "veg")
        if isinstance(veg, str):
            veg = veg.strip().lower() in ("1", "true", "veg")
        items.append({
            "id":       str(_first(it, "menu_item_id", "itemId", "item_id", "id", default="")),
            "name":     _first(it, "name", "item_name", "itemName", default="Item"),
            "price":    price,
            "quantity": qty,
            "veg":      veg,
            "image":    _first(it, "imageUrl", "image"),
        })
        subtotal += price * qty

    # Swiggy's food cart keeps the bill under `pricing`:
    # {item_total, delivery_charge, taxes_and_charges, to_pay}
    bill = _first(cart, "pricing", "bill", "billDetails", "bill_details", default={}) or {}
    if not isinstance(bill, dict):
        bill = {}
    item_total = _num(_first(bill, "item_total", "itemTotal", default=None) or subtotal)
    delivery = _num(_first(bill, "delivery_charge", "deliveryFee", "delivery", default=0))
    taxes = _num(_first(bill, "taxes_and_charges", "taxes", "gst", default=0))
    discount = _num(_first(bill, "discount", "total_discount", default=0))
    total = _num(_first(bill, "to_pay", "toPay", "grandTotal", "total", default=None)
                 or _first(cart, "to_pay", "toPay", "grandTotal", "total", default=None)
                 or (item_total + delivery + taxes - discount))
    # Whatever Swiggy charges but doesn't itemise — shown so the user sees
    # why the total is higher than the visible lines.
    other = total - (item_total + delivery + taxes - discount)

    restaurant = _first(cart, "restaurant", "restaurantDetails", default={}) or {}
    if not isinstance(restaurant, dict):
        restaurant = {}
    status = restaurant.get("availabilityStatus")
    eta = _first(restaurant, "eta", "deliveryTime") or cart.get("eta")
    if not eta and isinstance(restaurant.get("deliverySubtitle"), str):
        m = re.match(r"\s*(\d+(?:\s*-\s*\d+)?)\s*min", restaurant["deliverySubtitle"])
        eta = m.group(1).replace(" ", "") if m else None
    return {
        "restaurant": {
            "id":   _first(restaurant, "restaurantId", "id") or _first(cart, "restaurantId", "restaurant_id"),
            "name": _first(restaurant, "name") or _first(cart, "restaurantName", "restaurant_name", default="—"),
            "eta":  eta,
            "open": status in (None, "OPEN"),
        },
        "items":         items,
        "subtotal":      round(item_total, 2),
        "delivery_fee":  round(delivery, 2),
        "taxes":         round(taxes, 2),
        "discount":      round(discount, 2),
        "other_charges": round(other, 2) if other > 0.5 else 0.0,
        "total":         round(total, 2),
        "currency":      "INR",
        "payment_methods": ["COD"],
    }


def _summary_from_client(req: ReviewRequest | PlaceOrderRequest) -> dict[str, Any]:
    """Display-only summary from the browser basket (placing stays disabled)."""
    items = [
        {
            "id":       it.id,
            "name":     it.name,
            "price":    float(it.price),
            "quantity": int(it.quantity),
            "veg":      it.veg,
            "image":    it.image,
        }
        for it in req.items
    ]
    subtotal = sum(it["price"] * it["quantity"] for it in items)
    return {
        "restaurant": {
            "id":   req.restaurant_id or (req.items[0].restaurant_id if req.items else None),
            "name": req.restaurant_name or (req.items[0].restaurant if req.items else "—"),
            "eta":  None,
            "open": True,
        },
        "items":        items,
        "subtotal":     round(subtotal, 2),
        "delivery_fee": 0.0,
        "taxes":        0.0,
        "discount":     0.0,
        "total":        round(subtotal, 2),
        "currency":     "INR",
        "payment_methods": ["COD"],
        "_source": "client-fallback",
    }


def _same_items(live: list[dict], confirmed: list[ClientCartItem]) -> bool:
    want = {str(it.id): int(it.quantity) for it in confirmed}
    have: dict[str, int] = {}
    for it in live:
        have[str(it["id"])] = have.get(str(it["id"]), 0) + int(it["quantity"])
    return bool(want) and want == have


async def _rebuild_swiggy_cart(
    read: SwiggyReadClient, req: ReviewRequest | PlaceOrderRequest, address_id: str
) -> None:
    """Make Swiggy's cart exactly the confirmed basket: empty it, then add each item."""
    restaurant_id = req.restaurant_id or (req.items[0].restaurant_id if req.items else None)
    if not restaurant_id:
        raise HTTPException(400, "Basket has no restaurant — add the dish again.")
    await read.flush_food_cart()
    await read.update_food_cart(
        items=[{"menu_item_id": it.id, "quantity": it.quantity} for it in req.items],
        restaurant_id=restaurant_id,
        address_id=address_id,
        restaurant_name=req.restaurant_name,
    )


def _order_id_from(result: Any) -> str | None:
    if not isinstance(result, dict):
        return None
    for scope in (result, result.get("data"), result.get("order")):
        if isinstance(scope, dict):
            oid = _first(scope, "orderId", "order_id")
            if oid:
                return str(oid)
    return None


def _matches_restaurant(order: dict, restaurant_id: Any, restaurant_name: Any) -> bool:
    if restaurant_id and str(order.get("restaurantId")) == str(restaurant_id):
        return True
    return bool(restaurant_name) and order.get("restaurantName") == restaurant_name


# ── /api/order/review ─────────────────────────────────────────────────────────

@router.post("/review")
async def order_review(req: ReviewRequest) -> dict[str, Any]:
    """
    Build the Review screen from Swiggy's live cart, after pushing the user's
    basket into it. If Swiggy's cart can't be confirmed, the basket is shown
    with placing disabled and the reason listed under issues.
    """
    state = get_session(req.session_id)
    if not state.address_id:
        raise HTTPException(400, "No delivery address set — pick one and retry.")

    read = SwiggyReadClient()
    summary: dict[str, Any] = {"items": []}
    issues: list[str] = []
    try:
        if req.items:
            await _rebuild_swiggy_cart(read, req, state.address_id)
        summary = _extract_cart_summary(
            await read.get_food_cart(state.address_id, req.restaurant_name)
        )
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("review_cart_sync_failed", error=str(exc))

    if not summary["items"]:
        if not req.items:
            raise HTTPException(400, "Cart is empty — add something first.")
        summary = _summary_from_client(req)
        issues.append("Couldn't confirm your basket with Swiggy — try again in a moment.")
    elif req.items and not _same_items(summary["items"], req.items):
        issues.append("Swiggy's basket doesn't match yours — go back and re-add the dishes.")

    if summary["total"] > _CART_CAP:
        issues.append(f"Cart total ₹{summary['total']:.0f} exceeds ₹{_CART_CAP} cap")
    if not summary["restaurant"]["open"]:
        issues.append("Restaurant is currently closed")

    settings = get_settings()
    summary["address"] = {
        "id":    state.address_id,
        "label": getattr(state, "address_label", None),
        "chip":  getattr(state, "address_chip", None),
        "text":  getattr(state, "address_text", None),
    }
    summary["can_place_order"] = settings.orders_allowed and not issues
    summary["issues"] = issues
    summary["orders_enabled"] = settings.orders_allowed
    if not settings.orders_allowed:
        summary["disabled_reason"] = (
            "Orders are off. Set ORDER_ENABLED=true in .env (demo mode) "
            "to enable the Place Order CTA."
        )
    log.info(
        "order_review_built",
        session=req.session_id,
        item_count=len(summary["items"]),
        total=summary["total"],
        source=summary.get("_source", "swiggy"),
        can_place=summary["can_place_order"],
    )
    return summary


# ── /api/order/place ──────────────────────────────────────────────────────────

@router.post("/place")
async def place_order(req: PlaceOrderRequest) -> dict[str, Any]:
    """Place a real Swiggy cash-on-delivery order for exactly the confirmed basket."""
    if not req.confirmed:
        raise HTTPException(400, "User must confirm order via the Review screen.")
    if req.payment_method.upper() not in ("COD", "CASH"):
        raise HTTPException(400, "Only cash on delivery is supported in v1.")
    if not req.items:
        raise HTTPException(400, "Cart is empty.")

    lock = _place_locks.setdefault(req.session_id, asyncio.Lock())
    if lock.locked():
        raise HTTPException(409, "Your order is already being placed — hang on.")
    async with lock:
        return await _place_locked(req)


async def _place_locked(req: PlaceOrderRequest) -> dict[str, Any]:
    last = _unconfirmed_attempt_at.get(req.session_id)
    if last and time.time() - last < _RETRY_HOLDOFF_SECONDS:
        raise HTTPException(
            409,
            "Your last attempt wasn't confirmed by Swiggy. Check your Swiggy app "
            "before trying again (wait a couple of minutes).",
        )

    state = get_session(req.session_id)
    if not state.address_id:
        raise HTTPException(400, "No delivery address set.")
    address_id = state.address_id
    read = SwiggyReadClient()

    # 1. Swiggy's cart must be exactly what the user confirmed.
    try:
        await _rebuild_swiggy_cart(read, req, address_id)
        summary = _extract_cart_summary(await read.get_food_cart(address_id, req.restaurant_name))
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("place_order_cart_sync_failed", error=str(exc))
        raise HTTPException(502, "Couldn't update your Swiggy basket — nothing was ordered. Try again.")
    if not _same_items(summary["items"], req.items):
        log.warning("place_order_cart_mismatch", live=len(summary["items"]), confirmed=len(req.items))
        raise HTTPException(409, "Couldn't confirm your basket with Swiggy — nothing was ordered.")
    if summary["total"] > _CART_CAP:
        raise HTTPException(400, f"Cart total exceeds ₹{_CART_CAP} cap.")
    if not summary["restaurant"]["open"]:
        raise HTTPException(409, "Restaurant just went offline — please pick again.")

    rest_id = summary["restaurant"]["id"] or req.restaurant_id
    rest_name = summary["restaurant"]["name"] if summary["restaurant"]["name"] != "—" else req.restaurant_name

    # 2. Don't stack a second order on one that's still in progress.
    try:
        active_before = await read.get_food_orders(address_id, active_only=True)
    except Exception as exc:
        log.warning("place_order_active_check_failed", error=str(exc))
        raise HTTPException(502, "Couldn't check your active Swiggy orders — nothing was ordered.")
    if any(_matches_restaurant(o, rest_id, rest_name) for o in active_before):
        raise HTTPException(409, f"You already have an active order from {rest_name}. Check Swiggy first.")
    known_ids = {str(o.get("orderId")) for o in active_before}

    # 3. Place it.
    try:
        result = await SwiggyApiClient().place_food_order(address_id=address_id, payment_method="Cash")
    except OrderDisabledError as exc:
        log.info("place_order_blocked_by_guard", reason=str(exc))
        raise HTTPException(403, str(exc))
    except Exception as exc:
        log.error("place_order_failed", error=str(exc))
        raise HTTPException(502, f"Swiggy didn't accept the order — nothing was ordered. {exc}")

    # 4. Only a real Swiggy order counts as success.
    order_id = _order_id_from(result)
    if not order_id:
        try:
            active_after = await read.get_food_orders(address_id, active_only=True)
        except Exception:
            active_after = []
        new = [o for o in active_after
               if str(o.get("orderId")) not in known_ids and _matches_restaurant(o, rest_id, rest_name)]
        if new:
            order_id = str(new[0].get("orderId"))
    if not order_id:
        _unconfirmed_attempt_at[req.session_id] = time.time()
        log.error("place_order_unconfirmed", response=str(result)[:500])
        raise HTTPException(
            502,
            "Swiggy didn't confirm this order. Check your Swiggy app before trying again.",
        )

    _unconfirmed_attempt_at.pop(req.session_id, None)
    try:
        from phases.phase_00.services import memory as user_memory
        user_memory.record_order(
            restaurant_id=rest_id,
            restaurant_name=rest_name,
            items=[{**it, "qty": it.get("quantity", 1)} for it in summary["items"]],
            total=summary["total"],
        )
    except Exception as exc:
        log.warning("memory_record_order_failed", error=str(exc))

    log.info("order_placed", session=req.session_id, order_id=order_id,
             total=summary["total"], restaurant=rest_name)
    return {
        "ok":         True,
        "order_id":   order_id,
        "total":      summary["total"],
        "eta":        summary["restaurant"]["eta"],
        "items":      summary["items"],
        "restaurant": {**summary["restaurant"], "id": rest_id, "name": rest_name},
    }


# ── /api/order/status/{order_id} — for OrderStatus polling ────────────────────

@router.get("/status/{order_id}")
async def order_status(order_id: str) -> dict[str, Any]:
    """Read-only Swiggy `track_food_order` wrapper. Used by OrderStatus screen."""
    if not order_id:
        raise HTTPException(400, "order_id required")
    read = SwiggyReadClient()
    try:
        raw = await read.track_food_order(order_id)
    except Exception as exc:
        log.warning("order_status_failed", order_id=order_id, error=str(exc))
        raise HTTPException(502, "Couldn't fetch order status.")
    # Swiggy: {orders: [...], statusMessage}. Pick this order (or the only one).
    orders = [o for o in (raw.get("orders") or []) if isinstance(o, dict)]
    match = next((o for o in orders if str(o.get("orderId")) == str(order_id)),
                 orders[0] if len(orders) == 1 else None)
    status = ""
    if match:
        status = str(_first(match, "orderStatus", "status", "orderDeliveryStatus",
                            "deliveryStatus", default=""))
    return {"order_id": order_id, "status": status,
            "message": raw.get("statusMessage"), "raw": raw}
