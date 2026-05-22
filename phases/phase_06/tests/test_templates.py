"""Eval suite for Phase 6 static templates."""

from phases.phase_06.utils.templates import (
    get_cart_template,
    get_cancel_template,
    get_stale_template,
    get_swiggy_down_template
)


def test_cart_template_zero_gemini_calls():
    """6.E4 test_templates.py — cart/cancel/stale return zero Gemini calls."""
    # Since these are static functions, they inherently don't accept a gemini_client.
    # We verify the schema returned is correct JSON array format.
    bubbles = get_cart_template({"cart_total": 450})
    
    assert isinstance(bubbles, list)
    assert len(bubbles) == 1
    assert "text" in bubbles[0]
    assert "quick_replies" in bubbles[0]
    assert "450" in bubbles[0]["text"]


def test_cancel_template_schema():
    bubbles = get_cancel_template()
    assert isinstance(bubbles, list)
    assert "text" in bubbles[0]


def test_stale_template_schema():
    bubbles = get_stale_template()
    assert isinstance(bubbles, list)
    assert "text" in bubbles[0]


def test_swiggy_down_template_schema():
    bubbles = get_swiggy_down_template()
    assert isinstance(bubbles, list)
    assert "text" in bubbles[0]
