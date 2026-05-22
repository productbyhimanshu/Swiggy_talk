"""Guards real order placement — blocked until eval suite passes."""

from phases.phase_00.config import get_settings


class OrderDisabledError(RuntimeError):
    """Raised when place_food_order is called while orders are disabled."""


def assert_orders_enabled() -> None:
    """Raise unless ORDER_ENABLED and EVAL_SUITE_PASSED are both true."""
    settings = get_settings()
    if not settings.orders_allowed:
        raise OrderDisabledError(
            "place_food_order is disabled. Set ORDER_ENABLED=true only after "
            "EVAL_SUITE_PASSED=true (Phase 12 eval gate)."
        )
