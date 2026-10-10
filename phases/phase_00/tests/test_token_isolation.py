"""Two users → two different Swiggy tokens, no cross-read."""

import time

import pytest

from phases.phase_00.services.identity import current_uid_var
from phases.phase_00.services.swiggy_auth import SwiggyAuthService
from phases.phase_00.services.token_store import SqliteTokenStore, set_token_store


@pytest.fixture
def fresh_store(tmp_path, monkeypatch):
    from phases.phase_00.services import token_store

    monkeypatch.setattr(token_store, "_DB_PATH", tmp_path / "user.db")
    store = SqliteTokenStore()
    set_token_store(store)
    yield store


def test_two_users_separate_tokens(clean_env, fresh_store):
    expires = time.time() + 3600
    fresh_store.set("u_alice", "tok_ALICE", expires)
    fresh_store.set("u_bob",   "tok_BOB",   expires)

    auth = SwiggyAuthService(store=fresh_store)

    tok_alice = current_uid_var.set("u_alice")
    try:
        assert auth.get_access_token() == "tok_ALICE"
    finally:
        current_uid_var.reset(tok_alice)

    tok_bob = current_uid_var.set("u_bob")
    try:
        assert auth.get_access_token() == "tok_BOB"
    finally:
        current_uid_var.reset(tok_bob)


def test_missing_user_returns_none(clean_env, fresh_store):
    auth = SwiggyAuthService(store=fresh_store)
    t = current_uid_var.set("u_nobody")
    try:
        assert auth.get_access_token() is None
    finally:
        current_uid_var.reset(t)


def test_expired_token_returns_none(clean_env, fresh_store):
    fresh_store.set("u_x", "tok_X", time.time() - 10)  # already expired
    auth = SwiggyAuthService(store=fresh_store)
    t = current_uid_var.set("u_x")
    try:
        assert auth.get_access_token() is None
    finally:
        current_uid_var.reset(t)


def test_logout_deletes_only_this_user(clean_env, fresh_store):
    now = time.time() + 3600
    fresh_store.set("u_a", "tok_A", now)
    fresh_store.set("u_b", "tok_B", now)

    auth = SwiggyAuthService(store=fresh_store)
    t = current_uid_var.set("u_a")
    try:
        auth.logout()
    finally:
        current_uid_var.reset(t)

    assert fresh_store.get("u_a") is None
    assert fresh_store.get("u_b") is not None
