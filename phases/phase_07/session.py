"""Session store for Phase 7 — in-memory with disk snapshots.

Sessions are kept in memory for speed but snapshotted to .sessions/<id>.json
so that uvicorn --reload (or a crash) doesn't wipe address_id, cart state, or
conversation history mid-session. Snapshots are loaded lazily on first miss.
"""

import json
from pathlib import Path

from phases.phase_01.models.intent import UserIntent
from phases.phase_01.models.state import ConversationState

_sessions: dict[str, ConversationState] = {}

_SESSIONS_DIR = Path(__file__).resolve().parents[2] / ".sessions"


def _session_file(session_id: str) -> Path:
    # Session IDs are client-generated — strip path separators defensively
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_")
    return _SESSIONS_DIR / f"{safe}.json"


def save_session(state: ConversationState) -> None:
    """Snapshot session state to disk. Failures are non-fatal."""
    try:
        _SESSIONS_DIR.mkdir(exist_ok=True)
        # current_intent may hold a live UserIntent object — normalise to dict
        if isinstance(state.current_intent, UserIntent):
            state.current_intent = state.current_intent.model_dump()
        _session_file(state.session_id).write_text(
            state.model_dump_json(), encoding="utf-8"
        )
    except Exception:
        pass  # persistence is best-effort; in-memory state is the live copy


def _load_session(session_id: str) -> ConversationState | None:
    path = _session_file(session_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return ConversationState.model_validate(data)
    except Exception:
        return None


def get_session(session_id: str) -> ConversationState:
    """Retrieve or create a conversation state (memory → disk → new)."""
    if session_id not in _sessions:
        state = _load_session(session_id) or ConversationState(session_id=session_id)
        _sessions[session_id] = state
    return _sessions[session_id]


def clear_session(session_id: str) -> None:
    if session_id in _sessions:
        del _sessions[session_id]
    try:
        _session_file(session_id).unlink(missing_ok=True)
    except Exception:
        pass
