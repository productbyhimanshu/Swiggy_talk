"""OAuth 2.1 + PKCE for Swiggy Food API — multi-user token store backed.

Two code paths share this module:

  Web (production): the IdentityMiddleware pins a uid onto `current_uid_var`
    before any route runs. `SwiggyAuthService.get_access_token()` looks up the
    token for that uid in SqliteTokenStore. `/auth/callback` saves the fresh
    token to the store, never to `.env`.

  CLI (local dev only, scripts/swiggy_smoke.py path): `run_cli_auth()` writes
    tokens to `.env` so the smoke script can read them via settings. When no
    uid is on the contextvar (CLI / tests / scripts) the service falls back
    to `settings.swiggy_access_token`.

Token tokens are 5-day Bearer, no refresh. On Swiggy 401/419 the service
raises ReauthRequired; the API handler converts that to a 401 JSON
`{"error": "reauth_required"}` for the frontend's Reconnect banner.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode

import httpx

from phases.phase_00.config import Settings, _ENV_FILE, get_settings
from phases.phase_00.logging_setup import get_logger
from phases.phase_00.services.identity import current_uid_var, sign_payload, verify_payload
from phases.phase_00.services.token_store import TokenStore, get_token_store

log = get_logger(__name__)


class SwiggyAuthError(Exception):
    """OAuth failure."""


class ReauthRequired(Exception):
    """Swiggy rejected the stored token (401/419) — user must sign in again."""


# ── CLI/legacy helper — only used by run_cli_auth() ──────────────────────────


def update_env_file(**env_vars: str) -> None:
    """Write key-value pairs to `.env`. Only used by the CLI auth script.

    The web OAuth flow writes tokens into SqliteTokenStore and does NOT call
    this; `.env` stays untouched by live user logins.
    """
    if not _ENV_FILE.exists():
        _ENV_FILE.write_text("")

    lines = _ENV_FILE.read_text().splitlines()
    new_lines = []
    seen = set()

    for line in lines:
        if "=" in line and not line.strip().startswith("#"):
            key = line.split("=", 1)[0].strip()
            if key in env_vars:
                new_lines.append(f"{key}={env_vars[key]}")
                seen.add(key)
                continue
        new_lines.append(line)

    for key, value in env_vars.items():
        if key not in seen:
            new_lines.append(f"{key}={value}")

    _ENV_FILE.write_text("\n".join(new_lines) + "\n")
    log.info("env_updated", keys=list(env_vars.keys()))


def generate_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


# ── In-progress login (signed cookie, 10-min TTL) ────────────────────────────
#
# The PKCE verifier, state and initiating uid travel in a signed HttpOnly
# cookie instead of server memory, so a login survives server restarts
# (Render restarts on every deploy and on free-tier wake-up) and any number
# of workers. The callback only accepts it for the same uid that started it.

OAUTH_COOKIE = "bhook_oauth"
OAUTH_COOKIE_PURPOSE = "oauth_pending"
STATE_TTL_SECONDS = 10 * 60


# ── Service ──────────────────────────────────────────────────────────────────


class SwiggyAuthService:
    """OAuth 2.1 + PKCE against Swiggy. Token lookups are per-uid."""

    def __init__(
        self,
        settings: Settings | None = None,
        store: TokenStore | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.store = store or get_token_store()

    # ── Current-user token read ──────────────────────────────────────────────

    def get_access_token(self) -> str | None:
        """Return a valid token for the current user, or None.

        Web path: looks up `current_uid_var` → store.get(uid).
        CLI path (no contextvar): falls back to settings.swiggy_access_token.
        A token expiring within 5 minutes is treated as absent.
        """
        now = time.time()

        uid = current_uid_var.get()
        if uid:
            rec = self.store.get(uid)
            if rec is None:
                return None
            if now >= (rec.expires_at - 300):
                log.info("token_expired_in_store uid=%s…", uid[:8])
                return None
            return rec.access_token

        # CLI / script fallback — reads the env-backed single-user token.
        token = self.settings.swiggy_access_token
        expiry = self.settings.swiggy_token_expiry
        if not token or now >= (expiry - 300):
            return None
        return token

    # ── Dynamic client registration ──────────────────────────────────────────

    def _resolve_client_id(self) -> str:
        """Return the OAuth client_id, registering if needed.

        Priority: env SWIGGY_OAUTH_CLIENT_ID → cached DB value → fresh DCR call.
        """
        env_cid = self.settings.swiggy_oauth_client_id
        if env_cid:
            return env_cid
        cached = self.store.get_client_id()
        if cached:
            return cached
        return self.register_client()

    def register_client(self) -> str:
        url = f"{self.settings.swiggy_oauth_base_url.rstrip('/')}/auth/register"
        payload = {
            "redirect_uris": [self.settings.swiggy_oauth_redirect_uri],
            "client_name": "SwiggyTalk Web Agent",
            "token_endpoint_auth_method": "none",
        }

        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, json=payload)

        if response.status_code >= 400:
            raise SwiggyAuthError(f"Client registration failed: {response.text}")

        data = response.json()
        client_id = data["client_id"]
        log.info("dynamic_client_registered client_id=%s…", client_id[:6])
        self.store.set_client_id(client_id)
        return client_id

    # ── Authorize URL (web flow) ─────────────────────────────────────────────

    def build_authorization_url(self) -> tuple[str, str, str]:
        """PKCE+state URL for the CURRENT user (uid taken from contextvar).

        Returns (url, state_token, pending_cookie). The caller sets
        pending_cookie as OAUTH_COOKIE; exchange_code() verifies it.
        """
        uid = current_uid_var.get()
        if not uid:
            raise SwiggyAuthError(
                "No current user — IdentityMiddleware must run before OAuth."
            )

        client_id = self._resolve_client_id()
        verifier, challenge = generate_pkce_pair()
        state_token = secrets.token_urlsafe(16)
        pending_cookie = sign_payload(
            OAUTH_COOKIE_PURPOSE,
            {"s": state_token, "v": verifier, "u": uid, "t": time.time()},
        )

        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": self.settings.swiggy_oauth_redirect_uri,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state_token,
            "scope": "mcp:tools",
        }
        base_url = self.settings.swiggy_oauth_base_url.rstrip("/")
        url = f"{base_url}/auth/authorize?{urlencode(params)}"
        return url, state_token, pending_cookie

    # ── Code exchange (web flow) ─────────────────────────────────────────────

    async def exchange_code(
        self, code: str, state_token: str | None, pending_cookie: str | None
    ) -> None:
        """Verify the in-progress login → PKCE exchange → persist token.

        Rejects if:
          - state missing, or the pending cookie is missing / tampered / expired
          - the state Swiggy echoed back differs from the one we issued
          - the login was started by a different uid (cross-user hijack)
          - Swiggy's token endpoint returns >= 400
        """
        if not state_token:
            raise SwiggyAuthError("Missing state. Restart via /auth/swiggy/login.")

        pending = (
            verify_payload(OAUTH_COOKIE_PURPOSE, pending_cookie) if pending_cookie else None
        )
        if pending is None or not isinstance(pending.get("t"), (int, float)):
            raise SwiggyAuthError(
                "Unknown or expired state. Restart via /auth/swiggy/login."
            )
        if time.time() - pending["t"] > STATE_TTL_SECONDS:
            raise SwiggyAuthError(
                "Unknown or expired state. Restart via /auth/swiggy/login."
            )
        if pending.get("s") != state_token:
            raise SwiggyAuthError("State mismatch. Restart via /auth/swiggy/login.")
        verifier = str(pending.get("v") or "")
        state_uid = str(pending.get("u") or "")

        current_uid = current_uid_var.get()
        if not current_uid:
            raise SwiggyAuthError(
                "No current user — IdentityMiddleware must run before OAuth."
            )
        if state_uid != current_uid:
            # Either someone else's cookie or a tampered one. Reject.
            log.warning(
                "oauth_state_uid_mismatch state_uid=%s… current=%s…",
                state_uid[:8],
                current_uid[:8],
            )
            raise SwiggyAuthError("State does not belong to this session.")

        client_id = self._resolve_client_id()
        payload: dict[str, str] = {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "client_id": client_id,
            "redirect_uri": self.settings.swiggy_oauth_redirect_uri,
        }

        base_url = self.settings.swiggy_oauth_base_url.rstrip("/")
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{base_url}/auth/token",
                json=payload,
                headers={"Content-Type": "application/json"},
            )

        if response.status_code >= 400:
            # Don't echo response body — it may contain a token on some IdPs.
            raise SwiggyAuthError(
                f"Token exchange failed with status {response.status_code}"
            )

        data = response.json()
        access_token = data["access_token"]
        expires_in = int(data.get("expires_in", 432000))
        expires_at = time.time() + expires_in

        self.store.set(current_uid, access_token, expires_at)
        log.info("oauth_token_saved uid=%s… expires_in=%d", current_uid[:8], expires_in)

    # ── Logout ───────────────────────────────────────────────────────────────

    def logout(self) -> None:
        uid = current_uid_var.get()
        if uid:
            self.store.delete(uid)


# ── CLI Runner (local dev only — writes to .env, not the DB) ─────────────────


def run_cli_auth() -> None:
    """One-shot CLI helper that writes tokens to `.env` for local scripts.

    Separate from the web flow — this path does NOT touch the TokenStore.
    """
    settings = get_settings()
    if not settings.swiggy_oauth_client_id:
        print("No SWIGGY_OAUTH_CLIENT_ID in .env. Registering a dynamic client...")
        url = f"{settings.swiggy_oauth_base_url.rstrip('/')}/auth/register"
        payload = {
            "redirect_uris": [settings.swiggy_oauth_redirect_uri],
            "client_name": "SwiggyTalk Local CLI",
            "token_endpoint_auth_method": "none",
        }
        with httpx.Client(timeout=30.0) as c:
            r = c.post(url, json=payload)
        r.raise_for_status()
        client_id = r.json()["client_id"]
        update_env_file(SWIGGY_OAUTH_CLIENT_ID=client_id)
        settings.swiggy_oauth_client_id = client_id

    verifier, challenge = generate_pkce_pair()
    state = secrets.token_urlsafe(16)

    params = {
        "response_type": "code",
        "client_id": settings.swiggy_oauth_client_id,
        "redirect_uri": settings.swiggy_oauth_redirect_uri,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "scope": "mcp:tools",
    }
    auth_url = f"{settings.swiggy_oauth_base_url.rstrip('/')}/auth/authorize?{urlencode(params)}"

    parsed = urllib.parse.urlparse(settings.swiggy_oauth_redirect_uri)
    port = parsed.port or (443 if parsed.scheme == "https" else 8000)

    callback_code: str | None = None
    callback_state: str | None = None

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            nonlocal callback_code, callback_state
            query = urllib.parse.urlparse(self.path).query
            qs = parse_qs(query)
            if "code" in qs:
                callback_code = qs["code"][0]
                callback_state = qs.get("state", [None])[0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<h1>Authentication Successful!</h1>")
            else:
                self.send_response(400)
                self.end_headers()

        def log_message(self, format, *args):  # noqa: ARG002
            pass

    print(f"\n🚀 Open this URL in a browser:\n{auth_url}\n")
    print("Waiting for callback (complete Phone + OTP on Swiggy)...")

    try:
        server = HTTPServer(("0.0.0.0", port), CallbackHandler)
    except OSError as e:
        print(f"❌ Failed to start server on port {port}: {e}")
        return

    while not callback_code:
        server.handle_request()

    if callback_state != state:
        print("❌ State mismatch — aborting.")
        return

    base = settings.swiggy_oauth_base_url.rstrip("/")
    with httpx.Client(timeout=30.0) as client:
        r = client.post(
            f"{base}/auth/token",
            json={
                "grant_type": "authorization_code",
                "code": callback_code,
                "code_verifier": verifier,
                "client_id": settings.swiggy_oauth_client_id,
                "redirect_uri": settings.swiggy_oauth_redirect_uri,
            },
        )
    if r.status_code >= 400:
        print(f"❌ Token exchange failed: {r.status_code}")
        return

    body = r.json()
    expiry = time.time() + int(body.get("expires_in", 432000))
    update_env_file(
        SWIGGY_ACCESS_TOKEN=body["access_token"],
        SWIGGY_TOKEN_EXPIRY=str(expiry),
    )
    print("🎉 Token written to .env")


if __name__ == "__main__":
    run_cli_auth()
