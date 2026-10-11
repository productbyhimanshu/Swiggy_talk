"""Signed-cookie identity — the single source of 'who is this request'.

Flow:
  1. Middleware reads the `bhook_uid` cookie, verifies the HMAC signature.
  2. Valid → sets `current_uid_var` for the request.
  3. Missing/tampered → mints a fresh uid, sets `current_uid_var`, and arranges
     to write a new `bhook_uid` cookie on the response.
  4. Any code anywhere calls `get_current_uid()` to look up the active user.

Cookie value is `<uid>.<hmac>` where hmac = base64url(HMAC-SHA256(secret, uid)).
Tampered cookies produce a mismatch and are discarded — the user becomes a
new anonymous identity. We never raise on bad cookies.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from contextvars import ContextVar

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from phases.phase_00.config import get_settings
from phases.phase_00.logging_setup import get_logger

log = get_logger(__name__)

COOKIE_NAME = "bhook_uid"
COOKIE_MAX_AGE = 60 * 60 * 24 * 365  # 1 year

# Marker attribute on request.state when middleware needs to issue a cookie
_SET_COOKIE_ATTR = "_bhook_set_cookie_uid"

current_uid_var: ContextVar[str] = ContextVar("current_uid", default="")


# ── Signing ──────────────────────────────────────────────────────────────────


# Used only when SESSION_SECRET is unset. Random per process, so cookies can't
# be forged from source code; the cost is that a restart signs everyone out.
_EPHEMERAL_SECRET = secrets.token_bytes(32)
_warned_missing_secret = False


def _secret_bytes() -> bytes:
    global _warned_missing_secret
    s = get_settings().session_secret
    if s:
        return s.encode("utf-8")
    if not _warned_missing_secret:
        log.warning(
            "SESSION_SECRET is not set — using a random per-process key; "
            "everyone is signed out on restart. Set SESSION_SECRET."
        )
        _warned_missing_secret = True
    return _EPHEMERAL_SECRET


def _sign(uid: str) -> str:
    mac = hmac.new(_secret_bytes(), uid.encode("utf-8"), hashlib.sha256).digest()
    sig = base64.urlsafe_b64encode(mac).rstrip(b"=").decode("ascii")
    return f"{uid}.{sig}"


def _verify(value: str) -> str | None:
    try:
        uid, sig = value.rsplit(".", 1)
    except ValueError:
        return None
    expected = _sign(uid)
    if not hmac.compare_digest(expected, value):
        return None
    return uid


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _payload_mac(purpose: str, body: str) -> str:
    # `purpose` keeps a signature minted for one cookie from validating another.
    msg = f"{purpose}:{body}".encode("utf-8")
    return _b64(hmac.new(_secret_bytes(), msg, hashlib.sha256).digest())


def sign_payload(purpose: str, payload: dict) -> str:
    """Tamper-proof (not secret-from-the-holder) cookie value for a small dict."""
    body = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{body}.{_payload_mac(purpose, body)}"


def verify_payload(purpose: str, value: str) -> dict | None:
    """Return the dict if the signature checks out, else None. Never raises."""
    try:
        body, mac = value.rsplit(".", 1)
        if not hmac.compare_digest(_payload_mac(purpose, body), mac):
            return None
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def mint_uid() -> str:
    """URL-safe random identifier for a fresh visitor."""
    return "u_" + secrets.token_urlsafe(16)


# ── Request-scoped lookup ────────────────────────────────────────────────────


def get_current_uid() -> str:
    """Return the uid for the current request, or raise RuntimeError if unset."""
    uid = current_uid_var.get()
    if not uid:
        raise RuntimeError(
            "current_uid_var not set — IdentityMiddleware must run before any "
            "code that calls get_current_uid()."
        )
    return uid


# ── Middleware ───────────────────────────────────────────────────────────────


class IdentityMiddleware(BaseHTTPMiddleware):
    """Resolve `bhook_uid` cookie → set current_uid_var → write cookie on new users."""

    async def dispatch(self, request: Request, call_next):
        raw = request.cookies.get(COOKIE_NAME)
        uid = _verify(raw) if raw else None
        issue_new = uid is None

        if issue_new:
            uid = mint_uid()
            log.info("uid_minted uid=%s…", uid[:8])

        token = current_uid_var.set(uid)
        try:
            response: Response = await call_next(request)
        finally:
            current_uid_var.reset(token)

        if issue_new:
            is_https = request.url.scheme == "https"
            response.set_cookie(
                key=COOKIE_NAME,
                value=_sign(uid),
                max_age=COOKIE_MAX_AGE,
                httponly=True,
                secure=is_https,
                samesite="lax",
                path="/",
            )
        return response


def clear_identity_cookie(response: Response, is_https: bool) -> None:
    """Delete the bhook_uid cookie on logout — the browser becomes anonymous."""
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        secure=is_https,
        httponly=True,
        samesite="lax",
    )
