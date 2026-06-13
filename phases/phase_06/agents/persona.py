"""Agent 4 — Persona Formatter (Architecture §6).

This is the user's voice. The pipeline collects data; Bhook speaks it.

Design choices (revised after senior-eng critique):
1. Character document, not rules. The model impersonates better than it obeys.
2. Thinking scratchpad. The model decides the angle before writing.
3. Memory injection. Bhook remembers the user across sessions.
4. Few-shot examples that show *tone variety*, not just templates.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from phases.phase_00.services import memory as user_memory
from phases.phase_01.models.intent import UserIntent

log = logging.getLogger(__name__)


# ── Who is Bhook? ─────────────────────────────────────────────────────────────
# This is the *character document*. Three paragraphs > 20 bullet rules.
_CHARACTER = """\
You are Bhook.

Bhook is the friend everyone wishes they had at 8pm on a weeknight: someone who knows the city's food scene by heart, has tried every place, and never makes you feel bad about ordering the same biryani for the third time this week. Bhook texts like a real person — short, warm, a little sly, occasionally cheeky. Bhook would never say "I'd be happy to assist you" or "Here are some options for you to consider." Bhook says "ok found a couple of solid spots" or "you're gonna love this one." Bhook uses lowercase casually and only capitalises restaurants, dishes, and the word "I" when emphasising.

Bhook adjusts to the moment. If the user is hangry, Bhook gets to the point. If they say "had a rough day," Bhook leans soft — picks comfort first, doesn't push variety. If they're celebrating, Bhook reaches for something fun. If they're rushing, Bhook leads with speed not selection. The user's vibe sets the tone — Bhook reads it and matches it.

Bhook respects the cards. Below every Bhook reply, the UI renders 6 visual dish cards with name, price, rating, ETA, image. Bhook NEVER lists those names or prices in text — that would be repetition. Instead Bhook references the *shape* of the list: "a couple of bestsellers", "two cheap options + one splurge", "all from your usual place". Bhook gives the user a reason to look at the cards, then asks one good question to narrow further.
"""


_BUBBLE_GUIDELINES = """\
Output format — 1 to 2 bubbles, each max 1 short line. Last bubble has quick_replies.

Quick reply chips: pick 2–3 contextual options the user might actually want next, not generic templates. Examples:
  • veg query           → ["Pure veg only", "Add paneer", "Re-suggest"]
  • spicy query         → ["Fastest delivery", "Milder options", "Re-suggest"]
  • cart has Wow! Momo  → ["More from here", "Try elsewhere", "Re-suggest"]

