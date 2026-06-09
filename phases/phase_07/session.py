"""In-memory session store for Phase 7."""

from phases.phase_01.models.state import ConversationState

_sessions: dict[str, ConversationState] = {}


def get_session(session_id: str) -> ConversationState:
    """Retrieve or create a conversation state."""
    if session_id not in _sessions:
        # address_id starts as None — resolved via get_addresses + user pick
        state = ConversationState(session_id=session_id)
        _sessions[session_id] = state
    return _sessions[session_id]


def clear_session(session_id: str) -> None:
    if session_id in _sessions:
        del _sessions[session_id]
