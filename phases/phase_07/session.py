"""Session store for Phase 7 — in-memory with disk snapshots.

Sessions are kept in memory for speed but snapshotted to .sessions/<id>.json
so that uvicorn --reload (or a crash) doesn't wipe address_id, cart state, or
conversation history mid-session. Snapshots are loaded lazily on first miss.
"""

import json
from datetime import datetime
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
        state = ConversationState.model_validate(data)
        # Reloading from disk = user came back. Drop cached search results
        # (they're stale) and mark activity now so the staleness gate in
        # phase_07/router.py doesn't dead-end the next user message into
        # the "session timed out" bubble.
        state.cached_results = []
        state.has_recommendations = False
        state.last_activity = datetime.now()
        return state
    except Exception:
        return None


def _last_used_address_id() -> str | None:
    """Find the most recently saved address_id across all session snapshots."""
    try:
        snapshots = sorted(_SESSIONS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for snap in snapshots[:10]:
            try:
                data = json.loads(snap.read_text(encoding="utf-8"))
                addr = data.get("address_id")
                if addr:
                    return addr
            except Exception:
                continue
    except Exception:
        pass
    return None


def get_session(session_id: str) -> ConversationState:
    """Retrieve or create a conversation state (memory → disk → new)."""
    if session_id not in _sessions:
        state = _load_session(session_id)
        if state is None:
            state = ConversationState(session_id=session_id)
            # Seed address from the most recent session so users don't have to
            # re-select their address after every server restart / page refresh.
            state.address_id = _last_used_address_id()
        _sessions[session_id] = state
    return _sessions[session_id]


def clear_session(session_id: str) -> None:
    if session_id in _sessions:
        del _sessions[session_id]
    try:
        _session_file(session_id).unlink(missing_ok=True)
    except Exception:
        pass
