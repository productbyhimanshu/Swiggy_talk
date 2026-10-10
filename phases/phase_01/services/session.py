"""In-memory session store with staleness checks — uid-scoped."""

from phases.phase_00.config import get_settings
from phases.phase_00.logging_setup import get_logger
from phases.phase_00.services.identity import current_uid_var
from phases.phase_01.models.state import (
    ConversationState,
    SessionOwnershipError,
    check_staleness,
)

log = get_logger(__name__)

_sessions: dict[str, ConversationState] = {}


def _active_uid() -> str:
    try:
        return current_uid_var.get() or ""
    except LookupError:
        return ""


def create_session(session_id: str) -> ConversationState:
    uid = _active_uid()
    state = ConversationState(session_id=session_id, uid=uid)
    _sessions[session_id] = state
    log.info("session_created", session_id=session_id, uid=uid[:8])
    return state


def _ensure_ownership(state: ConversationState, uid: str) -> None:
    if not uid:
        return
    if not state.uid:
        state.uid = uid
        return
    if state.uid != uid:
        raise SessionOwnershipError(
            f"Session {state.session_id} does not belong to this user."
        )


def get_session(session_id: str, *, touch: bool = True) -> ConversationState:
    """
    Return session, creating if missing.
    Runs staleness check; updates last_activity when touch=True.
    Raises SessionOwnershipError if a different user tries to open it.
    """
    uid = _active_uid()
    if session_id not in _sessions:
        return create_session(session_id)

    state = _sessions[session_id]
    _ensure_ownership(state, uid)

    stale = check_staleness(state)
    if stale:
        log.info("session_stale", session_id=session_id)

    if touch:
        state.touch_activity()

    return state


def delete_session(session_id: str) -> bool:
    if session_id in _sessions:
        del _sessions[session_id]
        log.info("session_deleted", session_id=session_id)
        return True
    return False


def session_exists(session_id: str) -> bool:
    return session_id in _sessions


def list_session_ids() -> list[str]:
    return list(_sessions.keys())


def clear_all_sessions() -> None:
    """Test helper — wipe in-memory store."""
    _sessions.clear()


def is_session_timed_out(state: ConversationState) -> bool:
    """True if last activity exceeds configured timeout (before touch)."""
    from datetime import datetime, timedelta

    timeout = get_settings().session_timeout_minutes
    return datetime.now() - state.last_activity > timedelta(minutes=timeout)
