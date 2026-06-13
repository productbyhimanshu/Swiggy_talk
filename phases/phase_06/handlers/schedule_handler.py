"""SCHEDULE route handler — wires chat conversation to the phase_11 timing engine.

Flow (architecture §12):
  1. User: "deliver lunch by 1 pm" → intent.timing = "13:00"
  2. Propose: compute fire time, show confirmation bubble + [Confirm schedule] chip
     (proposal stored in state.scheduled_order — nothing scheduled yet)
  3. User taps "Confirm schedule" → create_job() registers the job
  4. Order firing remains blocked by the order guard until Phase 13 sign-off.

User cancel at any point → CANCEL route clears state.scheduled_order.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from phases.phase_01.models.intent import UserIntent
from phases.phase_01.models.state import ConversationState
from phases.phase_11.services.scheduler import calculate_order_time, create_job

_CONFIRM_RE = re.compile(r"\b(confirm|lock|yes|yep|do it|go ahead)\b", re.IGNORECASE)


def _parse_target_time(timing: str, now: datetime | None = None) -> datetime | None:
    """'13:00' → next occurrence of 13:00 (today, or tomorrow if already past)."""
    now = now or datetime.now()
    m = re.match(r"^(\d{1,2}):(\d{2})$", timing.strip())
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def _eta_for_state(state: ConversationState) -> str:
    """Best available ETA string: cart restaurant → first cached result → default."""
    rest_id = state.cart_restaurant_id or state.current_restaurant_id
    for r in state.cached_results:
        if rest_id and str(r.get("restaurantId") or r.get("id")) == str(rest_id):
            return r.get("deliveryTime") or f"{r.get('eta', 30)} mins"
    if state.cached_results:
        first = state.cached_results[0]
        return first.get("deliveryTime") or f"{first.get('eta', 30)} mins"
    return "30 mins"


def handle_schedule(
    message: str,
    intent: UserIntent,
    state: ConversationState,
) -> list[dict[str, Any]]:
    """Handle the SCHEDULE route. Pure local logic — zero LLM, zero Swiggy calls."""

    proposal = state.scheduled_order

    # ── Step 3: user confirms a pending proposal ──────────────────────────────
    if proposal and proposal.get("status") == "proposed" and _CONFIRM_RE.search(message):
        job_info = create_job(
            session_id=state.session_id,
            delivery_target=datetime.fromisoformat(proposal["delivery_target"]),
            eta_str=proposal["eta_str"],
            restaurant_id=proposal.get("restaurant_id"),
        )
        state.scheduled_order = {**proposal, "status": "confirmed", "job_id": job_info["job_id"]}
        fire_at = datetime.fromisoformat(job_info["fire_at"]).strftime("%I:%M %p").lstrip("0")
        target = datetime.fromisoformat(proposal["delivery_target"]).strftime("%I:%M %p").lstrip("0")
        return [
            {
                "text": f"Locked in! 🔒 I'll place the order at {fire_at} so it lands by {target}.",
                "quick_replies": [],
            },
            {
                "text": "I'll double-check the restaurant is open before firing. Say \"cancel\" anytime to call it off.",
                "quick_replies": ["Cancel schedule", "Order now instead"],
            },
        ]

    # ── Step 2: build a new proposal from intent.timing ───────────────────────
    timing = intent.timing
    if not timing:
        return [
            {
                "text": "What time do you want it delivered? ⏰",
                "quick_replies": ["1:00 PM", "8:00 PM", "In an hour"],
            }
        ]

    delivery_target = _parse_target_time(timing)
    if delivery_target is None:
        return [
            {
                "text": "Hmm, I couldn't read that time — try something like \"1:30 PM\" or \"20:00\"?",
                "quick_replies": [],
            }
        ]

    eta_str = _eta_for_state(state)
    timing_info = calculate_order_time(delivery_target, eta_str)

    if timing_info["order_now"]:
        return [
            {
                "text": "That window's already tight — better to order right now! ⚡",
                "quick_replies": ["Order now", "Pick a later time"],
            }
        ]

    state.scheduled_order = {
        "status": "proposed",
        "delivery_target": delivery_target.isoformat(),
        "eta_str": eta_str,
        "restaurant_id": state.cart_restaurant_id or state.current_restaurant_id,
    }

    fire_at = timing_info["fire_at"].strftime("%I:%M %p").lstrip("0")
    target_fmt = delivery_target.strftime("%I:%M %p").lstrip("0")
    bubbles = [
        {
            "text": f"Got it — {target_fmt} delivery 🕐 I'd place the order at {fire_at} "
                    f"(ETA {timing_info['eta_minutes']} min + 5 min buffer).",
            "quick_replies": [],
        },
        {
            "text": "Lock this in?",
            "quick_replies": ["Confirm schedule", "Change time", "Order now instead"],
        },
    ]
    if timing_info["warn_far_ahead"]:
        bubbles.insert(1, {
            "text": "Heads up: that's quite far out — ETAs might change, so I'll re-check closer to the time. ⚠️",
            "quick_replies": [],
        })
    return bubbles


def propose_schedule_after_search(
    intent: UserIntent,
    state: ConversationState,
) -> list[dict[str, Any]]:
    """
    Compose a schedule-proposal bubble to append AFTER NEW_SEARCH results when
    intent.timing was supplied alongside the food query ("momos under 200 and 10am").

    Stores the proposal in state.scheduled_order so the next user turn that
    confirms ("Confirm schedule", "yes", "lock it in") completes the booking
    via handle_schedule's confirmation branch.

    Returns [] if timing is missing / unparseable / already-past — caller
    skips appending and the user just sees results.
    """
    if not intent.timing:
        return []

    delivery_target = _parse_target_time(intent.timing)
    if delivery_target is None:
        return []

    eta_str = _eta_for_state(state)
    timing_info = calculate_order_time(delivery_target, eta_str)

    if timing_info["order_now"]:
        # The deadline is already too close to schedule meaningfully — make
        # sure no half-baked proposal lingers in session state, otherwise the
        # next turn's classifier could route back into schedule confirm/cancel.
        state.scheduled_order = None
        return [{
            "text": "That window's already tight — better to order right now! ⚡",
            "quick_replies": ["Order now", "Pick a later time"],
        }]

    state.scheduled_order = {
        "status": "proposed",
        "delivery_target": delivery_target.isoformat(),
        "eta_str": eta_str,
        "restaurant_id": state.cart_restaurant_id or state.current_restaurant_id,
    }

    fire_at = timing_info["fire_at"].strftime("%I:%M %p").lstrip("0")
    target_fmt = delivery_target.strftime("%I:%M %p").lstrip("0")
    return [{
        "text": f"Want me to time the order so it arrives by {target_fmt}? "
                f"I'd fire it at {fire_at}.",
        "quick_replies": ["Yes, schedule it", "No, order now"],
    }]
