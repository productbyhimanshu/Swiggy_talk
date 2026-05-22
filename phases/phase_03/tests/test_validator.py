"""Phase 3 — Agent 2 (validator) tests.

All LOCAL — zero Gemini calls. Covers exit gates 3.E4–3.E6.
"""

import pytest

from phases.phase_01.models.intent import UserIntent
from phases.phase_03.agents.validator import ValidationResult, validate_intent


def _intent(**kwargs) -> UserIntent:
    base = {"search_query": "biryani"}  # minimal valid intent
    base.update(kwargs)
    return UserIntent(**base)


# ── 3.E4: budget > 1000 → clarify ─────────────────────────────────────────────

def test_budget_over_cap_is_invalid():
    result = validate_intent(_intent(budget_max=1500, search_query="biryani"))
    assert result.valid is False
    assert result.clarify_field == "budget_max"
    assert "1000" in result.clarify_question
    assert result.quick_replies and len(result.quick_replies) == 3


def test_budget_exact_cap_is_valid():
    result = validate_intent(_intent(budget_max=1000, search_query="biryani"))
    assert result.valid is True


def test_budget_under_cap_is_valid():
    result = validate_intent(_intent(budget_max=999, search_query="biryani"))
    assert result.valid is True


def test_budget_none_no_cap_check():
    result = validate_intent(_intent(budget_max=None, search_query="pizza"))
    assert result.valid is True


# ── 3.E5: veg/non-veg clarification ───────────────────────────────────────────

def test_veg_nonveg_needs_clarification():
    result = validate_intent(_intent(veg_nonveg="NEEDS_CLARIFICATION"))
    # valid=True (can search), but clarify_field set
    assert result.valid is True
    assert result.clarify_field == "veg_nonveg"
    assert result.clarify_question is not None
    assert result.quick_replies and len(result.quick_replies) == 3


def test_veg_explicit_no_clarification():
    result = validate_intent(_intent(veg_nonveg="veg", search_query="paneer"))
    assert result.valid is True
    assert result.clarify_field is None


def test_nonveg_explicit_no_clarification():
    result = validate_intent(_intent(veg_nonveg="nonveg", search_query="chicken"))
    assert result.valid is True
    assert result.clarify_field is None


def test_both_veg_nonveg_no_clarification():
    result = validate_intent(_intent(veg_nonveg="both", search_query="biryani"))
    assert result.valid is True
    assert result.clarify_field is None


# ── 3.E6: no signals → clarify ────────────────────────────────────────────────

def test_no_signals_asks_for_preference():
    empty = UserIntent()  # all fields None
    result = validate_intent(empty)
    assert result.valid is False
    assert result.clarify_question is not None
    assert result.quick_replies and len(result.quick_replies) > 0


def test_only_search_query_sufficient():
    result = validate_intent(UserIntent(search_query="pizza"))
    assert result.valid is True


def test_only_mood_sufficient():
    result = validate_intent(UserIntent(mood="comfort"))
    assert result.valid is True


def test_only_cuisine_sufficient():
    result = validate_intent(UserIntent(cuisine="north_indian"))
    assert result.valid is True


def test_only_diet_sufficient():
    result = validate_intent(UserIntent(diet="high_protein"))
    assert result.valid is True


# ── Additional edge cases ──────────────────────────────────────────────────────

def test_budget_exactly_one_valid():
    result = validate_intent(_intent(budget_max=1, search_query="anything"))
    assert result.valid is True


def test_all_signals_and_budget_cap_error_takes_priority():
    """Budget cap check happens before veg clarification."""
    result = validate_intent(
        _intent(
            budget_max=2000,
            veg_nonveg="NEEDS_CLARIFICATION",
            search_query="biryani",
        )
    )
    assert result.valid is False
    assert result.clarify_field == "budget_max"


def test_validation_result_to_bubble_when_invalid():
    result = ValidationResult(
        valid=False,
        clarify_question="what are you in the mood for?",
        quick_replies=["Biryani", "Pizza"],
    )
    bubble = result.to_bubble()
    assert bubble is not None
    assert bubble.text == "what are you in the mood for?"
    assert bubble.quick_replies == ["Biryani", "Pizza"]


def test_validation_result_to_bubble_when_valid():
    result = ValidationResult(valid=True)
    assert result.to_bubble() is None


def test_validation_result_repr():
    r = ValidationResult(valid=False, clarify_field="budget_max")
    assert "budget_max" in repr(r)
