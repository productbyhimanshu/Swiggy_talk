"""Intent expander — turn vague intent into concrete Swiggy queries.

Why this exists (architectural critique we ran):
  Swiggy's search_restaurants does dumb substring matching. Asking it for
  "comfort food" returns garbage; asking for "biryani" returns gold. The
  system's job is to understand *what the user means* and translate that
  into queries Swiggy can actually answer.

  Before this layer, we had a hardcoded mood map ("comfort" → "biryani").
  That worked for 4 moods. This layer replaces it with an LLM call that
  understands any vague request, considers the user's history, and outputs
  3–5 concrete dish/cuisine terms to search in parallel.

Behaviour:
  • Specific queries ("butter chicken under 300") skip this layer — no
    added latency.
  • Vague queries ("comfort food", "lunch", "something light", "snack")
    fire this expansion → multi-search → merged results.
  • The LLM also returns a short reasoning trace, surfaced to the persona
    so it can be honest about *why* it picked these spots.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from phases.phase_01.models.intent import UserIntent

log = logging.getLogger(__name__)


# Queries we treat as already-concrete (skip expansion entirely):
# anything mentioning a specific dish, restaurant cuisine, or famous food term.
_CONCRETE_TERMS = {
    "pizza", "momo", "momos", "biryani", "burger", "burgers", "dosa", "idli",
    "vada", "paneer", "chicken", "noodle", "noodles", "sandwich", "pasta",
    "sushi", "cake", "donut", "kebab", "thali", "roll", "rolls", "wrap",
    "samosa", "tikka", "shawarma", "falafel", "taco", "chowmein", "manchurian",
    "fried rice", "naan", "roti", "paratha", "chaap", "bhel", "pani puri",
    "ice cream", "shake", "lassi", "coffee", "tea", "waffle", "pancake",
    "salad", "soup", "butter chicken", "dal makhani", "khichdi", "rajma",
    "korean", "italian", "chinese", "japanese", "thai", "mexican", "lebanese",
    "north indian", "south indian", "mughlai", "punjabi", "bengali",
}


def is_vague(intent: UserIntent) -> bool:
    """
    Decide whether the user's request is concrete enough to query Swiggy
    directly, or vague enough to need LLM-driven expansion first.

    Concrete signals (skip expansion): a known cuisine/dish keyword in the
    search_query. The search_query carrying a budget alone ("under 200")
    is not concrete.
    """
    q = (intent.search_query or "").lower().strip()
    if not q:
        return True
    # Strip numeric tokens (budget) before checking
    q_clean = re.sub(r"\b\d+\b", " ", q).strip()
    if not q_clean:
        return True
    return not any(term in q_clean for term in _CONCRETE_TERMS)


class ExpandedIntent:
    """Result of an expansion: concrete searches + reasoning trace."""

    __slots__ = ("search_terms", "reasoning")

    def __init__(self, search_terms: list[str], reasoning: str = "") -> None:
        self.search_terms = search_terms
        self.reasoning = reasoning

    def __repr__(self) -> str:
        return f"ExpandedIntent(terms={self.search_terms!r}, why={self.reasoning!r})"


_SYSTEM_PROMPT = """\
You are the query strategist for a food-ordering assistant in India (Jaipur). The user's request is too vague for a literal restaurant search — your job is to translate it into 3–5 concrete Swiggy search terms that will actually find food.

Rules:
- Output 3–5 search terms. Each term should be a dish OR cuisine name that Swiggy will recognise — short, lowercase, no qualifiers.
  Good: "butter chicken", "biryani", "dal makhani", "thali"
  Bad:  "comfort food", "something filling", "good food"
- Span variety. If the user wants "comfort", don't return ["butter chicken", "chicken curry", "chicken biryani"] (all chicken) — return a mix.
- Honour explicit constraints in the intent: respect mood, diet (veg/non-veg), budget tier (cheap → street food).
- Respect user_facts. If they say "veg only", do not return non-veg terms. If they order from a specific cuisine often, lean that way.
- The time of day matters: morning → breakfast items, late night → snacks/comfort.

Also output a one-line reasoning trace (≤80 chars) — what angle you took. Be specific:
  "warm hearty north indian comfort"  ✓
  "Picked variety based on intent"    ✗

Output ONLY this JSON: {"search_terms": ["...", "..."], "reasoning": "..."}.
"""


def _fallback(intent: UserIntent) -> ExpandedIntent:
    """Deterministic fallback when LLM is unreachable."""
    mood = (intent.mood or "").lower()
    diet = (intent.diet or "").lower()
    q = (intent.search_query or "").lower()

    if "healthy" in q or diet == "healthy":
        terms = ["salad", "grilled", "soup", "thali"]
    elif "snack" in q or "snacks" in q:
        terms = ["samosa", "pakora", "chaat", "sandwich"]
    elif mood == "comfort":
        terms = ["biryani", "butter chicken", "dal makhani", "thali"]
    elif mood == "heavy" or "filling" in q:
        terms = ["thali", "biryani", "kebab", "naan"]
    elif mood == "light":
        terms = ["salad", "soup", "wrap", "sandwich"]
    elif mood == "celebratory":
        terms = ["kebab", "biryani", "dessert", "tikka"]
    elif "breakfast" in q:
        terms = ["dosa", "paratha", "poha", "sandwich"]
    elif "lunch" in q:
        terms = ["thali", "biryani", "rice bowl", "chinese"]
    elif "dinner" in q:
        terms = ["biryani", "butter chicken", "thali", "kebab"]
    else:
        terms = ["biryani", "thali", "north indian", "chinese"]
    return ExpandedIntent(search_terms=terms, reasoning="fallback (LLM unavailable)")


def _clean_terms(terms: Any) -> list[str]:
    if not isinstance(terms, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for t in terms:
        if not isinstance(t, str):
            continue
        t = t.strip().lower()
        # Drop empty + dedupe + cap each term length
        if t and t not in seen and len(t) <= 30:
            seen.add(t)
            out.append(t)
    return out[:5]


async def expand_intent(
    intent: UserIntent,
    user_facts: list[str],
    hour_of_day: int,
    gemini_client,
) -> ExpandedIntent:
    """
    Expand a vague intent into concrete Swiggy search terms.

    Should be called only when is_vague(intent) is True — otherwise it's
    wasted latency. Always returns something safe (deterministic fallback
    on any failure).
    """
    user_prompt = json.dumps({
        "intent":      intent.model_dump(exclude_none=True),
        "user_facts":  user_facts,
        "hour_of_day": hour_of_day,
    }, ensure_ascii=False)

    try:
        resp = await gemini_client.generate_content_async(
            contents=[_SYSTEM_PROMPT, user_prompt],
            generation_config={
                "response_mime_type": "application/json",
                "temperature": 0.4,
                "max_output_tokens": 256,
            },
        )
        data = json.loads((resp.text or "{}").strip())
        terms = _clean_terms(data.get("search_terms"))
        reasoning = str(data.get("reasoning", ""))[:120]
        if not terms:
            raise ValueError("LLM returned no usable search terms")
        return ExpandedIntent(search_terms=terms, reasoning=reasoning)
    except Exception as exc:
        log.warning("intent_expand_failed: %s — falling back", exc)
        return _fallback(intent)
