"""Static templates for fast-path routes (Architecture §6)."""

from typing import Any


def get_cart_template(cart_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a static bubble array for a cart action."""
    # Assuming cart_data contains 'total' or similar. 
    # For now, we return a simple static message to avoid Gemini overhead.
    total = cart_data.get("cart_total", "the current total")
    return [
        {
            "text": f"Added to cart! Current total is ₹{total}.",
            "quick_replies": ["Checkout", "Add more from this place", "Start over"]
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
