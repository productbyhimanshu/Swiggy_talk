"""Phase 10 — full error fallback chain (architecture §14).

Fallback chain order (each step only runs if the prior step fails):
  1. Swiggy 5xx            → 3× retry (via SwiggyReadClient backoff)
  2. All retries exhausted → return swiggy_down template
  3. Gemini classify fail  → fallback to NEW_SEARCH route
  4. Agent 1 (intent) fail → use empty UserIntent()
  5. Agent 3 (scorer) fail → sort by rating, return raw results
  6. Agent 4 (persona) fail→ deterministic plain-text fallback (see persona.py)
  7. Restaurant closed     → re-search + notify user
  8. Unrecognised route    → treat as NEW_SEARCH

Each function here returns a fallback value that the orchestrator can
substitute in place of the failed component.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


# ── 1. Swiggy down ────────────────────────────────────────────────────────────

def swiggy_down_bubbles() -> list[dict]:
    """
    Return a user-facing bubble list for when Swiggy API is unreachable.
    Triggered after 3 retries are exhausted (SwiggyUnavailableError).
    """
    return [
        {
            "type": "bubble",
            "text": "Swiggy seems to be having a moment 😅 — couldn't reach their servers.",
            "quick_replies": [],
        },
        {
            "type": "bubble",
            "text": "Try again in a minute? I'll be here!",
            "quick_replies": ["Try again"],
        },
    ]


# ── 2. Gemini classify failure ────────────────────────────────────────────────

def fallback_route() -> str:
    """
    If Gemini classify fails / times out, default to NEW_SEARCH.
    architecture §14: unclassified → NEW_SEARCH.
    """
    log.warning("fallback_route_used reason=gemini_classify_failed")
    return "NEW_SEARCH"


# ── 3. Agent 1 (intent parser) failure ───────────────────────────────────────

def fallback_intent() -> dict:
    """
    Return an empty intent dict when Agent 1 fails after 3 attempts.
    The pipeline will proceed with no structured intent (graceful degradation).
    """
    log.warning("fallback_intent_used reason=agent1_failed")
    return {}


# ── 4. Agent 3 (scorer) failure ───────────────────────────────────────────────

def fallback_sort_by_rating(restaurants: list[dict]) -> list[dict]:
    """
    Sort restaurants by rating descending when Agent 3 (scorer) fails.
    Returns up to 6 results — architecture §14 fallback for scorer exception.
    """
    log.warning("fallback_sort_used reason=agent3_failed count=%d", len(restaurants))
    try:
        sorted_results = sorted(
            restaurants,
            key=lambda r: float(r.get("rating", 0) or 0),
            reverse=True,
        )
        return sorted_results[:6]
    except Exception as exc:
        log.error("fallback_sort_failed error=%s", exc)
        return restaurants[:6]


# ── 5. Restaurant closed between search and cart ──────────────────────────────

def restaurant_closed_bubbles(restaurant_name: str = "that restaurant") -> list[dict]:
    """
    Bubble set to show when a restaurant goes closed between search and cart add.
    Caller should then trigger a re-search.
    """
    return [
        {
            "type": "bubble",
            "text": f"Ah, looks like {restaurant_name} just closed 😬",
            "quick_replies": [],
        },
        {
            "type": "bubble",
            "text": "Let me find you something else that's open right now!",
            "quick_replies": ["Find alternatives"],
        },
    ]


# ── 6. Online-payment coupon filtered ────────────────────────────────────────

def cod_only_warning_bubble() -> dict:
    """Single bubble shown when all fetched coupons are online-payment only."""
    return {
        "type": "bubble",
        "text": "No COD-compatible coupons available right now 🎟️",
        "quick_replies": [],
    }


# ── 7. Full chain helper ──────────────────────────────────────────────────────

def apply_fallback_chain(
    error: Exception,
    context: dict[str, Any],
) -> list[dict]:
    """
    Top-level fallback dispatcher.

    Given an exception and context dict, returns the appropriate bubble list.
    Context keys used:
        - "stage": one of "swiggy", "classify", "intent", "scorer", "persona"
        - "restaurants": raw list (for scorer fallback)
        - "restaurant_name": str (for closed fallback)

    Used by the orchestrator's outer try/except to produce user-facing output
    without crashing.
    """
    stage = context.get("stage", "unknown")
    log.error(
        "fallback_chain_triggered stage=%s error_type=%s error=%s",
        stage, type(error).__name__, error,
    )

    if stage == "swiggy":
        return swiggy_down_bubbles()

    if stage == "closed":
        return restaurant_closed_bubbles(context.get("restaurant_name", "that restaurant"))

    if stage in ("classify", "intent", "scorer", "persona", "unknown"):
        # Generic fallback — ask user to retry
        return [
            {
                "type": "bubble",
                "text": "Something went sideways on my end 😅 — can you say that again?",
                "quick_replies": ["Try again"],
            }
        ]

    return swiggy_down_bubbles()
