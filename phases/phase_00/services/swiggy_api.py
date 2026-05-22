"""Swiggy Food API client — HTTP JSON-RPC tool calls (not MCP protocol)."""

from __future__ import annotations

import uuid
from typing import Any

import httpx

from phases.phase_00.config import Settings, get_settings
from phases.phase_00.logging_setup import get_logger
from phases.phase_00.services.order_guard import OrderDisabledError, assert_orders_enabled
from phases.phase_00.services.swiggy_auth import SwiggyAuthError, SwiggyAuthService

log = get_logger(__name__)

# Tools that mutate cart or place orders — tracked for safety audits
WRITE_TOOLS = frozenset(
    {
        "update_food_cart",
        "flush_food_cart",
        "apply_food_coupon",
        "place_food_order",
    }
)

# Blocked in Phase 0 — only callable via guarded place_food_order()
ORDER_TOOL = "place_food_order"


class SwiggyApiError(Exception):
    """Swiggy API or transport failure."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class SwiggyApiClient:
    """
    Async HTTP client for Swiggy Food JSON-RPC endpoints.

    Uses POST {SWIGGY_FOOD_URL} with method tools/call per Builders docs.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        auth: SwiggyAuthService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.auth = auth or SwiggyAuthService(self.settings)
        self._request_id = 0

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _require_token(self) -> str:
        token = self.auth.get_access_token()
        if not token:
            raise SwiggyAuthError(
                "Not authenticated. Complete OAuth via GET /auth/swiggy/login"
            )
        return token

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        """
        Call a Swiggy Food tool via JSON-RPC.

        Returns the `data` field from a successful tool response.
        """
        if name == ORDER_TOOL:
            raise SwiggyApiError(
                f"Direct call_tool('{ORDER_TOOL}') is forbidden. "
                "Use place_food_order() after order gate passes."
            )

        return await self._invoke_tool(name, arguments or {})

    async def place_food_order(
        self,
        payment_method: str = "COD",
        **extra_args: Any,
    ) -> Any:
        """
        Place a real food order — gated by ORDER_ENABLED + EVAL_SUITE_PASSED.
        """
        assert_orders_enabled()
        args = {"payment_method": payment_method, **extra_args}
        return await self._invoke_tool(ORDER_TOOL, args)

    async def get_addresses(self) -> Any:
        """Convenience wrapper for Phase 0 smoke test."""
        return await self.call_tool("get_addresses", {})

    async def _invoke_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        token = self._require_token()
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
            "id": self._next_id(),
        }

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        url = self.settings.swiggy_food_url.rstrip("/")
        log.info("swiggy_tool_call", tool=name, write=name in WRITE_TOOLS)

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, json=payload, headers=headers)

        if response.status_code == 401:
            raise SwiggyAuthError("Swiggy API returned 401 — re-run OAuth")
        if response.status_code >= 400:
            raise SwiggyApiError(
                f"HTTP {response.status_code}: {response.text}",
                status_code=response.status_code,
            )

        body = response.json()

        # JSON-RPC error envelope
        if "error" in body:
            err = body["error"]
            msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            raise SwiggyApiError(f"JSON-RPC error: {msg}")

        result = body.get("result", body)

        # Tool-level success/data envelope (per Builders docs)
        if isinstance(result, dict):
            if result.get("success") is False:
                error = result.get("error", {})
                msg = (
                    error.get("message", str(error))
                    if isinstance(error, dict)
                    else str(error)
                )
                raise SwiggyApiError(f"Tool {name} failed: {msg}")
            if "data" in result:
                return result["data"]
            # Some responses nest content in result directly
            if "content" in result:
                return result["content"]

        return result
