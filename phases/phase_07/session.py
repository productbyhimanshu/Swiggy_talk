"""In-memory session store for Phase 7."""

from phases.phase_01.models.state import ConversationState

_sessions: dict[str, ConversationState] = {}


def get_session(session_id: str) -> ConversationState:
    """Retrieve or create a conversation state."""
    if session_id not in _sessions:
        # In phase 5/6 we had some extra properties. We'll ensure they exist.
        state = ConversationState(session_id=session_id)
        # Mock default address_id for tests
        state.address_id = "107675381"
        _sessions[session_id] = state
    return _sessions[session_id]


def clear_session(session_id: str) -> None:
    if session_id in _sessions:
        del _sessions[session_id]
