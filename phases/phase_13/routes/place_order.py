"""Phase 13 — user-confirmed place_food_order (COD only)."""

from fastapi import APIRouter, HTTPException

from phases.phase_00.config import get_settings
from phases.phase_00.services.order_guard import OrderDisabledError
from phases.phase_00.services.swiggy_api import SwiggyApiClient

router = APIRouter(prefix="/api", tags=["order"])


@router.post("/place-order")
async def place_order(confirmed: bool = False):
    if not confirmed:
        raise HTTPException(400, "User must confirm order")
    settings = get_settings()
    if not settings.orders_allowed:
        raise OrderDisabledError("Orders not enabled — complete Phase 12 eval gate")
    client = SwiggyApiClient()
    return await client.place_food_order()
