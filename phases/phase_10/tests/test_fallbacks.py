"""Phase 10 eval suite — fallback chain (architecture §14, 10.E2-10.E4).

Tests:
  10.E2a: swiggy_down_bubbles returns correct structure
  10.E2b: fallback_sort_by_rating sorts desc, caps at 6
  10.E2c: restaurant_closed_bubbles includes restaurant name
  10.E2d: apply_fallback_chain dispatches correctly by stage
  10.E3:  Gemini classify failure → fallback_route returns NEW_SEARCH
  10.E4:  cod_only_warning_bubble is a single dict with type=bubble
"""

import pytest
from phases.phase_10.utils.fallbacks import (
    swiggy_down_bubbles,
    fallback_route,
    fallback_intent,
    fallback_sort_by_rating,
    restaurant_closed_bubbles,
    cod_only_warning_bubble,
    apply_fallback_chain,
)


# ── 10.E2a — Swiggy down ──────────────────────────────────────────────────────

def test_swiggy_down_bubbles_structure():
    """10.E2a — swiggy_down template returns ≥2 bubbles with type=bubble."""
    bubbles = swiggy_down_bubbles()

    assert len(bubbles) >= 2
    for b in bubbles:
        assert b.get("type") == "bubble"
        assert "text" in b
    # Last bubble should offer a retry quick reply
    last_qr = bubbles[-1].get("quick_replies", [])
    assert any("again" in qr.lower() for qr in last_qr)


# ── 10.E2b — Fallback sort ────────────────────────────────────────────────────

def test_fallback_sort_by_rating_orders_descending():
    """10.E2b — fallback_sort_by_rating orders desc and caps at 6."""
    restaurants = [
        {"name": f"R{i}", "rating": i} for i in range(10, 0, -1)  # 10 items
    ]
    result = fallback_sort_by_rating(restaurants)

    assert len(result) == 6
    ratings = [r["rating"] for r in result]
    assert ratings == sorted(ratings, reverse=True)


def test_fallback_sort_handles_missing_rating():
    """10.E2b edge — missing rating defaults to 0 (no crash)."""
    restaurants = [
        {"name": "A"},
        {"name": "B", "rating": 4.5},
        {"name": "C", "rating": None},
    ]
    result = fallback_sort_by_rating(restaurants)
    assert result[0]["name"] == "B"  # highest rating first


def test_fallback_sort_fewer_than_6():
    """10.E2b edge — <6 results returned as-is."""
    restaurants = [{"name": "X", "rating": 3.0}]
    result = fallback_sort_by_rating(restaurants)
    assert len(result) == 1


# ── 10.E2c — Restaurant closed ───────────────────────────────────────────────

def test_restaurant_closed_bubbles_includes_name():
    """10.E2c — closed bubble includes restaurant name."""
    bubbles = restaurant_closed_bubbles("Biryani Blues")

    assert len(bubbles) == 2
    assert "Biryani Blues" in bubbles[0]["text"]


def test_restaurant_closed_bubbles_default_name():
    """10.E2c edge — no name provided → graceful generic text."""
    bubbles = restaurant_closed_bubbles()
    # Should not crash; text should still make sense
    assert bubbles[0]["text"]


# ── 10.E2d — apply_fallback_chain dispatch ───────────────────────────────────

def test_apply_fallback_chain_swiggy_stage():
    """10.E2d — stage=swiggy → swiggy_down bubbles."""
    bubbles = apply_fallback_chain(Exception("503"), {"stage": "swiggy"})
    assert any("Swiggy" in b["text"] for b in bubbles)


def test_apply_fallback_chain_closed_stage():
    """10.E2d — stage=closed → restaurant closed bubbles with name."""
    bubbles = apply_fallback_chain(
        Exception("closed"),
        {"stage": "closed", "restaurant_name": "Test Place"}
    )
    assert any("Test Place" in b["text"] for b in bubbles)


def test_apply_fallback_chain_unknown_stage():
    """10.E2d — unknown stage → generic retry message."""
    bubbles = apply_fallback_chain(Exception("???"), {"stage": "unknown"})
    assert len(bubbles) >= 1
    assert all("text" in b for b in bubbles)


# ── 10.E3 — Gemini classify fallback ─────────────────────────────────────────

def test_fallback_route_returns_new_search():
    """10.E3 — Gemini classify failure → fallback_route returns NEW_SEARCH."""
    route = fallback_route()
    assert route == "NEW_SEARCH"


def test_fallback_intent_returns_empty_dict():
    """10.E3 — Agent 1 failure → fallback_intent returns empty dict."""
    intent = fallback_intent()
    assert isinstance(intent, dict)
    assert len(intent) == 0


# ── 10.E4 — COD coupon filter ────────────────────────────────────────────────

def test_cod_only_warning_bubble_structure():
    """10.E4 — cod_only_warning_bubble is a single dict with type=bubble."""
    bubble = cod_only_warning_bubble()

    assert isinstance(bubble, dict)
    assert bubble.get("type") == "bubble"
    assert "text" in bubble
    assert "coupon" in bubble["text"].lower() or "cod" in bubble["text"].lower()
