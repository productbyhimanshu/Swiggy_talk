"""Static templates for fast-path routes (Architecture §6)."""

from typing import Any


def get_cart_template() -> list[dict[str, Any]]:
    """Return a static bubble array for a cart action."""
    return [
        {
            "text": "Added! ✓",
            "quick_replies": ["More from here", "Checkout", "Start over"]
        }
    ]


def get_in_restaurant_template() -> list[dict[str, Any]]:
    """Fallback when restaurant menu is empty or unavailable."""
    return [
        {
            "text": "Couldn't load the full menu right now — try searching for something specific!",
            "quick_replies": ["Search again", "Different restaurant"]
        }
    ]


def get_cancel_template() -> list[dict[str, Any]]:
    """Return a static bubble array for cancel/clear actions."""
    return [
        {
            "text": "No worries, wiped the slate clean! What are you in the mood for instead?",
            "quick_replies": ["Show me something fast", "Healthy options", "I have a budget of ₹300"]
        }
    ]


def get_stale_template() -> list[dict[str, Any]]:
    """Return a static bubble array for stale sessions or timeouts."""
    return [
        {
            "text": "Oops, looks like this session timed out. Let's start fresh!",
            "quick_replies": ["Order food", "What's nearby?"]
        }
    ]


def get_greeting_template() -> list[dict[str, Any]]:
    """Return a static bubble array for greetings / small talk."""
    return [
        {
            "text": "Hey! 👋 I'm Bhook — your food buddy. What are you craving today?",
            "quick_replies": ["🍕 Pizza", "🍱 Biryani", "🍔 Burgers", "Surprise me!"]
        }
    ]


def get_swiggy_down_template() -> list[dict[str, Any]]:
    """Return a static bubble array for Swiggy API errors."""
    return [
        {
            "text": "Uh oh, the Swiggy API seems to be taking a nap right now. 💤",
            "quick_replies": ["Try again"]
        }
    ]
