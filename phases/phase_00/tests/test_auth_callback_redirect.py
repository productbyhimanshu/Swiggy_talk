"""The OAuth routes always land users on the app — never a raw error page."""

import time

import pytest
from fastapi.testclient import TestClient

from phases.phase_00 import main as main_mod
from phases.phase_00.services.identity import COOKIE_NAME, _sign
from phases.phase_00.services.swiggy_auth import OAUTH_COOKIE, SwiggyAuthError
from phases.phase_00.services.token_store import SqliteTokenStore, set_token_store


@pytest.fixture
def client(clean_env, monkeypatch, tmp_path):
    from phases.phase_00.services import token_store

    monkeypatch.setattr(token_store, "_DB_PATH", tmp_path / "user.db")
    set_token_store(SqliteTokenStore())
    monkeypatch.setenv("FRONTEND_URL", "https://bhook.example.com/")
    main_mod.get_settings.cache_clear()
    return TestClient(main_mod.app)


def _get_callback(client, **cookies):
    return client.get(
        "/auth/callback", params={"code": "c", "state": "s"},
        cookies=cookies, follow_redirects=False,
    )


def test_success_redirects_with_connected_flag(client, monkeypatch):
    async def ok(self, code, state, pending):
        assert pending == "pending-cookie"

    monkeypatch.setattr(main_mod.SwiggyAuthService, "exchange_code", ok)
    r = _get_callback(client, **{OAUTH_COOKIE: "pending-cookie"})
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "https://bhook.example.com/?connected=1"


def test_failure_redirects_with_auth_error_not_json(client, monkeypatch):
    async def fail(self, code, state, pending):
        raise SwiggyAuthError("Unknown or expired state.")

    monkeypatch.setattr(main_mod.SwiggyAuthService, "exchange_code", fail)
    r = _get_callback(client)
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "https://bhook.example.com/?auth_error=1"


def test_replayed_callback_for_connected_user_opens_app(client, monkeypatch):
    async def fail(self, code, state, pending):
        raise SwiggyAuthError("Unknown or expired state.")

    monkeypatch.setattr(main_mod.SwiggyAuthService, "exchange_code", fail)
    from phases.phase_00.services.token_store import get_token_store
    get_token_store().set("u_already", "tok", time.time() + 3600)

    r = _get_callback(client, **{COOKIE_NAME: _sign("u_already")})
    assert r.headers["location"] == "https://bhook.example.com/?connected=1"


def test_login_sets_short_lived_pending_cookie(client, monkeypatch):
    monkeypatch.setattr(
        main_mod.SwiggyAuthService, "build_authorization_url",
        lambda self: ("https://mcp.swiggy.com/auth/authorize?x=1", "st", "pending-value"),
    )
    r = client.get("/auth/swiggy/login", follow_redirects=False)
    assert r.headers["location"].startswith("https://mcp.swiggy.com/")
    set_cookies = r.headers.get_list("set-cookie")
    pending = next(c for c in set_cookies if c.startswith(f"{OAUTH_COOKIE}="))
    assert "HttpOnly" in pending and "Path=/auth" in pending and "Max-Age=600" in pending
