"""Resolve delivery address from Swiggy get_addresses into session."""

from typing import Any

from phases.phase_00.logging_setup import get_logger
from phases.phase_00.services.swiggy_api import SwiggyApiClient, SwiggyApiError
from phases.phase_00.services.swiggy_auth import SwiggyAuthError
from phases.phase_01.models.state import ConversationState
from phases.phase_01.services.session import get_session

log = get_logger(__name__)


def _extract_address_id(entry: Any) -> str | None:
    if not isinstance(entry, dict):
        return None
    for key in ("id", "addressId", "address_id"):
        val = entry.get(key)
        if val is not None:
            return str(val)
    return None


def pick_default_address(addresses: Any) -> str | None:
    """
    Choose address from get_addresses payload.
    Swiggy returns a list sorted by last order date — first is default.
    """
    if isinstance(addresses, list) and addresses:
        return _extract_address_id(addresses[0])
    if isinstance(addresses, dict):
        items = addresses.get("addresses") or addresses.get("data")
        if isinstance(items, list) and items:
            return _extract_address_id(items[0])
    return None


async def resolve_session_address(
    session_id: str,
    *,
    client: SwiggyApiClient | None = None,
) -> ConversationState:
    """
    Call get_addresses and store address_id on session.
    Raises SwiggyAuthError / SwiggyApiError on failure.
    """
    state = get_session(session_id, touch=True)
    api = client or SwiggyApiClient()

    try:
        data = await api.get_addresses()
    except (SwiggyAuthError, SwiggyApiError):
        log.warning("resolve_address_failed", session_id=session_id)
        raise

    address_id = pick_default_address(data)
    if not address_id:
        log.warning("resolve_address_empty", session_id=session_id)
        raise SwiggyApiError("No saved addresses returned from Swiggy")

    state.address_id = address_id
    log.info("address_resolved", session_id=session_id, address_id=address_id)
    return state
