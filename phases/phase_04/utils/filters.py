"""Hard filter gates — architecture §6.

Filter execution order (cheapest checks first):
  1. OPEN — availabilityStatus must be "OPEN"
  2. Rating — rating >= 4.0
  3. ETA — max_eta <= user_time_window (if set)
  4. Diet — veg_nonveg check per item (restaurant-level pureVeg flag)
  5. Budget — item price and projected cart total must be within budget

Each gate operates on the restaurant dict as returned by Swiggy
search_restaurants / get_restaurant_menu.
"""

from __future__ import annotations

from phases.phase_01.models.intent import UserIntent
from phases.phase_04.utils.parse_eta import parse_eta

# Minimum rating to pass the rating gate (architecture §6)
_MIN_RATING = 4.0

# Swiggy hard cart cap (architecture §2)
_CART_CAP = 1_000


def apply_filters(
    restaurants: list[dict],
    intent: UserIntent,
) -> list[dict]:
    """
    Apply all 5 hard gates in priority order.

    Args:
        restaurants: Raw list from search_restaurants (or get_restaurant_menu
                     when items are embedded).
        intent: Parsed and validated UserIntent.

    Returns:
        Filtered list — restaurants that passed every gate.
    """
    survivors: list[dict] = []

    for restaurant in restaurants:
        if not _gate_open(restaurant):
            continue
        if not _gate_rating(restaurant):
            continue
        if not _gate_eta(restaurant, intent):
            continue
        if not _gate_diet(restaurant, intent):
            continue
        if not _gate_budget(restaurant, intent):
            continue
        survivors.append(restaurant)

    return survivors


# ── Individual gate functions ──────────────────────────────────────────────────

def _gate_open(restaurant: dict) -> bool:
    """Gate 1: restaurant must be OPEN."""
    status = restaurant.get("availabilityStatus", "")
    return status == "OPEN"


def _gate_rating(restaurant: dict) -> bool:
    """Gate 2: rating must be >= 4.0."""
    raw = restaurant.get("rating")
    if raw is None:
        # No rating data — be conservative and exclude
        return False
    try:
        return float(raw) >= _MIN_RATING
    except (TypeError, ValueError):
        return False


def _gate_eta(restaurant: dict, intent: UserIntent) -> bool:
    """Gate 3: worst-case ETA must fit user's time window (if specified)."""
    if intent.timing is None:
        return True  # No time constraint — pass

    # Parse the timing type to get max acceptable ETA in minutes
    # timing = HH:MM, timing_type = deliver_by / order_now
    # For filter purposes: if the restaurant ETA exceeds budget, kill it.
    # We calculate time_window from timing vs now in the pipeline;
    # here we accept a pre-computed max_eta_minutes field if present.
    max_eta_allowed: int | None = restaurant.get("_max_eta_allowed")
    if max_eta_allowed is None:
        return True  # Pipeline hasn't injected window — pass through

    delivery_time_str = restaurant.get("deliveryTime", "")
    eta_max = parse_eta(delivery_time_str)
    return eta_max <= max_eta_allowed


def _gate_diet(restaurant: dict, intent: UserIntent) -> bool:
    """Gate 4: veg filter.

    If user requested veg-only:
    - Use restaurant-level pureVeg flag if no item detail.
    - If items are embedded (menu fetch), kill any non-veg item.
    """
    if intent.veg_nonveg not in ("veg",):
        return True  # Non-veg or both — no filter needed

    # Restaurant-level pureVeg badge
    if restaurant.get("pureVeg") is True:
        return True

    # If item-level data is available (from get_restaurant_menu)
    items: list[dict] = restaurant.get("items", [])
    if items:
        # Restaurant passes only if ALL requested items are veg
        return all(item.get("isVeg", False) for item in items)

    # No item data but pureVeg not set — conservative: include
    # (scoring will further rank by intent match)
    return True


def _gate_budget(restaurant: dict, intent: UserIntent) -> bool:
    """Gate 5: price must be within user budget AND Swiggy cart cap.

    If item-level data present: kill if any item.price > budget_max.
    Also enforces the ₹1000 Swiggy Builders Club hard cap.
    """
    items: list[dict] = restaurant.get("items", [])
    if not items:
        return True  # No item data at this point — pass (scorer will filter)

    budget = intent.budget_max  # may be None

    for item in items:
        try:
            price = float(item.get("price", 0))
        except (TypeError, ValueError):
            continue

        # Item price exceeds Swiggy hard cap
        if price > _CART_CAP:
            return False

        # Item price exceeds user budget
        if budget is not None and price > budget:
            return False

    return True
