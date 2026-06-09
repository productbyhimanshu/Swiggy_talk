"""Phase 11 — POST /api/schedule endpoint (architecture §11).

Rules:
  - confirmed=True is REQUIRED; 400 otherwise.
  - order_now path: fires immediately (still blocked by order guard in Phase 11).
  - Scheduled path: stores job in memory; APScheduler would fire at fire_at in production.
  - DELETE /api/schedule/{job_id} cancels the job (user cancel).
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from phases.phase_11.services.scheduler import (
    cancel_job,
    create_job,
    execute_scheduled_order,
    get_job,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["schedule"])


# ── Request / response models ──────────────────────────────────────────────────

class ScheduleRequest(BaseModel):
    session_id: str
    confirmed: bool = False
    delivery_target: datetime          # ISO-8601, e.g. "2026-06-10T13:00:00"
    eta_str: str = "30 mins"           # from Swiggy restaurant result
    restaurant_id: str | None = None


class CancelRequest(BaseModel):
    session_id: str


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/schedule")
async def schedule_order(req: ScheduleRequest) -> dict:
    """
    Create a scheduled order job.

    Returns timing metadata so the frontend can show the user when their
    order will be placed. If order_now=True the execute path is attempted
    immediately (still blocked by order guard in Phase 11).
    """
    if not req.confirmed:
        raise HTTPException(status_code=400, detail="User must confirm schedule (confirmed=true)")

    try:
        job_info = create_job(
            session_id=req.session_id,
            delivery_target=req.delivery_target,
            eta_str=req.eta_str,
            restaurant_id=req.restaurant_id,
        )
    except Exception as exc:
        log.error("schedule_order: create_job failed err=%s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # If fire_at is already in the past / within threshold → attempt immediately
    if job_info["order_now"]:
        result = execute_scheduled_order(job_info["job_id"])
        return {**job_info, "immediate_result": result}

    warn_msg = None
    if job_info["warn_far_ahead"]:
        warn_msg = (
            f"Heads up — that's more than 4 hours away! "
            f"I'll fire the order at {job_info['fire_at']}."
        )

    return {
        **job_info,
        "status": "scheduled",
        "warn": warn_msg,
    }


@router.delete("/schedule/{job_id}")
async def cancel_schedule(job_id: str, req: CancelRequest) -> dict:
    """
    Cancel a pending scheduled job.

    Returns ok=True even if already cancelled (idempotent).
    Frontend should call /api/cart/flush separately if it wants to clear the cart.
    """
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")

    if job.session_id != req.session_id:
        raise HTTPException(status_code=403, detail="Job does not belong to this session")

    result = cancel_job(job_id)
    log.info("cancel_schedule: job_id=%s session=%s", job_id, req.session_id)
    return result
