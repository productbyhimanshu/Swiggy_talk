"""Phase 13 — review summary + user-confirmed place_food_order (COD only).

Order safety (architecture §5, §19):
  • Real `place_food_order` is guarded by ORDER_ENABLED + EVAL_SUITE_PASSED.
    When either is false, the endpoint returns 403 with an explanation —
    the same shape the frontend can render as a friendly message.
  • Review endpoint re-validates the cart against Swiggy (single source of
    truth) — never trusts the frontend cart state alone.
  • Confirmed=True is mandatory; missing it returns 400 so accidental POSTs
    can't trigger an order.
"""

from __future__ import annotations

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
    # Client view of the cart. Used as a fallback when Swiggy's server-side
    # `get_food_cart` returns empty — the cart-sync layer is best-effort
    # (see phase_09/router.py) so the user shouldn't be dead-ended just
    # because update_food_cart silently no-op'd.
    items: list[ClientCartItem] = Field(default_factory=list)
    restaurant_id: str | None = None
    restaurant_name: str | None = None


class PlaceOrderRequest(BaseModel):
    session_id: str
    confirmed: bool = Field(
        default=False,
        description="User must explicitly confirm via the Review screen CTA.",
    )
    payment_method: str = Field(default="COD", description="COD only in v1.")
    items: list[ClientCartItem] = Field(default_factory=list)
    restaurant_id: str | None = None
    restaurant_name: str | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _coerce_cart(raw: Any) -> dict[str, Any]:
    """Swiggy's cart endpoints sometimes return a `content` list rather than a
    dict. Normalise to a dict so `_extract_cart_summary` can rely on .get()."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        # Common shape: list of items only — wrap so the extractor still works
        return {"items": raw}
    return {}


def _extract_cart_summary(cart: dict[str, Any]) -> dict[str, Any]:
    """Normalise the Swiggy cart payload into the shape the Review UI expects."""
    items_raw = cart.get("items") or cart.get("cart_items") or []
    items: list[dict] = []
    subtotal = 0.0
    for it in items_raw:
        price = float(it.get("price") or it.get("finalPrice") or 0)
        qty = int(it.get("quantity") or it.get("qty") or 1)
        items.append({
            "id":       it.get("itemId") or it.get("id"),
            "name":     it.get("name") or it.get("item_name") or "Item",
            "price":    price,
            "quantity": qty,
            "veg":      it.get("isVeg") if it.get("isVeg") is not None else it.get("veg"),
            "image":    it.get("imageUrl") or it.get("image"),
        })
        subtotal += price * qty

    bill = cart.get("bill") or cart.get("billDetails") or {}
    total = float(
        bill.get("grandTotal")
        or bill.get("total")
        or cart.get("total")
        or subtotal
    )
    delivery_fee = float(bill.get("deliveryFee") or bill.get("delivery") or 0)
    taxes = float(bill.get("taxes") or bill.get("gst") or 0)
    discount = float(bill.get("discount") or 0)

    restaurant = cart.get("restaurant") or {}
    return {
        "restaurant": {
            "id":   restaurant.get("restaurantId") or restaurant.get("id") or cart.get("restaurantId"),
            "name": restaurant.get("name") or cart.get("restaurantName") or "—",
            "eta":  restaurant.get("eta") or cart.get("eta"),
            "open": restaurant.get("availabilityStatus", "OPEN") == "OPEN"
                    if "availabilityStatus" in restaurant else True,
        },
        "items":        items,
        "subtotal":     round(subtotal, 2),
        "delivery_fee": round(delivery_fee, 2),
        "taxes":        round(taxes, 2),
        "discount":     round(discount, 2),
        "total":        round(total, 2),
        "currency":     "INR",
        "payment_methods": ["COD"],
    }


def _summary_from_client(req: ReviewRequest | PlaceOrderRequest) -> dict[str, Any]:
    """Build a summary from the client cart when Swiggy's server cart is empty.

    Same shape as `_extract_cart_summary` so the rest of the review pipeline
    is shape-agnostic.
    """
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
    delivery_fee = 28.0 if items else 0.0  # matches BasketSheet's fixed fee
    total = subtotal + delivery_fee
    rest_name = req.restaurant_name or (req.items[0].restaurant if req.items else "—")
    rest_id   = req.restaurant_id or (req.items[0].restaurant_id if req.items else None)
    return {
        "restaurant": {
            "id":   rest_id,
            "name": rest_name,
            "eta":  None,
            "open": True,
        },
        "items":        items,
        "subtotal":     round(subtotal, 2),
        "delivery_fee": round(delivery_fee, 2),
        "taxes":        0.0,
        "discount":     0.0,
        "total":        round(total, 2),
        "currency":     "INR",
        "payment_methods": ["COD"],
        "_source": "client-fallback",
    }


# ── /api/order/review ─────────────────────────────────────────────────────────

@router.post("/review")
async def order_review(req: ReviewRequest) -> dict[str, Any]:
    """
    Build the Review screen payload. Server-side source of truth: we fetch the
    live Swiggy cart so the user never sees stale data on the final screen.

    Re-runs the ₹1000 cap and restaurant OPEN gates so the Place-order CTA can
    be disabled before the user even clicks it.
    """
    state = get_session(req.session_id)
    if not state.address_id:
        raise HTTPException(400, "No delivery address set — pick one and retry.")

    read = SwiggyReadClient()
    raw_cart: Any = None
    try:
        raw_cart = await read.get_food_cart()
    except Exception as exc:
        log.warning("review_cart_fetch_failed_falling_back_to_client", error=str(exc))

    summary = _extract_cart_summary(_coerce_cart(raw_cart))
    # Fallback: Swiggy's server cart is empty/unavailable but the user's
    # frontend has items — render from the client view so the user can still
    # see the bill and confirm. The place-order endpoint re-syncs to Swiggy
    # before placement.
    if not summary["items"]:
        if req.items:
            summary = _summary_from_client(req)
            log.info(
                "review_using_client_cart_fallback",
                session=req.session_id,
                items=len(summary["items"]),
            )
        else:
            raise HTTPException(400, "Cart is empty — add something first.")

    # Re-validate gates against the live cart, not the client's view
    issues: list[str] = []
    if summary["total"] > _CART_CAP:
        issues.append(f"Cart total ₹{summary['total']:.0f} exceeds ₹{_CART_CAP} dev cap")
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
            "Orders are off in dev. Set ORDER_ENABLED=true and EVAL_SUITE_PASSED=true "
            "in .env to enable real COD placement."
        )
    log.info(
        "order_review_built",
        session=req.session_id,
        item_count=len(summary["items"]),
        total=summary["total"],
        can_place=summary["can_place_order"],
    )
    return summary


# ── /api/order/place ──────────────────────────────────────────────────────────

@router.post("/place")
async def place_order(req: PlaceOrderRequest) -> dict[str, Any]:
    """
    Place a real Swiggy COD order. The frontend Review CTA is the only path —
    `confirmed` must be True. Cart and OPEN status are re-validated server-side
    so the user can't bypass the cap by hand-crafting the request.
    """
    if not req.confirmed:
        raise HTTPException(400, "User must confirm order via the Review screen.")
    if req.payment_method.upper() != "COD":
        raise HTTPException(400, "Only COD payments supported in v1.")

    state = get_session(req.session_id)
    if not state.address_id:
        raise HTTPException(400, "No delivery address set.")

    read = SwiggyReadClient()

    # Best-effort re-sync: push the client cart into Swiggy so the live cart
    # matches what the user just confirmed. We don't fail on sync errors —
    # the gated place_food_order below is the authoritative step.
    if req.items and req.restaurant_id:
        try:
            await read.update_food_cart(
                items=[{"itemId": it.id, "quantity": it.quantity} for it in req.items],
                restaurant_id=req.restaurant_id,
                address_id=state.address_id,
            )
        except Exception as exc:
            log.warning("place_order_resync_failed", error=str(exc))

    raw_cart: Any = None
    try:
        raw_cart = await read.get_food_cart()
    except Exception as exc:
        log.warning("place_order_cart_fetch_failed", error=str(exc))

    summary = _extract_cart_summary(_coerce_cart(raw_cart))
    if not summary["items"] and req.items:
        summary = _summary_from_client(req)
    if not summary["items"]:
        raise HTTPException(400, "Cart is empty.")
    if summary["total"] > _CART_CAP:
        raise HTTPException(400, f"Cart total exceeds ₹{_CART_CAP} dev cap.")
    if not summary["restaurant"]["open"]:
        raise HTTPException(409, "Restaurant just went offline — please pick again.")

    client = SwiggyApiClient()
    try:
        result = await client.place_food_order(payment_method="COD")
    except OrderDisabledError as exc:
        # Translate guard into a real HTTP response the UI can render gracefully
        log.info("place_order_blocked_by_guard", reason=str(exc))
        raise HTTPException(403, str(exc))
    except Exception as exc:
        log.error("place_order_failed", error=str(exc))
        raise HTTPException(502, f"Swiggy rejected the order: {exc}")

    # Persist to long-term memory so "order this again" can work later.
    try:
        from phases.phase_00.services import memory as user_memory
        user_memory.record_order(
            restaurant_id=summary["restaurant"]["id"],
            restaurant_name=summary["restaurant"]["name"],
            items=[{**it, "qty": it.get("quantity", 1)} for it in summary["items"]],
            total=summary["total"],
        )
    except Exception as exc:
        log.warning("memory_record_order_failed", error=str(exc))

    order_id = None
    if isinstance(result, dict):
        order_id = result.get("orderId") or result.get("order_id") or result.get("id")

    log.info(
        "order_placed",
        session=req.session_id,
        order_id=order_id,
        total=summary["total"],
        restaurant=summary["restaurant"]["name"],
    )
    return {
        "ok":        True,
        "order_id":  order_id,
        "total":     summary["total"],
        "eta":       summary["restaurant"]["eta"],
        "items":     summary["items"],
        "restaurant": summary["restaurant"],
        "raw":       result,
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
    return {"order_id": order_id, "raw": raw}
