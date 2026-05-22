"""OAuth 2.1 + PKCE for Swiggy Food API (HTTP, not MCP protocol)."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from phases.phase_00.config import Settings, get_settings
from phases.phase_00.logging_setup import get_logger

log = get_logger(__name__)

TOKEN_STORE_DIR = Path.home() / ".swiggy_talk"
TOKEN_STORE_FILE = TOKEN_STORE_DIR / "tokens.json"
PKCE_STORE_FILE = TOKEN_STORE_DIR / "pkce_pending.json"


class SwiggyAuthError(Exception):
    """OAuth or token storage failure."""


@dataclass
class TokenBundle:
    access_token: str
    token_type: str
    expires_in: int
    scope: str
    obtained_at: float

    @property
    def expires_at(self) -> float:
        return self.obtained_at + self.expires_in

    def is_expired(self, buffer_seconds: int = 60) -> bool:
        return time.time() >= (self.expires_at - buffer_seconds)

    def to_dict(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "token_type": self.token_type,
            "expires_in": self.expires_in,
            "scope": self.scope,
            "obtained_at": self.obtained_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TokenBundle:
        return cls(
            access_token=data["access_token"],
            token_type=data.get("token_type", "Bearer"),
            expires_in=int(data["expires_in"]),
            scope=data.get("scope", ""),
            obtained_at=float(data.get("obtained_at", time.time())),
        )


def generate_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for S256 PKCE."""
    verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


class SwiggyAuthService:
    """OAuth 2.1 + PKCE against https://mcp.swiggy.com."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._base = self.settings.swiggy_oauth_base_url.rstrip("/")

    def build_authorization_url(self, state: str | None = None) -> tuple[str, str]:
        """
        Build authorize URL and persist PKCE verifier for callback exchange.
        Returns (authorization_url, state).
        """
        if not self.settings.swiggy_oauth_client_id:
            raise SwiggyAuthError("SWIGGY_OAUTH_CLIENT_ID is not configured")

        verifier, challenge = generate_pkce_pair()
        state = state or secrets.token_urlsafe(16)

        params = {
            "response_type": "code",
            "client_id": self.settings.swiggy_oauth_client_id,
            "redirect_uri": self.settings.swiggy_oauth_redirect_uri,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
            "scope": "mcp:tools",
        }
        url = f"{self._base}/auth/authorize?{urlencode(params)}"
        self._save_pending_pkce(verifier, state)
        log.info("oauth_authorize_url_built", redirect_uri=self.settings.swiggy_oauth_redirect_uri)
        return url, state

    async def exchange_code(self, code: str, state: str | None = None) -> TokenBundle:
        """Exchange authorization code for access token."""
        verifier, pending_state = self._load_pending_pkce()
        if state and pending_state and state != pending_state:
            raise SwiggyAuthError("OAuth state mismatch — possible CSRF")

        payload: dict[str, str] = {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "client_id": self.settings.swiggy_oauth_client_id,
            "redirect_uri": self.settings.swiggy_oauth_redirect_uri,
        }
        if self.settings.swiggy_oauth_client_secret:
            payload["client_secret"] = self.settings.swiggy_oauth_client_secret

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self._base}/auth/token",
                json=payload,
                headers={"Content-Type": "application/json"},
            )

        if response.status_code >= 400:
            raise SwiggyAuthError(
                f"Token exchange failed ({response.status_code}): {response.text}"
            )

        data = response.json()
        bundle = TokenBundle(
            access_token=data["access_token"],
            token_type=data.get("token_type", "Bearer"),
            expires_in=int(data.get("expires_in", 432000)),
            scope=data.get("scope", ""),
            obtained_at=time.time(),
        )
        self.save_tokens(bundle)
        self._clear_pending_pkce()
        log.info("oauth_token_obtained", expires_in=bundle.expires_in)
        return bundle

    def save_tokens(self, bundle: TokenBundle) -> None:
        TOKEN_STORE_DIR.mkdir(parents=True, exist_ok=True)
        TOKEN_STORE_FILE.write_text(json.dumps(bundle.to_dict(), indent=2))
        try:
            TOKEN_STORE_FILE.chmod(0o600)
        except OSError:
            pass

    def load_tokens(self) -> TokenBundle | None:
        if not TOKEN_STORE_FILE.exists():
            return None
        try:
            data = json.loads(TOKEN_STORE_FILE.read_text())
            return TokenBundle.from_dict(data)
        except (json.JSONDecodeError, KeyError) as exc:
            raise SwiggyAuthError(f"Invalid token store: {exc}") from exc

    def get_access_token(self) -> str | None:
        bundle = self.load_tokens()
        if bundle is None:
            return None
        if bundle.is_expired():
            log.warning("oauth_token_expired")
            return None
        return bundle.access_token

    def clear_tokens(self) -> None:
        if TOKEN_STORE_FILE.exists():
            TOKEN_STORE_FILE.unlink()
        self._clear_pending_pkce()

    def _save_pending_pkce(self, verifier: str, state: str) -> None:
        TOKEN_STORE_DIR.mkdir(parents=True, exist_ok=True)
        PKCE_STORE_FILE.write_text(json.dumps({"verifier": verifier, "state": state}))

    def _load_pending_pkce(self) -> tuple[str, str | None]:
        if not PKCE_STORE_FILE.exists():
            raise SwiggyAuthError(
                "No pending PKCE session. Start login via GET /auth/swiggy/login first."
            )
        data = json.loads(PKCE_STORE_FILE.read_text())
        return data["verifier"], data.get("state")

    def _clear_pending_pkce(self) -> None:
        if PKCE_STORE_FILE.exists():
            PKCE_STORE_FILE.unlink()
