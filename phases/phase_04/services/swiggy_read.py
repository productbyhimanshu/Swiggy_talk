"""Swiggy read-only tool wrappers with exponential-backoff retry.

Architecture §6 tools covered here (read path only):
  get_addresses, search_restaurants, get_restaurant_menu, search_menu,
  get_food_cart, fetch_food_coupons, track_food_order, get_food_orders

Write tools (update_food_cart, flush_food_cart, apply_food_coupon) ship in Phase 9.
The ordering endpoint stays BLOCKED until Phase 12 gate.

Retry policy (architecture §14):
  3× exponential backoff (1s, 2s, 4s) on 5xx / transport timeout.
  After exhaustion → raises SwiggyUnavailableError → caller returns swiggy_down template.
"""

from __future__ import annotations

import asyncio
from typing import Any

from phases.phase_00.config import Settings, get_settings
from phases.phase_00.logging_setup import get_logger
from phases.phase_00.services.swiggy_api import SwiggyApiClient, SwiggyApiError
from phases.phase_00.services.swiggy_auth import SwiggyAuthService

log = get_logger(__name__)

_RETRY_COUNT = 3
_RETRY_BACKOFF = (1.0, 2.0, 4.0)  # seconds between retries


class SwiggyUnavailableError(Exception):
    """Raised after all retries exhausted — triggers swiggy_down template."""


