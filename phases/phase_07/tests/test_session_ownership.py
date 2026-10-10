"""A session created by uid A cannot be opened by uid B."""

import pytest

from phases.phase_00.services.identity import current_uid_var
from phases.phase_01.models.state import SessionOwnershipError
from phases.phase_07 import session as sess


@pytest.fixture(autouse=True)
def isolated_sessions(tmp_path, monkeypatch):
    monkeypatch.setattr(sess, "_SESSIONS_DIR", tmp_path / ".sessions")
    sess._sessions.clear()
    yield
    sess._sessions.clear()


def _as(uid, fn, *args, **kw):
    tok = current_uid_var.set(uid)
    try:
        return fn(*args, **kw)
    finally:
        current_uid_var.reset(tok)


def test_other_user_gets_404(clean_env):
    state_a = _as("u_alice", sess.get_session, "sess-xyz")
    assert state_a.uid == "u_alice"

    with pytest.raises(SessionOwnershipError):
        _as("u_bob", sess.get_session, "sess-xyz")


def test_owner_can_reopen(clean_env):
    state_a1 = _as("u_alice", sess.get_session, "sess-abc")
    state_a2 = _as("u_alice", sess.get_session, "sess-abc")
    assert state_a1 is state_a2


def test_session_without_uid_bound_on_first_open(clean_env):
    # Legacy snapshot path — uid empty on model, gets bound on read.
    from phases.phase_01.models.state import ConversationState
    stub = ConversationState(session_id="legacy")
    sess._sessions["legacy"] = stub

    state = _as("u_newcomer", sess.get_session, "legacy")
    assert state.uid == "u_newcomer"

    # Someone else now locked out
    with pytest.raises(SessionOwnershipError):
        _as("u_stranger", sess.get_session, "legacy")
