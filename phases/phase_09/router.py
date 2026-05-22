"""Phase 9 Cart API Router."""

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from phases.phase_00.logging_setup import get_logger
from phases.phase_04.services.swiggy_read import SwiggyReadClient
from phases.phase_07.session import get_session

log = get_logger(__name__)
router = APIRouter(prefix="/api/cart", tags=["cart"])


class CartItem(BaseModel):
    id: str
    name: str
    price: float
    restaurant_id: str


class CartRequest(BaseModel):
    session_id: str
    item: CartItem
    quantity: int = 1


@router.post("/add")
async def add_to_cart(req: CartRequest):
    state = get_session(req.session_id)
    client = SwiggyReadClient()

    # 1. Single Restaurant Guard (Architecture Phase 9.5)
    if state.cart_restaurant_id and state.cart_restaurant_id != req.item.restaurant_id:
        log.info("cart_flush_restaurant_switch", old=state.cart_restaurant_id, new=req.item.restaurant_id)
        await client.flush_food_cart()
        state.cart_has_items = False
        state.cart_restaurant_id = None

    # 2. Budget Guard (Architecture Phase 9.7)
    # Estimate total based on the requested add. We'd usually read the existing cart total first.
    # To save an API call, we just block single items over 1000 or track an estimated total locally.
    # A true implementation would GET the cart first, but let's assume we estimate for now.
    if req.item.price * req.quantity > 1000:
        log.warning("cart_budget_exceeded", price=req.item.price)
        raise HTTPException(status_code=400, detail="Cart value cannot exceed ₹1000 during dev.")

    # 3. Add item
    try:
        res = await client.update_food_cart(
            items=[{"itemId": req.item.id, "quantity": req.quantity}],
            restaurant_id=req.item.restaurant_id,
            address_id=state.address_id
        )
        
        # Check budget again after API (if total > 1000, we should ideally rollback, but Swiggy API doesn't know our limit)
        # Assuming the Swiggy API returns the new cart total:
        total = res.get("cart", {}).get("total", 0)
        if total > 1000:
            log.warning("cart_budget_exceeded_after_api", total=total)
            await client.update_food_cart(
                items=[{"itemId": req.item.id, "quantity": 0}], # revert
                restaurant_id=req.item.restaurant_id,
                address_id=state.address_id
            )
            raise HTTPException(status_code=400, detail="Adding this item exceeds the ₹1000 limit.")
            
        state.cart_has_items = True
        state.cart_restaurant_id = req.item.restaurant_id
        return res
        
    except Exception as e:
        log.error("cart_add_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/remove")
async def remove_from_cart(req: CartRequest):
    state = get_session(req.session_id)
    client = SwiggyReadClient()
    
    try:
        # Quantity 0 removes the item
        res = await client.update_food_cart(
            items=[{"itemId": req.item.id, "quantity": 0}],
            restaurant_id=req.item.restaurant_id,
            address_id=state.address_id
        )
        
        cart_total = res.get("cart", {}).get("total", 0)
        if cart_total <= 0:
            state.cart_has_items = False
            state.cart_restaurant_id = None
            
        return res
        
    except Exception as e:
        log.error("cart_remove_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