class SwiggyReadClient:
    """
    High-level wrapper around SwiggyApiClient for read-only Swiggy tools.

    Adds:
    - Automatic 3× retry with exponential backoff on 5xx / timeout
    - Convenience methods matching architecture tool names
    - COD coupon filtering (fetch_food_coupons)
    - address_id auto-resolution guard (search_restaurants)
    """

    def __init__(
        self,
        settings: Settings | None = None,
        api: SwiggyApiClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._api = api or SwiggyApiClient(
            settings=self.settings,
            auth=SwiggyAuthService(self.settings),
        )

    # ── Injectable override for tests ─────────────────────────────────────────
    # Maps tool_name → async callable(arguments) → Any
    _tool_overrides: dict[str, Any] = {}

    def set_tool_override(self, tool_name: str, fn: Any) -> None:
        """Replace a specific tool call with a mock (for tests)."""
        self._tool_overrides[tool_name] = fn

    def clear_overrides(self) -> None:
        self._tool_overrides.clear()

    # ── Read tool wrappers ─────────────────────────────────────────────────────

    async def get_addresses(self) -> list[dict]:
        """Return user's saved Swiggy delivery addresses."""
        result = await self._call("get_addresses", {})
        if isinstance(result, list):
            return result
        # Some API responses wrap addresses in a key
        if isinstance(result, dict):
            return result.get("addresses", [result])
        return []

    async def search_restaurants(
        self,
        query: str,
        address_id: str,
    ) -> list[dict]:
        """
        Search restaurants by query + addressId.

        architecture §2: addressId is REQUIRED — assert non-null.
        Returns list of restaurant dicts with availabilityStatus, rating, deliveryTime.
        """
        if not address_id:
            raise ValueError(
                "address_id is required for search_restaurants. "
                "Call get_addresses() first."
            )
        result = await self._call(
            "search_restaurants",
            {"query": query, "addressId": address_id},
        )
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return result.get("restaurants", [])
        return []

    async def get_restaurant_menu(self, restaurant_id: str) -> dict:
        """Full menu for a restaurant — items include isVeg, price, name."""
        result = await self._call(
            "get_restaurant_menu",
            {"restaurantId": restaurant_id},
        )
        if isinstance(result, dict):
            return result
        return {"items": []}

    async def search_menu(
        self,
        query: str,
        restaurant_id: str | None = None,
        address_id: str | None = None,
    ) -> list[dict]:
        """Search items within / across restaurants."""
        args: dict[str, Any] = {"query": query}
        if restaurant_id:
            args["restaurantId"] = restaurant_id
        if address_id:
            args["addressId"] = address_id
        result = await self._call("search_menu", args)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return result.get("items", [])
        return []

    async def get_food_cart(self) -> dict:
        """View current cart + bill breakdown."""
        result = await self._call("get_food_cart", {})
        if isinstance(result, dict):
            return result
        return {}

    async def fetch_food_coupons(self) -> list[dict]:
        """
        List available coupons — filters out non-COD coupons.

        architecture §2: COD only in v1. Filter coupons requiring online payment.
        """
        result = await self._call("fetch_food_coupons", {})
        raw: list[dict] = []
        if isinstance(result, list):
            raw = result
        elif isinstance(result, dict):
            raw = result.get("coupons", [])

        # Keep only COD-compatible coupons
        return [c for c in raw if _is_cod_compatible(c)]

    async def track_food_order(self, order_id: str) -> dict:
        """Track order status — read-only."""
        result = await self._call("track_food_order", {"orderId": order_id})
        if isinstance(result, dict):
            return result
        return {}

    async def get_food_orders(self) -> list[dict]:
        """Order history — used by idempotency guard before retrying the ordering endpoint."""
        result = await self._call("get_food_orders", {})
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return result.get("orders", [])
        return []

    # ── Phase 9 Write Tools ───────────────────────────────────────────────────

    async def update_food_cart(self, items: list[dict], restaurant_id: str, address_id: str) -> dict:
        """Add, remove, or update items in the cart."""
        return await self._call("update_food_cart", {
            "items": items,
            "restaurantId": restaurant_id,
            "addressId": address_id
        })

    async def flush_food_cart(self) -> dict:
        """Clear the cart completely."""
        return await self._call("flush_food_cart", {})

    async def apply_food_coupon(self, coupon_code: str) -> dict:
        """Apply a coupon to the current cart."""
        return await self._call("apply_food_coupon", {"couponCode": coupon_code})

    # ── Retry core ─────────────────────────────────────────────────────────────

    async def _call(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """
        Call a Swiggy tool with 3× exponential backoff retry on 5xx / timeout.

        Test overrides are subject to the same retry logic — they can raise
        SwiggyApiError / ConnectionError to simulate transient failures.

        Raises:
            SwiggyUnavailableError: After all retries exhausted.
        """
        last_error: Exception | None = None
        for attempt, backoff in enumerate((*_RETRY_BACKOFF, None), start=1):
            try:
                start = asyncio.get_event_loop().time()

                # Override path (test injection) — same retry semantics
                if tool_name in self._tool_overrides:
                    result = await self._tool_overrides[tool_name](arguments)
                else:
                    result = await self._api.call_tool(tool_name, arguments)

                elapsed_ms = int((asyncio.get_event_loop().time() - start) * 1000)
                log.info(
                    "swiggy_tool_ok",
                    tool=tool_name,
                    attempt=attempt,
                    latency_ms=elapsed_ms,
                )
                return result

            except SwiggyApiError as exc:
                last_error = exc
                status = getattr(exc, "status_code", None)
                is_retryable = status is None or status >= 500

                log.warning(
                    "swiggy_tool_error",
                    tool=tool_name,
                    attempt=attempt,
                    status_code=status,
                    error=str(exc),
                    retrying=is_retryable and backoff is not None,
                )

                if not is_retryable:
                    # 4xx — don't retry, surface immediately
                    raise SwiggyUnavailableError(
                        f"Swiggy {tool_name} failed (non-retryable): {exc}"
                    ) from exc

                if backoff is not None:
                    await asyncio.sleep(backoff)

            except Exception as exc:
                # Transport errors (timeout, connection refused, etc.)
                last_error = exc
                log.warning(
                    "swiggy_transport_error",
                    tool=tool_name,
                    attempt=attempt,
                    error=str(exc),
                    retrying=backoff is not None,
                )
                if backoff is not None:
                    await asyncio.sleep(backoff)

        raise SwiggyUnavailableError(
            f"Swiggy {tool_name} unavailable after {_RETRY_COUNT} attempts: {last_error}"
        ) from last_error


# ── Coupon helpers ─────────────────────────────────────────────────────────────

def _is_cod_compatible(coupon: dict) -> bool:
    """Return True if coupon works with Cash-on-Delivery."""
    # Common field names in Swiggy API responses
    payment_modes = coupon.get("paymentModes") or coupon.get("payment_modes") or []
    if payment_modes:
        modes_lower = [str(m).lower() for m in payment_modes]
        # If online-only is explicitly required, filter out
        if any(m in ("online", "card", "upi", "net_banking") for m in modes_lower):
            if "cod" not in modes_lower and "cash" not in modes_lower:
                return False
    # No restriction or COD explicitly listed → compatible
    return True
