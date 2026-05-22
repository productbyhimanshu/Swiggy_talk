"""Phase 1.E1 / 1.E2 — ConversationState and staleness."""

from datetime import datetime, timedelta

from phases.phase_01.models.state import ConversationState, check_staleness


def test_staleness_clears_cached_fields():
    state = ConversationState(session_id="s1")
    state.has_recommendations = True
    state.cached_results = [{"id": "r1"}]
    state.current_restaurant_id = "rest_99"
    state.last_activity = datetime.now() - timedelta(minutes=31)

    assert check_staleness(state, timeout_minutes=30) is True
    assert state.cached_results == []
    assert state.has_recommendations is False
    assert state.current_restaurant_id is None


def test_staleness_false_when_recent():
    state = ConversationState(session_id="s2")
    state.has_recommendations = True
    state.cached_results = [{"id": "r1"}]
    state.last_activity = datetime.now() - timedelta(minutes=5)

    assert check_staleness(state, timeout_minutes=30) is False
    assert state.cached_results == [{"id": "r1"}]
    assert state.has_recommendations is True


def test_context_window_last_six_only():
    state = ConversationState(session_id="s3")
    for i in range(10):
        state.append_message("user", f"msg-{i}")

    window = state.get_context_window()
    assert len(window) == 6
    assert window[0]["text"] == "msg-4"
    assert window[-1]["text"] == "msg-9"


def test_append_message_updates_activity():
    state = ConversationState(session_id="s4")
    old = state.last_activity
    state.append_message("user", "hello")
    assert state.last_activity >= old
    assert len(state.message_history) == 1
