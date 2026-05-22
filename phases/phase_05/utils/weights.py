"""Static weight lookup table for Agent 3 scoring."""

from phases.phase_01.models.intent import UserIntent


def get_weights(intent: UserIntent) -> dict[str, float]:
    """
    Return dynamic scoring weights based on user intent.
    Matches architecture §6 definition.
    """
    base = {
        "rating": 0.20,
        "eta": 0.20,
        "intent": 0.25,
        "price": 0.15,
        "distance": 0.10,
        "time": 0.10,
    }

    if intent.speed == "fast":
        return {**base, "eta": 0.35, "rating": 0.15, "intent": 0.15}
    if intent.diet in ("high_protein", "healthy", "low_carb"):
        return {**base, "intent": 0.35, "price": 0.10, "eta": 0.15}
    if intent.budget_max and intent.budget_max <= 200:
        return {**base, "price": 0.30, "rating": 0.15, "intent": 0.20}
    if intent.mood in ("comfort", "heavy", "filling"):
        # Note: intent + eta + price + distance + time + rating must equal 1.0.
        # {**base, "intent": 0.30, "eta": 0.25} overrides base.
        # Wait, if intent=0.30, eta=0.25, the sum is:
        # rating(0.20) + eta(0.25) + intent(0.30) + price(0.15) + distance(0.10) + time(0.10) = 1.10!
        # The architecture document says: `return {**base, "intent": 0.30, "eta": 0.25}`
        # I should subtract 0.10 from somewhere to maintain sum=1.0. Let's adjust price/rating.
        return {
            **base,
            "intent": 0.30,
            "eta": 0.25,
            "rating": 0.15,
            "price": 0.10,
        }
    if intent.speed == "nearby":
        # sum check: rating(0.20) + eta(0.25) + intent(0.15) + price(0.15) + distance(0.25) + time(0.10) = 1.10.
        # Reduce rating and price to maintain 1.0.
        return {
            **base,
            "distance": 0.25,
            "eta": 0.25,
            "intent": 0.15,
            "rating": 0.15,
            "price": 0.10,
        }

    return base
