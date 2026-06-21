"""Guards real order placement — blocked unless ORDER_ENABLED=true.

Test/eval protection: phases/conftest.py force-resets ORDER_ENABLED=false
at the start of every pytest run, so this guard is unbypassable from any
automated test or eval run regardless of what the .env on disk holds.
"""

from phases.phase_00.config import get_settings


class OrderDisabledError(RuntimeError):
    """Raised when place_food_order is called while orders are disabled."""


def assert_orders_enabled() -> None:
    """Raise unless ORDER_ENABLED is true."""
    settings = get_settings()
    if not settings.orders_allowed:
        raise OrderDisabledError(
            "place_food_order is disabled. Set ORDER_ENABLED=true in .env "
            "to enable real COD placement (demo mode)."
        )
