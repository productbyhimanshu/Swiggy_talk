"""Stub handlers per route — full agents wire in later phases."""

from phases.phase_01.models.state import ConversationState
from phases.phase_02.orchestrator import Route


def _bubble(text: str, quick_replies: list[str] | None = None) -> dict:
    b: dict = {"text": text}
    if quick_replies:
        b["quick_replies"] = quick_replies
    return b


def handle_greeting(_message: str, _state: ConversationState) -> dict:
    return {
        "route": Route.GREETING.value,
        "bubbles": [_bubble("hey! what are you in the mood for today? 🍽️")],
        "agents": [],
    }


def handle_cancel(_message: str, _state: ConversationState) -> dict:
    return {
        "route": Route.CANCEL.value,
        "bubbles": [_bubble("cart cleared, starting fresh 🔄")],
        "agents": [],
    }


def handle_cart_action(message: str, _state: ConversationState) -> dict:
    return {
        "route": Route.CART_ACTION.value,
        "bubbles": [_bubble(f"got it — updating your cart for: {message.strip()[:80]}")],
        "agents": [],
    }


def handle_order(_message: str, _state: ConversationState) -> dict:
    return {
        "route": Route.ORDER.value,
        "bubbles": [_bubble("let me pull up your order summary...")],
        "agents": [],
        "requires_user_confirm": True,
    }


def handle_schedule(_message: str, _state: ConversationState) -> dict:
    return {
        "route": Route.SCHEDULE.value,
        "bubbles": [_bubble("got it — I'll work out the best time to place that order 🕐")],
        "agents": ["timing"],
    }


def handle_new_search(_message: str, _state: ConversationState) -> dict:
    return {
        "route": Route.NEW_SEARCH.value,
        "bubbles": [_bubble("on it — finding options for you...")],
        "agents": ["intent", "validate", "score", "persona"],
    }


def handle_clarify_reply(_message: str, _state: ConversationState) -> dict:
    return {
        "route": Route.CLARIFY_REPLY.value,
        "bubbles": [_bubble("thanks — narrowing it down with that 👍")],
        "agents": ["validate", "score", "persona"],
    }


def handle_refine(_message: str, _state: ConversationState) -> dict:
    return {
        "route": Route.REFINE.value,
        "bubbles": [_bubble("re-scoring with your preferences...")],
        "agents": ["score", "persona"],
    }


def handle_in_restaurant(_message: str, _state: ConversationState) -> dict:
    return {
        "route": Route.IN_RESTAURANT.value,
        "bubbles": [_bubble("searching that restaurant's menu...")],
        "agents": ["score", "persona"],
    }


HANDLERS = {
    Route.GREETING: handle_greeting,
    Route.CANCEL: handle_cancel,
    Route.CART_ACTION: handle_cart_action,
    Route.ORDER: handle_order,
    Route.SCHEDULE: handle_schedule,
    Route.NEW_SEARCH: handle_new_search,
    Route.CLARIFY_REPLY: handle_clarify_reply,
    Route.REFINE: handle_refine,
    Route.IN_RESTAURANT: handle_in_restaurant,
}
