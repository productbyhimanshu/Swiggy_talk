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
        # Refinement chips and natural phrases that modify the existing search:
        # speed/price/health/diet/cuisine swap. Important: "pure veg only",
        # "non-veg only", "fastest delivery" must NOT route to NEW_SEARCH
        # because that drops the original query keyword (momos/biryani/etc).
        r"\b("
        r"faster|fastest|cheaper|healthier|more protein|less spicy|spicier|milder|"
        r"different|instead|re-?suggest|better options|something else|show me|"
        r"pure veg|veg only|veg-only|nonveg only|non-?veg only|"
        r"under \d+|below \d+|less than \d+|"
        r"fast delivery|quick delivery|highest rated|top rated|cheapest"
        r")\b",
    ),
    (
        "in_restaurant",
        r"\b(same restaurant|same place|also add from|search .+ in|from same|from there|from here|more from|what else)\b",
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
    if route == Route.IN_RESTAURANT and not (state.current_restaurant_id or state.cart_restaurant_id or state.cart_has_items):
        return False
    return True


# Common food / cuisine keywords — when one of these appears in the message
# alongside a refine/schedule trigger, prefer NEW_SEARCH so the food query
# isn't lost (e.g. "butter chicken under 300" must not route to REFINE if the
# prior recommendation was for momos; "lunch momos at 1pm" must run a real
# search before offering to schedule).
_FOOD_HINT_RE = re.compile(
    r"\b(pizza|momo|momos|biryani|burger|burgers|dosa|idli|vada|paneer|chicken|"
    r"noodle|noodles|sandwich|pasta|sushi|cake|donut|kebab|thali|roll|rolls|wrap|"
    r"samosa|tikka|shawarma|falafel|taco|chowmein|manchurian|fried rice|naan|"
    r"roti|paratha|chaap|bhel|pani puri|dahi puri|ice cream|shake|lassi|coffee|"
    r"tea|waffle|pancake|salad|soup|food|meal|dinner|lunch|breakfast|brunch|"
    r"butter chicken|fish|prawn|mutton|veg|nonveg|non-veg|cuisine|spicy|sweet)\b",
    re.IGNORECASE,
)


def classify_regex(message: str, state: ConversationState) -> Route | None:
    """Return a concrete route if regex + guards match; None if no regex hit."""
    msg = message.strip()
    if not msg:
        return None

    has_food = bool(_FOOD_HINT_RE.search(msg))

    for name, pattern in PATTERN_ORDER:
        if re.search(pattern, msg, re.IGNORECASE):
            route = _ROUTE_BY_NAME[name]
            # If the message names a dish/cuisine/meal, REFINE and SCHEDULE
            # are too narrow — the user wants a fresh food search that may
            # *also* be timed. NEW_SEARCH then attaches a schedule proposal
            # at the end when intent.timing is present.
            if has_food and route in (Route.REFINE, Route.SCHEDULE):
                return Route.NEW_SEARCH
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
