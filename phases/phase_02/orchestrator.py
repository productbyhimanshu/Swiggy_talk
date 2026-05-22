"""Hybrid message classifier — regex first, Gemini for ambiguous (architecture §5)."""

from __future__ import annotations

import re
from enum import Enum

from phases.phase_01.models.state import ConversationState

# Iteration order matters: first match wins
PATTERN_ORDER: list[tuple[str, str]] = [
    (
        "greeting",
        r"^(hi|hey|hello|sup|yo|good morning|thanks|thank you|bye|ok|cool|nice)(\s+\w+)?\s*[!.?]*$",
    ),
    ("cancel", r"\b(cancel|stop|nevermind|forget it|scratch that|nvm|start over|clear cart)\b"),
    ("order", r"\b(order it|place order|checkout|confirm order|buy it|proceed|place it)\b"),
    ("cart_action", r"\b(add|remove|delete|drop|take out|minus|plus|increase|decrease|qty|quantity)\b"),
    (
        "refine",
        r"\b(faster|cheaper|healthier|more protein|less spicy|different|instead|re-?suggest|better options|something else|show me)\b",
    ),
    (
        "in_restaurant",
        r"\b(same restaurant|same place|also add from|search .+ in|from same|from there|what else)\b",
    ),
    (
        "schedule",
        r"\b(at \d{1,2}|by \d{1,2}|before \d{1,2}|lunch at|dinner at|breakfast at|schedule|deliver by)\b",
    ),
]


class Route(str, Enum):
    NEW_SEARCH = "new_search"
    CLARIFY_REPLY = "clarify_reply"
    REFINE = "refine"
    CART_ACTION = "cart_action"
    IN_RESTAURANT = "in_restaurant"
    ORDER = "order"
    SCHEDULE = "schedule"
    GREETING = "greeting"
    CANCEL = "cancel"
    AMBIGUOUS = "ambiguous"


_ROUTE_BY_NAME = {r.value: r for r in Route}


def _passes_context_guard(route: Route, state: ConversationState) -> bool:
    if route == Route.ORDER and not state.cart_has_items:
        return False
    if route == Route.REFINE and not state.has_recommendations:
        return False
    if route == Route.IN_RESTAURANT and not state.current_restaurant_id:
        return False
    return True


def classify_regex(message: str, state: ConversationState) -> Route | None:
    """Return a concrete route if regex + guards match; None if no regex hit."""
    msg = message.strip()
    if not msg:
        return None

    for name, pattern in PATTERN_ORDER:
        if re.search(pattern, msg, re.IGNORECASE):
            route = _ROUTE_BY_NAME[name]
            if _passes_context_guard(route, state):
                return route
    return None


def classify(message: str, state: ConversationState) -> Route:
    """
    Synchronous classify — clarify → regex → ambiguous/new_search.
    Call classify_message() to also run Gemini on ambiguous inputs.
    """
    if state.awaiting_clarification:
        return Route.CLARIFY_REPLY

    matched = classify_regex(message, state)
    if matched is not None:
        return matched

    msg = message.strip()
    if _needs_gemini(msg):
        return Route.AMBIGUOUS
    return Route.NEW_SEARCH


def _needs_gemini(msg: str) -> bool:
    """
    Long conversational messages need Gemini; short food-like queries are new_search.
    Architecture: len > 5 → ambiguous, except brief search phrases (e.g. 'biryani').
    """
    if len(msg) <= 5:
        return False
    words = msg.split()
    if len(words) <= 4 and len(msg) <= 48:
        return False
    return True
