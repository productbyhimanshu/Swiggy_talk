"""In-progress login travels in a signed cookie bound to the uid that started it."""

import time

import pytest

from phases.phase_00.services import swiggy_auth as sa
from phases.phase_00.services.identity import current_uid_var, sign_payload
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
def fake_swiggy_token_endpoint(monkeypatch):
    class _Resp:
        status_code = 200
        def json(self):
            return {"access_token": "swiggy_tok", "expires_in": 3600}

    class _Client:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, headers=None): return _Resp()

    monkeypatch.setattr(sa.httpx, "AsyncClient", _Client)


def _start_login_as(uid: str) -> tuple[str, str]:
    tok = current_uid_var.set(uid)
    try:
        _url, state, cookie = SwiggyAuthService().build_authorization_url()
        return state, cookie
    finally:
        current_uid_var.reset(tok)


async def _finish_login_as(uid: str, state, cookie) -> None:
    tok = current_uid_var.set(uid)
    try:
        await SwiggyAuthService().exchange_code("code", state, cookie)
    finally:
        current_uid_var.reset(tok)


@pytest.mark.asyncio
async def test_valid_callback_stores_token(clean_env, fresh_store, fake_swiggy_token_endpoint):
    state, cookie = _start_login_as("u_alice")
    await _finish_login_as("u_alice", state, cookie)
    rec = fresh_store.get("u_alice")
    assert rec is not None and rec.access_token == "swiggy_tok"


@pytest.mark.asyncio
async def test_login_survives_server_restart(clean_env, fresh_store, fake_swiggy_token_endpoint):
    # A restart wipes server memory; the login must need only the cookie.
    assert not any(
        isinstance(v, dict) and not k.startswith("__") for k, v in vars(sa).items()
    ), "swiggy_auth must not keep login state in module-level dicts"
    state, cookie = _start_login_as("u_alice")
    await _finish_login_as("u_alice", state, cookie)  # fresh service instance
    assert fresh_store.get("u_alice") is not None


@pytest.mark.asyncio
async def test_other_users_login_cookie_rejected(clean_env, fresh_store):
    state, cookie = _start_login_as("u_alice")
    with pytest.raises(SwiggyAuthError, match="not belong"):
        await _finish_login_as("u_bob", state, cookie)
    assert fresh_store.get("u_alice") is None and fresh_store.get("u_bob") is None


@pytest.mark.asyncio
async def test_missing_cookie_rejected(clean_env, fresh_store):
    state, _cookie = _start_login_as("u_x")
    with pytest.raises(SwiggyAuthError, match="Unknown or expired"):
        await _finish_login_as("u_x", state, None)


@pytest.mark.asyncio
async def test_tampered_cookie_rejected(clean_env, fresh_store):
    state, cookie = _start_login_as("u_x")
    body, mac = cookie.rsplit(".", 1)
    with pytest.raises(SwiggyAuthError, match="Unknown or expired"):
        await _finish_login_as("u_x", state, body[:-2] + "AA." + mac)


@pytest.mark.asyncio
async def test_state_mismatch_rejected(clean_env, fresh_store):
    _state, cookie = _start_login_as("u_x")
    with pytest.raises(SwiggyAuthError, match="mismatch"):
        await _finish_login_as("u_x", "some-other-state", cookie)


@pytest.mark.asyncio
async def test_expired_login_rejected(clean_env, fresh_store):
    old = sign_payload(
        sa.OAUTH_COOKIE_PURPOSE,
        {"s": "st", "v": "ver", "u": "u_x", "t": time.time() - sa.STATE_TTL_SECONDS - 60},
    )
    with pytest.raises(SwiggyAuthError, match="Unknown or expired"):
        await _finish_login_as("u_x", "st", old)
