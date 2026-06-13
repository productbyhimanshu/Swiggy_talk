"""Proactive opener — what Bhook says first.

Powered by long-term memory + clock + recent session state. The frontend
calls /api/opener when the chat is empty; Bhook responds with one of:

  • repeat-usual: "same Wow! Momo as last Tuesday?" (we have a habit)
  • time-aware:   "lunch time — what are we thinking?"  (clock cue, no habit yet)
  • welcome:      "tell me what you're craving" (first ever session)

Zero LLM calls — this should feel instant.
"""

from __future__ import annotations

from datetime import datetime

from phases.phase_00.services import memory as user_memory


def _greeting_for(hour: int) -> tuple[str, list[str]]:
    """Time-aware default when we don't have a habit yet."""
    if 5 <= hour < 11:
        return ("morning! what's for breakfast? ☀️",
                ["Coffee + something", "Healthy", "Surprise me"])
    if 11 <= hour < 15:
        return ("lunch time 🍱 what's the move?",
                ["Something quick", "Comfort food", "Healthy"])
    if 15 <= hour < 18:
        return ("snack o'clock 🍿 sweet or savoury?",
                ["Savoury", "Sweet", "Surprise me"])
    if 18 <= hour < 22:
        return ("dinner time 🍽️ what are we doing tonight?",
                ["Comfort food", "Try something new", "Surprise me"])
    return ("late night cravings? 🌙 i got you",
            ["Snacks", "Something filling", "Re-suggest"])


def build_opener(now: datetime | None = None) -> dict:
    """
    Return a single bubble {text, quick_replies} for the empty-chat screen.

    Never raises — memory failures fall back to the time-aware greeting.
    """
    now = now or datetime.now()

    try:
        usual = user_memory.suggest_usual(now=now)
    except Exception:
        usual = None

    if usual:
        items = usual.get("items") or []
        item_label = items[0].get("name") if items else None
        rest = usual.get("restaurant_name") or "your usual spot"
        if item_label:
            text = f"hey 👋 want the {item_label.lower()} from {rest} again?"
        else:
            text = f"hey 👋 same {rest} as usual?"
        return {
            "text": text,
            "quick_replies": ["Yes, same please", "Something else", "Surprise me"],
        }

    # No habit yet — time-aware default
    text, chips = _greeting_for(now.hour)
    return {"text": text, "quick_replies": chips}
