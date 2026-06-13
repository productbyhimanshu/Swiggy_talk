"""Per-card "why this pick" badges — deterministic, no LLM call.

Originally this used the LLM, but the model produced templated output anyway
("bestseller, under ₹200", "top-rated nearby") — so we'd pay ~700ms latency
for what's effectively a lookup over data we already have. This rewrite picks
the badge locally from the structured signals on the dish dict.

Goals (in order):
  1. Each card explains why IT is on the list — different from its neighbours.
  2. Drop badges that apply to >50% of the result set (no signal = no badge).
  3. Cap at 32 chars without mid-word truncation.

Signals we mine:
  • _match_kind: exact / all_words / category    (set by orchestrator scorer)
  • bestseller                                    (Swiggy menu flag)
  • rating ≥ 4.5                                  (top-rated)
  • eta_min ≤ fastest in set                      (fastest of these)
  • price ≤ 0.6 × budget                          (great value)
  • veg (when intent.veg_nonveg == veg)           (pure veg)
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from phases.phase_01.models.intent import UserIntent
from phases.phase_04.utils.parse_eta import parse_eta as _parse_eta

log = logging.getLogger(__name__)

_MAX_WHY_CHARS = 32


def _eta_for(d: dict) -> int:
    et = d.get("eta") or d.get("deliveryTime")
    if isinstance(et, (int, float)):
        return int(et)
    if isinstance(et, str):
        return _parse_eta(et)
    return 999


def _candidate_badges(d: dict, ctx: dict, intent: UserIntent) -> list[str]:
    """Return ALL labels that legitimately apply to this dish, ranked by signal strength."""
    out: list[str] = []

    # Strongest first
    if d.get("_match_kind") == "exact":
        out.append("matches your search")
    elif d.get("_match_kind") == "all_words":
        out.append("close match")

    if d.get("bestseller"):
        out.append("bestseller")

    rating = d.get("rating")
    if isinstance(rating, (int, float)) and float(rating) >= 4.5:
        out.append("top-rated nearby")

    et = _eta_for(d)
    if ctx.get("fastest_eta") and et == ctx["fastest_eta"] and et < 45:
        out.append(f"fastest — {et} min")

    price = d.get("price")
    budget = intent.budget_max
    if isinstance(price, (int, float)) and isinstance(budget, (int, float)) and budget:
        if price <= 0.6 * budget:
            out.append("great value")

    if intent.veg_nonveg == "veg" and d.get("veg") is True:
        out.append("pure veg")

    return out


def _dedupe_universal(badges_per_card: list[list[str]]) -> list[list[str]]:
    """
    If a badge appears on more than half the cards, it's not a differentiator
    — drop it from every card. This is what stops "bestseller, non-veg, under
    ₹200" showing on every result.
    """
    n = len(badges_per_card)
    if n <= 2:
        return badges_per_card
    counts = Counter(b for badges in badges_per_card for b in badges)
    too_common = {b for b, c in counts.items() if c > n // 2 and c > 1}
    # Always keep "matches your search" / "close match" — they're per-card signals
    too_common -= {"matches your search", "close match"}
    return [[b for b in badges if b not in too_common] for badges in badges_per_card]


def _fit(text: str) -> str:
    if len(text) <= _MAX_WHY_CHARS:
        return text
    # Trim at last full word that fits
    cut = text[: _MAX_WHY_CHARS + 1].rsplit(" ", 1)[0]
    return cut or text[:_MAX_WHY_CHARS]


def _compose(badges: list[str]) -> str:
    """Pick the best 1–2 badges that fit in the char budget."""
    if not badges:
        return ""
    primary = badges[0]
    if len(badges) == 1:
        return _fit(primary)
    secondary = badges[1]
    combined = f"{primary} · {secondary}"
    if len(combined) <= _MAX_WHY_CHARS:
        return combined
    return _fit(primary)


def annotate_picks_sync(intent: UserIntent, items: list[dict]) -> list[dict]:
    """Deterministic — adds `why` to each item in place and returns the same list."""
    if not items:
        return items

    fastest = min((_eta_for(d) for d in items), default=999)
    ctx = {"fastest_eta": fastest}

    all_badges = [_candidate_badges(d, ctx, intent) for d in items]
    all_badges = _dedupe_universal(all_badges)

    for d, badges in zip(items, all_badges):
        why = _compose(badges)
        if why:
            d["why"] = why
        else:
            d.pop("why", None)  # don't leave stale why-lines on refines

    return items


# Async wrapper to keep the old call-site signature working without a network hop.
async def annotate_picks(
    intent: UserIntent,
    items: list[dict],
    gemini_client=None,  # ignored — kept for compatibility
) -> list[dict]:
    return annotate_picks_sync(intent, items)
