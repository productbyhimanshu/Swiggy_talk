"""Phase 9 — cart add/remove API routes."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/cart", tags=["cart"])


@router.post("/add")
async def cart_add():
    raise NotImplementedError("Phase 9")


@router.post("/remove")
async def cart_remove():
    raise NotImplementedError("Phase 9")
