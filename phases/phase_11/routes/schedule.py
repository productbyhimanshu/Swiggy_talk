"""Phase 11 — POST /api/schedule."""

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["schedule"])


@router.post("/schedule")
async def schedule_order():
    raise NotImplementedError("Phase 11")
