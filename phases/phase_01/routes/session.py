"""Session API — create, inspect, resolve Swiggy address."""

import uuid

from fastapi import APIRouter, HTTPException

from phases.phase_00.logging_setup import get_logger
from phases.phase_00.services.swiggy_api import SwiggyApiError
from phases.phase_00.services.swiggy_auth import SwiggyAuthError
from phases.phase_01.services.address import resolve_session_address
from phases.phase_01.services.session import create_session, delete_session, get_session

log = get_logger(__name__)

router = APIRouter(prefix="/api/session", tags=["session"])


@router.post("")
async def create_new_session():
    """Create a new chat session."""
    session_id = str(uuid.uuid4())
    state = create_session(session_id)
    return state.to_public_dict()


@router.get("/{session_id}")
async def read_session(session_id: str):
    """Return public session fields (no cart/cache payloads)."""
    state = get_session(session_id, touch=False)
    return state.to_public_dict()


@router.post("/{session_id}/resolve-address")
async def resolve_address(session_id: str):
    """Call Swiggy get_addresses and set address_id on session."""
    get_session(session_id, touch=False)
    try:
        state = await resolve_session_address(session_id)
    except SwiggyAuthError as exc:
        raise HTTPException(
            status_code=401,
            detail=str(exc),
        ) from exc
    except SwiggyApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "session_id": session_id,
        "address_id": state.address_id,
    }


@router.delete("/{session_id}")
async def remove_session(session_id: str):
    if not delete_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True}
