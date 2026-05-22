"""Phase 1.E3 — session store and timeout."""

from datetime import datetime, timedelta

import pytest

from phases.phase_01.models.state import ConversationState
from phases.phase_01.services.session import (
    clear_all_sessions,
    create_session,
    delete_session,
    get_session,
    is_session_timed_out,
    session_exists,
)


@pytest.fixture(autouse=True)
def _clean_sessions():
    clear_all_sessions()
    yield
    clear_all_sessions()


def test_new_session_defaults():
    state = create_session("abc")
    assert state.session_id == "abc"
    assert state.address_id is None
    assert state.cart_has_items is False
    assert state.message_history == []
    assert session_exists("abc")


def test_get_session_creates_missing():
    state = get_session("new-id")
    assert state.session_id == "new-id"
    assert session_exists("new-id")


def test_get_session_touch_updates_activity():
    state = create_session("touch")
    state.last_activity = datetime.now() - timedelta(minutes=10)
    get_session("touch", touch=True)
    assert is_session_timed_out(state) is False


def test_is_session_timed_out():
    state = create_session("timeout")
    state.last_activity = datetime.now() - timedelta(minutes=35)
    assert is_session_timed_out(state) is True


def test_get_session_clears_stale_cache(monkeypatch):
    state = create_session("stale")
    state.has_recommendations = True
    state.cached_results = [{"x": 1}]
    state.last_activity = datetime.now() - timedelta(minutes=35)

    refreshed = get_session("stale", touch=True)
    assert refreshed.has_recommendations is False
    assert refreshed.cached_results == []


def test_delete_session():
    create_session("del")
    assert delete_session("del") is True
    assert session_exists("del") is False
    assert delete_session("del") is False