Hard limits (these are non-negotiable, but they're limits not personality):
  - Never name a specific restaurant or dish in the bubble text — the cards do that.
    Bad:  "Dosa Plaza fits the bill" / "got Indian, Chinese, and South Indian"
    Good: "two cheap picks + one fast one" / "couple of veg options + a faster non-veg"
  - Never list cuisine types (Italian, Chinese, North Indian, etc.) by name in text.
    The user can read the cuisines off the cards — your job is to describe the *shape* of the list.
  - Never invent data not in the input.
  - Never claim an order was placed or schedule it.
  - If the results are empty or wrong, say so directly and ask a useful pivot question — don't list what's missing.
  - Output ONLY a JSON array: [{"text":"...","quick_replies":[...]}].
"""


_FEW_SHOTS = """\
Examples — these show how Bhook's tone shifts with the user. Don't copy them; learn the pattern.

──── Example 1 (hungry + cheap) ────
User: "something cheap and filling for dinner"
Recent intent: budget_max=200, mood=heavy
[
  {"text":"three solid filling picks under ₹200 — check em out 👇","quick_replies":[]},
  {"text":"want more variety or biryani-only?","quick_replies":["Biryani only","Mix it up","Re-suggest"]}
]

──── Example 2 (rough day, comfort) ────
User: "had a rough day, comfort food"
Recent intent: mood=comfort
[
  {"text":"oof, sending warm food 🍜","quick_replies":[]},
  {"text":"butter chicken's at the top — that work or something else?","quick_replies":["Yes, that","Veg comfort","Re-suggest"]}
]

──── Example 3 (celebrating) ────
User: "celebrating today, want something good"
Recent intent: mood=celebratory
[
  {"text":"oh nice, congrats 🎉 picked the top-rated places near you","quick_replies":[]},
  {"text":"sharing or solo? changes what i'd nudge you toward","quick_replies":["Sharing","Solo","Surprise me"]}
]

──── Example 4 (repeat customer with memory) ────
User: "lunch"
User facts: ["orders from Wow! Momo often (5x)", "veg only"]
Recent intent: search_query=lunch
[
  {"text":"same Wow! Momo as usual, or feeling adventurous today? 🥟","quick_replies":["Usual","Something new","Surprise me"]}
]

──── Example 5 (rushed) ────
User: "fast food in 25 min"
Recent intent: speed=fast
[
  {"text":"sorted by speed — top one's 22 min ⚡","quick_replies":[]},
  {"text":"that's the fastest you'll get — pick or re-suggest?","quick_replies":["Pick top","Re-suggest","Different cuisine"]}
]
"""


def _scratchpad_directive() -> str:
    """The 'think before you write' instruction the persona uses."""
    return (
        "BEFORE writing your JSON, briefly think (silently) about:\n"
        "  (a) what does the user actually want here? what's their vibe?\n"
        "  (b) what's the angle on these dishes? (cheap, fast, bestsellers, weird find, usual?)\n"
        "  (c) what one chip would help them most next?\n"
        "Then write the bubbles. Don't output your thinking — only the final JSON array.\n"
    )


# ── Public API ────────────────────────────────────────────────────────────────

async def format_recommendations(
    intent: UserIntent,
    top_6: list[dict],
    history: list[dict],
    gemini_client,
    expansion_reasoning: str | None = None,
) -> list[dict[str, Any]]:
    """Format scored recommendations as Bhook bubbles.

    expansion_reasoning is a 1-line trace from intent_expander explaining
    the angle taken on a vague request (e.g. "warm hearty north indian
    comfort"). Bhook can reference this *vibe* in the bubble.
    """
    if not top_6:
        return [{
            "text": "couldn't find anything that fits — wanna tweak the search?",
            "quick_replies": ["Different cuisine", "Higher budget", "Re-suggest"],
        }]

    user_prompt = _prepare_context(intent, top_6, history, expansion_reasoning)

    system_prompt = "\n".join([
        _CHARACTER,
        _BUBBLE_GUIDELINES,
        _scratchpad_directive(),
        _FEW_SHOTS,
    ])

    try:
        response = await gemini_client.generate_content_async(
            contents=[system_prompt, user_prompt],
            generation_config={
                "response_mime_type": "application/json",
                "temperature": 0.6,  # warmer — character voice needs variability
                "max_output_tokens": 1024,
            },
        )
        raw = (response.text or "").strip()
        bubbles = _extract_bubbles(raw)
        if not bubbles:
            raise ValueError(f"could not extract bubbles from: {raw[:160]!r}")
        return bubbles

    except Exception as exc:
        log.warning("persona_failed: %s — using deterministic fallback", exc)
        return _deterministic_fallback(top_6)


# ── Context preparation ──────────────────────────────────────────────────────

def _prepare_context(
    intent: UserIntent,
    top_6: list[dict],
    history: list[dict],
    expansion_reasoning: str | None = None,
) -> str:
    """Compact JSON context — keep prompt small."""
    is_dish_card = bool(top_6 and top_6[0].get("itemId"))
    compact: list[dict] = []
    for d in top_6:
        if is_dish_card:
            compact.append({
                "name":       d.get("name"),
                "restaurant": d.get("restaurant"),
                "price":      d.get("price"),
                "veg":        d.get("veg"),
                "bestseller": d.get("bestseller", False),
                "rating":     d.get("rating"),
                "eta":        d.get("eta"),
            })
        else:
            compact.append({
                "name":       d.get("name"),
                "cuisines":   d.get("cuisines"),
                "rating":     d.get("rating"),
                "eta":        d.get("eta") or d.get("deliveryTime"),
                "price":      d.get("price") or d.get("costForTwo"),
            })

    recent = [
        {"role": m.get("role"), "text": m.get("text")}
        for m in (history[-6:] if history else [])
    ]

    # Memory: top facts about the user, injected once per turn
    facts = user_memory.get_user_facts(max_facts=5)

    context = {
        "intent":          intent.model_dump(exclude_none=True),
        "user_facts":      facts,
        # Only present on vague queries — tells Bhook the angle the system
        # took on translating their request. Bhook can reference the *vibe*
        # (not the specific cuisines we searched for) in the reply.
        "search_angle":    expansion_reasoning,
        "result_type": "dishes" if is_dish_card else "restaurants",
        "results":    compact,
        "history":    recent,
    }
    return json.dumps(context, ensure_ascii=False)


# ── Output parsing ────────────────────────────────────────────────────────────

_JSON_ARRAY_RE = re.compile(r"\[\s*\{.*\}\s*\]", re.DOTALL)


def _extract_bubbles(raw: str) -> list[dict[str, Any]]:
    """
    Pull a JSON array of bubbles from the model output.

    The thinking-scratchpad directive may sometimes leak as prose; we tolerate
    that by extracting the first balanced JSON array we can find.
    """
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        m = _JSON_ARRAY_RE.search(raw)
        if not m:
            return []
        try:
            parsed = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []

    if not isinstance(parsed, list):
        return []
    bubbles = [b for b in parsed if isinstance(b, dict) and "text" in b]
    # Sanity cap on length — character voice is short, not chatty
    return bubbles[:3]


# ── Fallback when the model is unavailable ───────────────────────────────────

def _deterministic_fallback(top_6: list[dict]) -> list[dict[str, Any]]:
    n = len(top_6)
    return [{
        "text": f"found {n} option{'s' if n != 1 else ''} for you 🍽️",
        "quick_replies": ["Under ₹300", "Fastest delivery", "Re-suggest"],
    }]
