"""OAuth state binds to the uid that initiated — cross-user state is rejected."""

import time

import httpx
import pytest

from phases.phase_00.services import swiggy_auth as sa
from phases.phase_00.services.identity import current_uid_var
from phases.phase_00.services.swiggy_auth import SwiggyAuthError, SwiggyAuthService
from phases.phase_00.services.token_store import SqliteTokenStore, set_token_store


@pytest.fixture
def fresh_store(tmp_path, monkeypatch):
    from phases.phase_00.services import token_store

    monkeypatch.setattr(token_store, "_DB_PATH", tmp_path / "user.db")
    store = SqliteTokenStore()
    store.set_client_id("test-client")
    set_token_store(store)
    yield store


@pytest.fixture
def clean_pending():
    sa._PENDING_AUTH.clear()
    yield
    sa._PENDING_AUTH.clear()


def _build_url_as(uid: str) -> str:
    tok = current_uid_var.set(uid)
    try:
        auth = SwiggyAuthService()
        url, state = auth.build_authorization_url()
        return state
    finally:
        current_uid_var.reset(tok)


@pytest.mark.asyncio
async def test_callback_with_wrong_user_state_rejected(
    clean_env, fresh_store, clean_pending, monkeypatch
):
    # Alice initiates
    state = _build_url_as("u_alice")

    # Bob tries to redeem Alice's state
    tok = current_uid_var.set("u_bob")
    try:
        auth = SwiggyAuthService()
        with pytest.raises(SwiggyAuthError, match="not belong"):
            await auth.exchange_code("fake_code", state)
    finally:
        current_uid_var.reset(tok)

    # Store still has nothing for either user
    assert fresh_store.get("u_alice") is None
    assert fresh_store.get("u_bob") is None


@pytest.mark.asyncio
async def test_unknown_state_rejected(clean_env, fresh_store, clean_pending):
    tok = current_uid_var.set("u_x")
    try:
        auth = SwiggyAuthService()
        with pytest.raises(SwiggyAuthError, match="Unknown or expired"):
            await auth.exchange_code("fake_code", "never-issued-state")
    finally:
        current_uid_var.reset(tok)


@pytest.mark.asyncio
async def test_expired_state_rejected(clean_env, fresh_store, clean_pending):
    state = _build_url_as("u_alice")
    # Backdate the stored entry past the 10-minute TTL
    verifier, uid, _ts = sa._PENDING_AUTH[state]
    sa._PENDING_AUTH[state] = (verifier, uid, time.time() - 11 * 60)

    tok = current_uid_var.set("u_alice")
    try:
        auth = SwiggyAuthService()
        with pytest.raises(SwiggyAuthError, match="Unknown or expired"):
            await auth.exchange_code("fake_code", state)
    finally:
        current_uid_var.reset(tok)


@pytest.mark.asyncio
async def test_valid_callback_stores_token(
    clean_env, fresh_store, clean_pending, monkeypatch
):
    state = _build_url_as("u_alice")

    class _FakeResponse:
        status_code = 200
        def json(self):
            return {"access_token": "swiggy_tok", "expires_in": 3600}

    class _FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, headers=None):
            return _FakeResponse()

    monkeypatch.setattr(sa.httpx, "AsyncClient", _FakeClient)

    tok = current_uid_var.set("u_alice")
    try:
        auth = SwiggyAuthService()
        await auth.exchange_code("real_code", state)
    finally:
        current_uid_var.reset(tok)

    rec = fresh_store.get("u_alice")
    assert rec is not None and rec.access_token == "swiggy_tok"
