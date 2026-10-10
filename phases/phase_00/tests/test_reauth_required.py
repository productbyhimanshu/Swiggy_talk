"""Swiggy 401 inside the API client → ReauthRequired → stored token wiped."""

import time
from unittest.mock import patch

import httpx
import pytest

from phases.phase_00.services import swiggy_api
from phases.phase_00.services.identity import current_uid_var
from phases.phase_00.services.swiggy_api import SwiggyApiClient
from phases.phase_00.services.swiggy_auth import ReauthRequired
from phases.phase_00.services.token_store import SqliteTokenStore, set_token_store


@pytest.fixture
def fresh_store(tmp_path, monkeypatch):
    from phases.phase_00.services import token_store

    monkeypatch.setattr(token_store, "_DB_PATH", tmp_path / "user.db")
    store = SqliteTokenStore()
    set_token_store(store)
    yield store


class _Resp:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body or {}
        self.text = "boom"
    def json(self):
        return self._body


class _Client:
    def __init__(self, status, body=None):
        self._status = status
        self._body = body
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def post(self, url, json=None, headers=None):
        return _Resp(self._status, self._body)


@pytest.mark.asyncio
async def test_401_raises_reauth_and_deletes_token(clean_env, fresh_store, monkeypatch):
    fresh_store.set("u_a", "tok_live", time.time() + 3600)
    monkeypatch.setattr(
        swiggy_api.httpx,
        "AsyncClient",
        lambda *a, **kw: _Client(401),
    )

    tok = current_uid_var.set("u_a")
    try:
        with pytest.raises(ReauthRequired):
            await SwiggyApiClient().call_tool("search_restaurants")
    finally:
        current_uid_var.reset(tok)

    # 401 wiped the stored token so the user must re-auth
    assert fresh_store.get("u_a") is None


@pytest.mark.asyncio
async def test_419_also_raises_reauth(clean_env, fresh_store, monkeypatch):
    fresh_store.set("u_b", "tok_live", time.time() + 3600)
    monkeypatch.setattr(
        swiggy_api.httpx,
        "AsyncClient",
        lambda *a, **kw: _Client(419),
    )

    tok = current_uid_var.set("u_b")
    try:
        with pytest.raises(ReauthRequired):
            await SwiggyApiClient().call_tool("search_restaurants")
    finally:
        current_uid_var.reset(tok)
    assert fresh_store.get("u_b") is None


@pytest.mark.asyncio
async def test_no_token_raises_reauth(clean_env, fresh_store):
    tok = current_uid_var.set("u_c")  # never had a token
    try:
        with pytest.raises(ReauthRequired):
            await SwiggyApiClient().call_tool("search_restaurants")
    finally:
        current_uid_var.reset(tok)
