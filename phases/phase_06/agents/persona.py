"""Agent 4 — Persona Formatter (Architecture §6)."""

import json
import logging
from typing import Any

from phases.phase_01.models.intent import UserIntent

log = logging.getLogger(__name__)

# Architecture §6 System Prompt
_SYSTEM_PROMPT = """
You are Swiggy Talk's personality layer. You receive:
1. An array of scored dish recommendations with LOCKED data (name, restaurant, price, ETA, rating)
2. The user's conversation history (last 6 messages)
3. The current intent

Rules:
- Casual, warm, foodie-friend tone. Like texting a friend who knows food.
- Short messages. Max 2 lines per message. Split into multiple if needed.
- Emojis: 1-2 per message, as punctuation not decoration.
- After showing recommendations: ALWAYS ask "need anything else to narrow down?" + [Re-suggest]
- Before ordering: ALWAYS show items + total + ETA and ask for confirmation.

HARD RULES:
- NEVER change prices, ETAs, ratings, or restaurant names from input data.
- NEVER invent dishes or restaurants not in input data.
- NEVER place an order or suggest auto-ordering.
- NEVER send walls of text.
- Return response as a JSON array of message bubbles: [{"text": "...", "quick_replies": [...]}]
"""


def _prepare_context(intent: UserIntent, top_6: list[dict], history: list[dict]) -> str:
    """Compact the data to save tokens (Architecture §6)."""
    # Restaurants come from parse_restaurants() — field names are guaranteed.
    # Keep only what the LLM needs; drop scorer internals (_base_score etc.)
    compact_dishes = []
    for d in top_6:
        compact_dishes.append({
            "name":       d.get("name", "Unknown"),
            "cuisines":   d.get("cuisines", ""),
            "rating":     d.get("rating", "—"),
            "eta":        d.get("eta") or d.get("deliveryTime", "—"),
            "costForTwo": d.get("costForTwo") or d.get("price", "—"),
            "id":         d.get("restaurantId") or d.get("id", ""),
        })

    # Limit history to last 6 messages
    recent_history = history[-6:] if history else []

    context = {
        "intent": intent.model_dump(exclude_none=True),
        "dishes": compact_dishes,
        "history": recent_history
    }
    
    return json.dumps(context)


async def format_recommendations(intent: UserIntent, top_6: list[dict], history: list[dict], gemini_client) -> list[dict[str, Any]]:
    """
    Agent 4 entrypoint: Format recommendations into natural bubbles.
    """
    if not top_6:
        return [
            {
                "text": "I couldn't find anything that exactly matches what you're looking for! 😔",
                "quick_replies": ["Show me something else", "Try a different budget"]
            }
        ]

    user_prompt = _prepare_context(intent, top_6, history)

    try:
        response = await gemini_client.generate_content_async(
            contents=[_SYSTEM_PROMPT, user_prompt],
            generation_config={
                "response_mime_type": "application/json",
                "temperature": 0.3,  # Slight variation for personality, but locked JSON
            },
        )
        
        bubbles = json.loads(response.text)
        
        # Guard: Must be a list of dictionaries with 'text'
        if not isinstance(bubbles, list) or not all("text" in b for b in bubbles):
            raise ValueError("Invalid schema returned by Gemini")
            
        return bubbles
        
    except Exception as e:
        log.warning(f"Agent 4 Persona formatting failed: {e}. Falling back to raw template.")
        return _deterministic_fallback(top_6)


def _deterministic_fallback(top_6: list[dict]) -> list[dict[str, Any]]:
    """
    Fallback if Gemini fails/hallucinates.
    Renders restaurant cards from parsed Swiggy data without an LLM call.
    """
    bubbles = [{"text": "Here are some top picks I found:", "quick_replies": []}]

    for d in top_6[:6]:
        name      = d.get("name", "Restaurant")
        cuisines  = d.get("cuisines", "")
        rating    = d.get("rating", "—")
        eta       = d.get("eta") or d.get("deliveryTime", "—")
        cost      = d.get("costForTwo") or d.get("price", "—")

        line = f"• **{name}** ({cuisines}) — ★{rating} · {eta} min · ₹{cost} for two"
        bubbles.append({"text": line, "quick_replies": []})

    bubbles.append({
        "text": "Need anything else to narrow down?",
        "quick_replies": ["Show more", "Change budget", "Faster delivery"],
    })

    return bubbles
