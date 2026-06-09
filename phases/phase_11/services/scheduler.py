"""Phase 11 — APScheduler timing engine (architecture §11).

Responsibilities:
  - calculate_order_time(): decide when to fire the order job given delivery target + ETA
  - pre_order_check(): validate restaurant is still OPEN + ETA hasn't spiked before firing
  - execute_scheduled_order(): calls stubbed place_food_order (blocked by OrderDisabledError)
  - cancel_job(): remove a pending job and optionally flush the cart
  - In-memory job registry (APScheduler BackgroundScheduler)

Safety:
  - place_food_order is NEVER called directly — routed through assert_orders_enabled()
    which raises OrderDisabledError while ORDER_ENABLED=false (Phase 12 gate)
  - Orders are ONLY placed when triggered by a user-confirmed scheduled job
  - No auto-ordering under any circumstances

Timing formula (architecture §11):
  order_time = delivery_target - eta_minutes - ORDER_BUFFER_MINUTES (default 5)
  warn_threshold = 4 hours ahead
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from phases.phase_00.services.order_guard import OrderDisabledError, assert_orders_enabled
from phases.phase_04.utils.parse_eta import parse_eta

log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────
ORDER_BUFFER_MINUTES = 5       # extra buffer beyond ETA
WARN_AHEAD_HOURS = 4           # warn user if scheduling >4h ahead
ORDER_NOW_THRESHOLD_MINUTES = 2  # if calculated fire_time is ≤ this far away → order_now


# ── Job registry (in-memory, no DB dependency) ─────────────────────────────────

@dataclass
class ScheduledJob:
    job_id: str
    session_id: str
    delivery_target: datetime
    eta_minutes: int
    fire_at: datetime
    restaurant_id: str | None = None
    cancelled: bool = False
    fired: bool = False
    result: dict | None = None


_jobs: dict[str, ScheduledJob] = {}  # job_id → ScheduledJob


def _make_job_id(session_id: str) -> str:
    ts = datetime.now().strftime("%Y%m%d%H%M%S%f")
    return f"job_{session_id}_{ts}"


# ── Core timing logic ──────────────────────────────────────────────────────────

def calculate_order_time(
    delivery_target: datetime,
    eta_str: str,
    *,
    buffer_minutes: int = ORDER_BUFFER_MINUTES,
    now: datetime | None = None,
) -> dict:
    """
    Compute when to fire the order job.

    Args:
        delivery_target: When the user wants food delivered (e.g. 13:00).
        eta_str:         Swiggy deliveryTime string e.g. "25-30 mins".
        buffer_minutes:  Extra safety buffer (default 5 min).
        now:             Injectable current time (for testing).

    Returns dict with:
        fire_at (datetime):     When to fire the order job.
        eta_minutes (int):      Parsed worst-case ETA.
        order_now (bool):       True if fire_at is already past / too close.
        warn_far_ahead (bool):  True if delivery_target is >4h from now.
        minutes_until_fire (float): Seconds from now until fire_at.
    """
    now = now or datetime.now()
    eta_minutes = parse_eta(eta_str)
    lead_time = timedelta(minutes=eta_minutes + buffer_minutes)
    fire_at = delivery_target - lead_time

    minutes_until_fire = (fire_at - now).total_seconds() / 60
    order_now = minutes_until_fire <= ORDER_NOW_THRESHOLD_MINUTES
    warn_far_ahead = (delivery_target - now) > timedelta(hours=WARN_AHEAD_HOURS)

    log.info(
        "calculate_order_time target=%s eta=%d buffer=%d fire_at=%s order_now=%s warn=%s",
        delivery_target.isoformat(), eta_minutes, buffer_minutes,
        fire_at.isoformat(), order_now, warn_far_ahead,
    )

    return {
        "fire_at": fire_at,
        "eta_minutes": eta_minutes,
        "order_now": order_now,
        "warn_far_ahead": warn_far_ahead,
        "minutes_until_fire": round(minutes_until_fire, 1),
    }


# ── Pre-order check ────────────────────────────────────────────────────────────

def pre_order_check(
    job: ScheduledJob,
    current_eta_str: str,
    restaurant_open: bool,
    cart_has_items: bool,
) -> dict:
    """
    Validate conditions immediately before firing the order.

    Called by execute_scheduled_order() — if any check fails the job is
    cancelled and a user-facing reason is returned.

    Returns:
        {"ok": True} on success.
        {"ok": False, "reason": str, "cancel": True} on failure.
    """
    if not restaurant_open:
        log.warning("pre_order_check: restaurant closed job=%s", job.job_id)
        return {"ok": False, "reason": "restaurant_closed", "cancel": True}

    if not cart_has_items:
        log.warning("pre_order_check: cart empty job=%s", job.job_id)
        return {"ok": False, "reason": "cart_empty", "cancel": True}

    current_eta = parse_eta(current_eta_str)
    # If ETA has spiked beyond delivery_target window, cancel
    cushion = timedelta(minutes=current_eta + ORDER_BUFFER_MINUTES)
    would_arrive_at = datetime.now() + cushion
    if would_arrive_at > job.delivery_target + timedelta(minutes=10):
        log.warning(
            "pre_order_check: ETA spike job=%s current_eta=%d",
            job.job_id, current_eta,
        )
        return {
            "ok": False,
            "reason": "eta_spike",
            "new_eta_minutes": current_eta,
            "cancel": True,
        }

    return {"ok": True}


# ── Execute (stubbed — place_food_order blocked) ──────────────────────────────

def execute_scheduled_order(job_id: str) -> dict:
    """
    Fire a scheduled order job.

    Phase 11: place_food_order is STUBBED — assert_orders_enabled() will raise
    OrderDisabledError while ORDER_ENABLED=false. This is intentional and tested.

    Phase 13 will wire the real endpoint here once the eval gate passes.
    """
    job = _jobs.get(job_id)
    if job is None:
        log.error("execute_scheduled_order: unknown job_id=%s", job_id)
        return {"ok": False, "reason": "job_not_found"}

    if job.cancelled:
        log.info("execute_scheduled_order: job already cancelled job=%s", job_id)
        return {"ok": False, "reason": "job_cancelled"}

    if job.fired:
        log.info("execute_scheduled_order: job already fired job=%s", job_id)
        return {"ok": False, "reason": "already_fired"}

    try:
        # SAFETY GATE — raises OrderDisabledError until Phase 12 gate passes
        assert_orders_enabled()
        # Phase 13 only: real place_food_order would go here
        # result = swiggy_client.place_food_order(...)
        job.fired = True
        job.result = {"placed": True}
        log.info("execute_scheduled_order: fired job=%s", job_id)
        return {"ok": True, "result": job.result}

    except OrderDisabledError as exc:
        log.info("execute_scheduled_order: blocked by order guard job=%s err=%s", job_id, exc)
        return {"ok": False, "reason": "order_disabled", "detail": str(exc)}

    except Exception as exc:
        log.error("execute_scheduled_order: unexpected error job=%s err=%s", job_id, exc)
        job.result = {"error": str(exc)}
        return {"ok": False, "reason": "unexpected_error", "detail": str(exc)}


# ── Public job API ─────────────────────────────────────────────────────────────

def create_job(
    session_id: str,
    delivery_target: datetime,
    eta_str: str,
    restaurant_id: str | None = None,
    *,
    now: datetime | None = None,
) -> dict:
    """
    Register a new scheduled order job.

    Returns the job dict including job_id, fire_at, and timing metadata.
    """
    timing = calculate_order_time(delivery_target, eta_str, now=now)
    job_id = _make_job_id(session_id)

    job = ScheduledJob(
        job_id=job_id,
        session_id=session_id,
        delivery_target=delivery_target,
        eta_minutes=timing["eta_minutes"],
        fire_at=timing["fire_at"],
        restaurant_id=restaurant_id,
    )
    _jobs[job_id] = job

    log.info(
        "create_job: job_id=%s session=%s fire_at=%s order_now=%s",
        job_id, session_id, timing["fire_at"].isoformat(), timing["order_now"],
    )
    return {
        "job_id": job_id,
        "fire_at": timing["fire_at"].isoformat(),
        "eta_minutes": timing["eta_minutes"],
        "order_now": timing["order_now"],
        "warn_far_ahead": timing["warn_far_ahead"],
        "minutes_until_fire": timing["minutes_until_fire"],
    }


def cancel_job(job_id: str) -> dict:
    """
    Cancel a pending job. Returns ok=True even if already cancelled (idempotent).
    Caller is responsible for flushing the cart if UX requires it.
    """
    job = _jobs.get(job_id)
    if job is None:
        return {"ok": False, "reason": "job_not_found"}
    if job.fired:
        return {"ok": False, "reason": "already_fired"}

    job.cancelled = True
    log.info("cancel_job: job_id=%s", job_id)
    return {"ok": True, "job_id": job_id}


def get_job(job_id: str) -> ScheduledJob | None:
    """Return the ScheduledJob or None."""
    return _jobs.get(job_id)


def clear_all_jobs() -> None:
    """Clear the in-memory job registry (test helper)."""
    _jobs.clear()
