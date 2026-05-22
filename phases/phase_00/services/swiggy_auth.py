"""OAuth 2.1 + PKCE for Swiggy Food API (Clientless flow)."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode

import httpx

from phases.phase_00.config import Settings, _ENV_FILE, get_settings
from phases.phase_00.logging_setup import get_logger

log = get_logger(__name__)


class SwiggyAuthError(Exception):
    """OAuth failure."""


def generate_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for S256 PKCE."""
    verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def update_env_file(**env_vars: str) -> None:
    """Write arbitrary key-value pairs to .env."""
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


class SwiggyAuthService:
    """OAuth 2.1 + PKCE against Swiggy (Clientless)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def get_access_token(self) -> str | None:
        """Read token from settings, respecting expiration."""
        token = self.settings.swiggy_access_token
        expiry = self.settings.swiggy_token_expiry

        if not token:
            return None

        # Expired or expiring within 5 minutes (300s)
        if time.time() >= (expiry - 300):
            log.warning("oauth_token_expired")
            return None

        return token

    def register_client(self) -> str:
        """Register a new dynamic client (RFC 7591) and return the client_id."""
        url = f"{self.settings.swiggy_oauth_base_url.rstrip('/')}/auth/register"
        payload = {
            "redirect_uris": [self.settings.swiggy_oauth_redirect_uri],
            "client_name": "SwiggyTalk Local Agent",
            "token_endpoint_auth_method": "none"
        }
        
        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, json=payload)
            
        if response.status_code >= 400:
            raise SwiggyAuthError(f"Client registration failed: {response.text}")
            
        data = response.json()
        client_id = data["client_id"]
        log.info("dynamic_client_registered", client_id=client_id)
        
        # Write to .env
        update_env_file(SWIGGY_OAUTH_CLIENT_ID=client_id)
        # Update current settings so the rest of the flow uses it
        self.settings.swiggy_oauth_client_id = client_id
        
        return client_id

    def build_authorization_url(
        self, challenge: str, state: str
    ) -> str:
        """
        Build authorize URL pointing to swiggy_oauth_base_url/auth/authorize.
        """
        if not self.settings.swiggy_oauth_client_id:
            raise SwiggyAuthError("SWIGGY_OAUTH_CLIENT_ID is required but not set in .env")

        params = {
            "response_type": "code",
            "client_id": self.settings.swiggy_oauth_client_id,
            "redirect_uri": self.settings.swiggy_oauth_redirect_uri,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
            "scope": "mcp:tools",
        }
        base_url = self.settings.swiggy_oauth_base_url.rstrip("/")
        url = f"{base_url}/auth/authorize?{urlencode(params)}"
        return url

    def exchange_code(self, code: str, verifier: str) -> tuple[str, int]:
        """Exchange authorization code for access token. Returns (token, expires_in)."""
        payload: dict[str, str] = {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "client_id": self.settings.swiggy_oauth_client_id,
            "redirect_uri": self.settings.swiggy_oauth_redirect_uri,
        }

        # Sync httpx call for the CLI script
        base_url = self.settings.swiggy_oauth_base_url.rstrip("/")
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                f"{base_url}/auth/token",
                json=payload,
                headers={"Content-Type": "application/json"},
            )

        if response.status_code >= 400:
            raise SwiggyAuthError(
                f"Token exchange failed ({response.status_code}): {response.text}"
            )

        data = response.json()
        access_token = data["access_token"]
        expires_in = int(data.get("expires_in", 432000))
        return access_token, expires_in


# ── CLI Runner ────────────────────────────────────────────────────────────────

def run_cli_auth() -> None:
    """Run the local web server to catch the callback and exchange the token."""
    settings = get_settings()
    auth_service = SwiggyAuthService(settings)

    if not settings.swiggy_oauth_client_id:
        print("No SWIGGY_OAUTH_CLIENT_ID found. Registering a new dynamic client...")
        auth_service.register_client()

    verifier, challenge = generate_pkce_pair()
    state = secrets.token_urlsafe(16)

    auth_url = auth_service.build_authorization_url(challenge, state)

    # Parse port from redirect URI (default to 8000 for http if not specified)
    parsed_uri = urllib.parse.urlparse(settings.swiggy_oauth_redirect_uri)
    port = parsed_uri.port
    if port is None:
        port = 443 if parsed_uri.scheme == "https" else 8000

    callback_code = None
    callback_state = None

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            nonlocal callback_code, callback_state
            query = urllib.parse.urlparse(self.path).query
            params = parse_qs(query)

            if "code" in params:
                callback_code = params["code"][0]
                callback_state = params.get("state", [None])[0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(
                    b"<html><body><h1>Authentication Successful!</h1><p>You can close this window and return to the terminal.</p></body></html>"
                )
            else:
                self.send_response(400)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(
                    b"<html><body><h1>Authentication Failed</h1><p>No code found in the callback.</p></body></html>"
                )

        def log_message(self, format, *args):
            pass  # Suppress default server logging

    print(f"\n🚀 Exact Swiggy Auth URL to open manually:\n{auth_url}\n")
    print("Waiting for callback... (Complete Phone + OTP in your browser)")
    # webbrowser.open(auth_url)  # Disabled per user request

    try:
        # Bind to '0.0.0.0' to allow localhost properly
        server = HTTPServer(("0.0.0.0", port), CallbackHandler)
    except OSError as e:
        print(f"❌ Failed to start server on port {port}: {e}")
        return
    while not callback_code:
        server.handle_request()

    if callback_state != state:
        print("❌ Error: State mismatch! Possible CSRF attack.")
        return

    print("\n✅ Callback received! Exchanging code for token...")

    try:
        access_token, expires_in = auth_service.exchange_code(callback_code, verifier)
        expiry = time.time() + expires_in
        update_env_file(SWIGGY_ACCESS_TOKEN=access_token, SWIGGY_TOKEN_EXPIRY=str(expiry))
        print("🎉 Success! SWIGGY_ACCESS_TOKEN written to .env")
        print("You can now run queries!")
    except Exception as e:
        print(f"❌ Token exchange failed: {e}")


if __name__ == "__main__":
    run_cli_auth()
