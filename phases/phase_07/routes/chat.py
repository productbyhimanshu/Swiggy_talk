"""Phase 7 — POST /api/chat SSE streaming."""

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat")
async def chat():
    raise NotImplementedError("Phase 7")
