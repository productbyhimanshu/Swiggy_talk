"""Phase 9 — cart sync.

Swiggy's update_food_cart REPLACES the whole cart with the items sent (and
rejects quantity 0 with a 500), so the browser sends its entire basket on
every change and this endpoint mirrors it into Swiggy:
  • empty basket → flush_food_cart
  • otherwise   → update_food_cart(all items), then report which items
                  Swiggy didn't keep (e.g. no longer available)
Requests carry a client sequence number; an older request that arrives after
a newer one is ignored so rapid +/− taps can't leave Swiggy with a stale cart.
"""

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from phases.phase_00.logging_setup import get_logger
from phases.phase_00.services.swiggy_api import SwiggyApiError
from phases.phase_04.services.swiggy_read import SwiggyReadClient, SwiggyUnavailableError
from phases.phase_07.session import get_session, save_session

log = get_logger(__name__)
router = APIRouter(prefix="/api/cart", tags=["cart"])

_CART_CAP = 1000  # ₹ — Swiggy Builders Club cap

# Per-process (single worker today).
_sync_locks: dict[str, asyncio.Lock] = {}
_last_seq: dict[str, int] = {}


class SyncItem(BaseModel):
    id: str
    quantity: int = 1
    price: float = 0
    name: str = ""


class CartSyncRequest(BaseModel):
    session_id: str
    seq: int = 0
    restaurant_id: str | None = None
    restaurant_name: str | None = None
    items: list[SyncItem] = Field(default_factory=list)


@router.post("/sync")
async def sync_cart(req: CartSyncRequest):
    """Make the user's Swiggy cart exactly the browser basket."""
    state = get_session(req.session_id)
    items = [it for it in req.items if it.quantity > 0]
    if sum(it.price * it.quantity for it in items) > _CART_CAP:
        raise HTTPException(status_code=400, detail=f"Cart value cannot exceed ₹{_CART_CAP}.")
    if items and not state.address_id:
        raise HTTPException(status_code=400, detail="Pick a delivery address first.")
    if items and not req.restaurant_id:
        raise HTTPException(status_code=400, detail="Basket has no restaurant.")

    lock = _sync_locks.setdefault(req.session_id, asyncio.Lock())
    async with lock:
        if req.seq < _last_seq.get(req.session_id, -1):
            return {"ok": True, "stale": True}
        _last_seq[req.session_id] = req.seq

        client = SwiggyReadClient()
        try:
            if not items:
                await client.flush_food_cart()
                live = []
                to_pay = 0
            else:
                res = await client.update_food_cart(
                    items=[{"menu_item_id": it.id, "quantity": it.quantity} for it in items],
                    restaurant_id=req.restaurant_id,
                    address_id=state.address_id,
                    restaurant_name=req.restaurant_name,
                )
                data = res.get("data") or {}
                live = [i for i in data.get("items") or [] if isinstance(i, dict)]
                to_pay = (data.get("pricing") or {}).get("to_pay")
        except (SwiggyApiError, SwiggyUnavailableError) as exc:
            log.warning("cart_sync_failed", error=str(exc))
            raise HTTPException(status_code=502, detail=str(exc))

        kept = {str(i.get("menu_item_id")): int(i.get("quantity") or 0) for i in live}
        missing = [it.id for it in items if kept.get(it.id) != it.quantity]
        state.cart_has_items = bool(live)
        state.cart_restaurant_id = req.restaurant_id if live else None
        save_session(state)
        if missing:
            log.warning("cart_sync_items_dropped", missing=missing)
        return {
            "ok": not missing,
            "items": [{"id": k, "quantity": v} for k, v in kept.items()],
            "missing": missing,
            "to_pay": to_pay,
        }
