"""Per-user Swiggy token store + cached dynamic client registration.

Backs the multi-user token lookup used by SwiggyAuthService. SQLite today,
Postgres-swappable tomorrow via the TokenStore protocol.

Tables (both live in .memory/user.db alongside the memory tables):

  user_tokens(uid PK, access_token, expires_at, updated_at)
    One row per visitor. Swiggy tokens last 5 days; no refresh — a 401 from
    Swiggy means we delete the row and the user must re-auth.

  oauth_client(id=1 CHECK, client_id, created_at)
    Single-row cache for Dynamic Client Registration (RFC 7591). The env
    SWIGGY_OAUTH_CLIENT_ID overrides this when set.

No tokens are ever logged. Only the uid prefix (first 8 chars) appears in
log lines.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)

_DB_PATH = Path(__file__).resolve().parents[3] / ".memory" / "user.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_tokens (
    uid          TEXT PRIMARY KEY,
    access_token TEXT NOT NULL,
    expires_at   REAL NOT NULL,
    updated_at   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS oauth_client (
    id         INTEGER PRIMARY KEY CHECK (id = 1),
    client_id  TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""


@dataclass(frozen=True)
class TokenRecord:
    access_token: str
    expires_at: float


class TokenStore(Protocol):
    """Minimal surface so a Postgres impl can be dropped in later."""

    def get(self, uid: str) -> TokenRecord | None: ...
    def set(self, uid: str, access_token: str, expires_at: float) -> None: ...
    def delete(self, uid: str) -> None: ...
    def get_client_id(self) -> str | None: ...
    def set_client_id(self, client_id: str) -> None: ...


@contextmanager
def _conn():
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(_DB_PATH), timeout=2.0)
    c.row_factory = sqlite3.Row
    try:
        c.executescript(_SCHEMA)
        yield c
        c.commit()
    finally:
        c.close()


class SqliteTokenStore:
    """SQLite TokenStore (the default; see .memory/user.db)."""

    def get(self, uid: str) -> TokenRecord | None:
        with _conn() as c:
            row = c.execute(
                "SELECT access_token, expires_at FROM user_tokens WHERE uid=?",
                (uid,),
            ).fetchone()
        if row is None:
            return None
        return TokenRecord(access_token=row["access_token"], expires_at=row["expires_at"])

    def set(self, uid: str, access_token: str, expires_at: float) -> None:
        now = time.time()
        with _conn() as c:
            c.execute(
                "INSERT INTO user_tokens(uid, access_token, expires_at, updated_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(uid) DO UPDATE SET "
                "  access_token=excluded.access_token, "
                "  expires_at=excluded.expires_at, "
                "  updated_at=excluded.updated_at",
                (uid, access_token, expires_at, now),
            )
        log.info("token_saved uid=%s… expires_at=%s", uid[:8], expires_at)

    def delete(self, uid: str) -> None:
        with _conn() as c:
            c.execute("DELETE FROM user_tokens WHERE uid=?", (uid,))
        log.info("token_deleted uid=%s…", uid[:8])

    def get_client_id(self) -> str | None:
        with _conn() as c:
            row = c.execute("SELECT client_id FROM oauth_client WHERE id=1").fetchone()
        return row["client_id"] if row else None

    def set_client_id(self, client_id: str) -> None:
        with _conn() as c:
            c.execute(
                "INSERT INTO oauth_client(id, client_id, created_at) VALUES (1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET client_id=excluded.client_id",
                (client_id, time.time()),
            )
        log.info("oauth_client_cached")


_default_store: TokenStore = SqliteTokenStore()


def get_token_store() -> TokenStore:
    return _default_store


def set_token_store(store: TokenStore) -> None:
    """Override for tests."""
    global _default_store
    _default_store = store
