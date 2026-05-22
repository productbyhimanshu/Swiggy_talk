"""Dev/test endpoint — classify a message through the orchestrator."""

from pydantic import BaseModel, Field

from fastapi import APIRouter, HTTPException

from phases.phase_01.services.session import get_session
from phases.phase_02.pipeline import run_pipeline

router = APIRouter(prefix="/api", tags=["orchestrator"])


class ClassifyRequest(BaseModel):
    session_id: str
    message: str = Field(min_length=0)


@router.post("/classify")
async def classify_message_endpoint(body: ClassifyRequest):
    """Run orchestrator classify + stub pipeline (no SSE yet)."""
    state = get_session(body.session_id, touch=True)
    try:
        result = await run_pipeline(body.message, state)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "session_id": body.session_id,
        **result,
    }
