"""In-memory session store with staleness checks."""

from phases.phase_00.config import get_settings
from phases.phase_00.logging_setup import get_logger
from phases.phase_01.models.state import ConversationState, check_staleness

log = get_logger(__name__)

_sessions: dict[str, ConversationState] = {}


def create_session(session_id: str) -> ConversationState:
    state = ConversationState(session_id=session_id)
    _sessions[session_id] = state
    log.info("session_created", session_id=session_id)
    return state


def get_session(session_id: str, *, touch: bool = True) -> ConversationState:
    """
    Return session, creating if missing.
    Runs staleness check; updates last_activity when touch=True.
    """
    if session_id not in _sessions:
        return create_session(session_id)

    state = _sessions[session_id]
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
