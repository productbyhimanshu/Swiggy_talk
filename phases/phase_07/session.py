"""Session store for Phase 7 — in-memory with disk snapshots, uid-scoped.

Sessions are kept in memory for speed but snapshotted to .sessions/<id>.json
so that uvicorn --reload (or a crash) doesn't wipe address_id, cart state, or
conversation history mid-session.

Multi-user rules:
  • Every ConversationState carries a uid (the signed-cookie identity).
  • Sessions created without a current uid (CLI/tests) have uid="".
  • A read with a mismatched uid raises SessionOwnershipError → the router
    maps that to HTTP 404.
"""

import json
from datetime import datetime
from pathlib import Path

from phases.phase_00.services.identity import current_uid_var
from phases.phase_01.models.intent import UserIntent
from phases.phase_01.models.state import ConversationState, SessionOwnershipError

_sessions: dict[str, ConversationState] = {}

_SESSIONS_DIR = Path(__file__).resolve().parents[2] / ".sessions"


def _session_file(session_id: str) -> Path:
    # Session IDs are client-generated — strip path separators defensively
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_")
    return _SESSIONS_DIR / f"{safe}.json"


def _active_uid() -> str:
    try:
        return current_uid_var.get() or ""
    except LookupError:
        return ""


def save_session(state: ConversationState) -> None:
    """Snapshot session state to disk. Failures are non-fatal."""
    try:
        _SESSIONS_DIR.mkdir(exist_ok=True)
        if isinstance(state.current_intent, UserIntent):
            state.current_intent = state.current_intent.model_dump()
        _session_file(state.session_id).write_text(
            state.model_dump_json(), encoding="utf-8"
        )
    except Exception:
        pass


def _load_session(session_id: str) -> ConversationState | None:
    path = _session_file(session_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        state = ConversationState.model_validate(data)
        state.cached_results = []
        state.has_recommendations = False
        state.last_activity = datetime.now()
        return state
    except Exception:
        return None


def _last_used_address_id(uid: str) -> str | None:
    """Most recently used address_id for THIS user — never leaks across users."""
    if not uid:
        return None
    try:
        snapshots = sorted(
            _SESSIONS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        for snap in snapshots[:30]:
            try:
                data = json.loads(snap.read_text(encoding="utf-8"))
                if data.get("uid") != uid:
                    continue
                addr = data.get("address_id")
                if addr:
                    return addr
            except Exception:
                continue
    except Exception:
        pass
    return None


def _ensure_ownership(state: ConversationState, current_uid: str) -> None:
    """Validate that `current_uid` owns `state`. Raises SessionOwnershipError on mismatch.

    An existing state with no uid (pre-multiuser snapshot) is bound to the
    current uid on first read and persisted — one-shot migration.
    """
    if not current_uid:
        # CLI / test path — ownership isn't enforced.
        return
    if not state.uid:
        state.uid = current_uid
        save_session(state)
        return
    if state.uid != current_uid:
        raise SessionOwnershipError(
            f"Session {state.session_id} does not belong to this user."
        )


def get_session(session_id: str) -> ConversationState:
    """Retrieve or create the state for THIS user's session_id."""
    uid = _active_uid()

    if session_id in _sessions:
        state = _sessions[session_id]
        _ensure_ownership(state, uid)
        return state

    state = _load_session(session_id)
    if state is None:
        state = ConversationState(session_id=session_id, uid=uid)
        state.address_id = _last_used_address_id(uid)
    else:
        _ensure_ownership(state, uid)
    _sessions[session_id] = state
    return state


def clear_session(session_id: str) -> None:
    if session_id in _sessions:
        del _sessions[session_id]
    try:
        _session_file(session_id).unlink(missing_ok=True)
    except Exception:
        pass
