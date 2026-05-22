"""Phase 4 — hard filter gate tests (exit gates 4.E1, 4.E3).

All LOCAL — uses fixture dicts, no Swiggy API calls.
"""

import pytest

from phases.phase_01.models.intent import UserIntent
from phases.phase_04.utils.filters import apply_filters


# ── Fixture helpers ────────────────────────────────────────────────────────────

def _restaurant(
    *,
    status: str = "OPEN",
    rating: float = 4.5,
    delivery_time: str = "25-30 mins",
    pure_veg: bool = False,
    items: list[dict] | None = None,
    max_eta_allowed: int | None = None,
) -> dict:
    r: dict = {
        "availabilityStatus": status,
        "rating": rating,
        "deliveryTime": delivery_time,
        "pureVeg": pure_veg,
    }
    if items is not None:
        r["items"] = items
    if max_eta_allowed is not None:
        r["_max_eta_allowed"] = max_eta_allowed
    return r


def _item(*, is_veg: bool = True, price: float = 200.0) -> dict:
    return {"isVeg": is_veg, "price": price, "name": "Test Item"}


def _intent(**kwargs) -> UserIntent:
    base: dict = {}
    base.update(kwargs)
    return UserIntent(**base)


# ── Gate 1: OPEN ───────────────────────────────────────────────────────────────

def test_closed_restaurant_killed():
    r = _restaurant(status="CLOSED")
    assert apply_filters([r], _intent()) == []


def test_open_restaurant_passes():
    r = _restaurant(status="OPEN")
    assert len(apply_filters([r], _intent())) == 1


def test_missing_status_killed():
    r = {"rating": 4.5, "deliveryTime": "30 mins"}  # no availabilityStatus
    assert apply_filters([r], _intent()) == []


# ── Gate 2: Rating ─────────────────────────────────────────────────────────────

def test_rating_below_4_killed():
    r = _restaurant(rating=3.9)
    assert apply_filters([r], _intent()) == []


def test_rating_exactly_4_passes():
    r = _restaurant(rating=4.0)
    assert len(apply_filters([r], _intent())) == 1


def test_rating_above_4_passes():
    r = _restaurant(rating=4.8)
    assert len(apply_filters([r], _intent())) == 1


def test_missing_rating_killed():
    r = {"availabilityStatus": "OPEN", "deliveryTime": "30 mins"}
    assert apply_filters([r], _intent()) == []


def test_non_numeric_rating_killed():
    r = _restaurant()
    r["rating"] = "N/A"
    assert apply_filters([r], _intent()) == []


# ── Gate 3: ETA ────────────────────────────────────────────────────────────────

def test_eta_within_window_passes():
    # max_eta_allowed injected by pipeline; 30 mins ETA, allowed 30 → pass
    r = _restaurant(delivery_time="25-30 mins", max_eta_allowed=30)
    assert len(apply_filters([r], _intent(timing="13:00"))) == 1


def test_eta_exceeds_window_killed():
    r = _restaurant(delivery_time="35-45 mins", max_eta_allowed=30)
    assert apply_filters([r], _intent(timing="13:00")) == []


def test_no_timing_skips_eta_gate():
    # timing=None → ETA gate always passes regardless of delivery time
    r = _restaurant(delivery_time="60-90 mins")
    assert len(apply_filters([r], _intent(timing=None))) == 1


def test_no_max_eta_injected_passes():
    # timing set but pipeline didn't inject _max_eta_allowed → pass through
    r = _restaurant(delivery_time="60-90 mins")
    assert len(apply_filters([r], _intent(timing="13:00"))) == 1


# ── Gate 4: Diet ───────────────────────────────────────────────────────────────

def test_veg_user_nonveg_item_killed():
    r = _restaurant(items=[_item(is_veg=False, price=200)])
    assert apply_filters([r], _intent(veg_nonveg="veg")) == []


def test_veg_user_veg_item_passes():
    r = _restaurant(items=[_item(is_veg=True, price=200)])
    assert len(apply_filters([r], _intent(veg_nonveg="veg"))) == 1


def test_veg_user_pure_veg_restaurant_passes():
    r = _restaurant(pure_veg=True)
    assert len(apply_filters([r], _intent(veg_nonveg="veg"))) == 1


def test_nonveg_user_no_diet_filter():
    r = _restaurant(items=[_item(is_veg=False, price=200)])
    assert len(apply_filters([r], _intent(veg_nonveg="nonveg"))) == 1


def test_both_veg_nonveg_no_filter():
    r = _restaurant(items=[_item(is_veg=False, price=200)])
    assert len(apply_filters([r], _intent(veg_nonveg="both"))) == 1


def test_veg_user_mixed_items_killed():
    r = _restaurant(items=[_item(is_veg=True), _item(is_veg=False)])
    assert apply_filters([r], _intent(veg_nonveg="veg")) == []


# ── Gate 5: Budget ─────────────────────────────────────────────────────────────

def test_item_over_budget_killed():
    r = _restaurant(items=[_item(price=600)])
    assert apply_filters([r], _intent(budget_max=500)) == []


def test_item_at_budget_passes():
    r = _restaurant(items=[_item(price=500)])
    assert len(apply_filters([r], _intent(budget_max=500))) == 1


def test_item_under_budget_passes():
    r = _restaurant(items=[_item(price=299)])
    assert len(apply_filters([r], _intent(budget_max=300))) == 1


def test_no_budget_no_filter():
    r = _restaurant(items=[_item(price=999)])
    assert len(apply_filters([r], _intent(budget_max=None))) == 1


def test_item_over_swiggy_cap_killed():
    """Items over ₹1000 are always killed regardless of user budget."""
    r = _restaurant(items=[_item(price=1001)])
    assert apply_filters([r], _intent(budget_max=None)) == []


def test_no_items_budget_gate_passes():
    """If no item data, budget gate is skipped (scorer handles it later)."""
    r = _restaurant()
    assert len(apply_filters([r], _intent(budget_max=100))) == 1


# ── Combined / edge cases ──────────────────────────────────────────────────────

def test_all_gates_pass_clean_fixture():
    r = _restaurant(
        status="OPEN",
        rating=4.5,
        delivery_time="20-30 mins",
        pure_veg=False,
        items=[_item(is_veg=True, price=250)],
    )
    assert len(apply_filters([r], _intent(budget_max=300, veg_nonveg="veg"))) == 1


def test_empty_input_returns_empty():
    assert apply_filters([], _intent()) == []


def test_multiple_restaurants_partial_filter():
    open_r = _restaurant(status="OPEN", rating=4.5)
    closed_r = _restaurant(status="CLOSED", rating=4.5)
    low_r = _restaurant(status="OPEN", rating=3.5)
    result = apply_filters([open_r, closed_r, low_r], _intent())
    assert len(result) == 1
    assert result[0] is open_r


def test_filter_order_open_before_rating():
    """Closed restaurant should be killed before rating check — order matters for performance."""
    closed_high_rated = _restaurant(status="CLOSED", rating=4.9)
    result = apply_filters([closed_high_rated], _intent())
    assert result == []
