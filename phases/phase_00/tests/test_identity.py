"""Multi-user identity: signed cookie + contextvar + middleware."""

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from phases.phase_00.services.identity import (
    COOKIE_NAME,
    IdentityMiddleware,
    _sign,
    _verify,
    current_uid_var,
    mint_uid,
)


def _make_app():
    app = FastAPI()
    app.add_middleware(IdentityMiddleware)

    @app.get("/whoami")
    async def whoami(request: Request):
        return {"uid": current_uid_var.get()}

    return app


def test_fresh_visitor_gets_signed_cookie(clean_env):
    client = TestClient(_make_app())
    r = client.get("/whoami")
    assert r.status_code == 200
    uid = r.json()["uid"]
    assert uid.startswith("u_") and len(uid) >= 10

    # Response set a cookie whose value is <uid>.<sig>
    raw = r.cookies.get(COOKIE_NAME)
    assert raw is not None
    assert _verify(raw) == uid


def test_valid_cookie_is_preserved(clean_env):
    client = TestClient(_make_app())
    uid = "u_known_user_xyz"
    signed = _sign(uid)
    r = client.get("/whoami", cookies={COOKIE_NAME: signed})
    assert r.json()["uid"] == uid
    # Already valid — middleware should NOT re-issue the cookie
    assert COOKIE_NAME not in r.cookies


def test_tampered_cookie_treated_as_new_user(clean_env):
    client = TestClient(_make_app())
    r = client.get("/whoami", cookies={COOKIE_NAME: "u_fake.not_a_real_sig"})
    assert r.status_code == 200
    new_uid = r.json()["uid"]
    assert new_uid != "u_fake"
    # And a fresh cookie was issued
    assert COOKIE_NAME in r.cookies


def test_two_cookies_two_uids(clean_env):
    # Two separate clients so cookie jars are isolated — simulating two browsers.
    app = _make_app()
    a = TestClient(app).get("/whoami")
    b = TestClient(app).get("/whoami")
    assert a.json()["uid"] != b.json()["uid"]


def test_mint_uid_is_unique(clean_env):
    assert mint_uid() != mint_uid()


def test_missing_secret_uses_unguessable_key(clean_env, monkeypatch):
    import hashlib
    import hmac as _hmac
    import base64

    from phases.phase_00.config import get_settings

    monkeypatch.setenv("SESSION_SECRET", "")
    get_settings.cache_clear()

    signed = _sign("u_victim")
    assert _verify(signed) == "u_victim"  # still works within this process

    # A cookie forged with any well-known string must not validate.
    for guess in ("dev-fallback-do-not-use-in-prod", "", "secret"):
        mac = _hmac.new(guess.encode(), b"u_victim", hashlib.sha256).digest()
        forged = "u_victim." + base64.urlsafe_b64encode(mac).rstrip(b"=").decode()
        assert _verify(forged) is None
