"""Long-term memory — per-user SQLite-backed state.

Architecture: every row is scoped by `uid` (the signed-cookie identity). Reads
and writes implicitly use `current_uid_var` so call sites stay unchanged — only
the IdentityMiddleware must have run first.

Public surface:

  • get_user_facts() → list[str]        — short facts for the persona prompt
  • record_order(...)                   — append on checkout
  • record_rejection(query, dishes)     — on dismissed recommendations
  • suggest_usual(now) → dict | None    — proactive opener data
  • set_preference / get_preference     — free-form k/v

All writes are best-effort. Failures are logged, never raised.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from phases.phase_00.services.identity import current_uid_var

log = logging.getLogger(__name__)

_DB_PATH = Path(__file__).resolve().parents[3] / ".memory" / "user.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS profile (
    uid   TEXT NOT NULL,
    key   TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (uid, key)
);

CREATE TABLE IF NOT EXISTS orders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    uid             TEXT    NOT NULL,
    ts              REAL    NOT NULL,
    restaurant_id   TEXT,
    restaurant_name TEXT,
    items_json      TEXT    NOT NULL,
    total           REAL    NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS rejections (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    uid    TEXT    NOT NULL,
    ts     REAL    NOT NULL,
    query  TEXT    NOT NULL,
    dishes TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS orders_uid_ts     ON orders(uid, ts);
CREATE INDEX IF NOT EXISTS rejections_uid_ts ON rejections(uid, ts);
"""


def _current_uid() -> str | None:
    """Resolve the active user. Returns None in CLI / test paths where no middleware ran."""
    try:
        uid = current_uid_var.get()
    except LookupError:
        return None
    return uid or None


@contextmanager
def _conn():
    try:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(_DB_PATH), timeout=2.0)
        c.row_factory = sqlite3.Row
        try:
            c.executescript(_SCHEMA)
            yield c
            c.commit()
        finally:
            c.close()
    except Exception as exc:
        log.warning("memory_io_failed: %s", exc)
        yield None


# ── Profile (k/v) ─────────────────────────────────────────────────────────────


def set_preference(key: str, value: Any, uid: str | None = None) -> None:
    uid = uid or _current_uid()
    if not uid:
        return
    with _conn() as c:
        if c is None:
            return
        c.execute(
            "INSERT INTO profile(uid, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(uid, key) DO UPDATE SET value=excluded.value",
            (uid, key, json.dumps(value)),
        )


def get_preference(key: str, default: Any = None, uid: str | None = None) -> Any:
    uid = uid or _current_uid()
    if not uid:
        return default
    with _conn() as c:
        if c is None:
            return default
        row = c.execute(
            "SELECT value FROM profile WHERE uid=? AND key=?", (uid, key)
        ).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except Exception:
            return default


# ── Orders ────────────────────────────────────────────────────────────────────


def record_order(
    restaurant_id: str | None,
    restaurant_name: str | None,
    items: list[dict],
    total: float = 0.0,
    uid: str | None = None,
) -> None:
    uid = uid or _current_uid()
    if not uid:
        return
    with _conn() as c:
        if c is None:
            return
        compact = [
            {
                "id":    it.get("id") or it.get("itemId"),
                "name":  it.get("name"),
                "price": it.get("price"),
                "veg":   it.get("veg"),
                "qty":   it.get("qty", 1),
            }
            for it in items
        ]
        c.execute(
            "INSERT INTO orders(uid, ts, restaurant_id, restaurant_name, items_json, total) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (uid, time.time(), restaurant_id, restaurant_name, json.dumps(compact), total),
        )


def recent_orders(limit: int = 10, uid: str | None = None) -> list[dict]:
    uid = uid or _current_uid()
    if not uid:
        return []
    with _conn() as c:
        if c is None:
            return []
        rows = c.execute(
            "SELECT ts, restaurant_id, restaurant_name, items_json, total "
            "FROM orders WHERE uid=? ORDER BY ts DESC LIMIT ?",
            (uid, limit),
        ).fetchall()
        out: list[dict] = []
        for r in rows:
            try:
                items = json.loads(r["items_json"])
            except Exception:
                items = []
            out.append({
                "ts":              r["ts"],
                "restaurant_id":   r["restaurant_id"],
                "restaurant_name": r["restaurant_name"],
                "items":           items,
                "total":           r["total"],
            })
        return out


# ── Rejections ────────────────────────────────────────────────────────────────


def record_rejection(query: str, dishes: list[str], uid: str | None = None) -> None:
    uid = uid or _current_uid()
    if not uid:
        return
    with _conn() as c:
        if c is None:
            return
        c.execute(
            "INSERT INTO rejections(uid, ts, query, dishes) VALUES (?, ?, ?, ?)",
            (uid, time.time(), query, json.dumps(dishes)),
        )


# ── Reading derived facts ─────────────────────────────────────────────────────


def get_user_facts(max_facts: int = 5, uid: str | None = None) -> list[str]:
    uid = uid or _current_uid()
    if not uid:
        return []
    facts: list[str] = []

    veg = get_preference("veg_default", uid=uid)
    if veg == "veg":
        facts.append("veg only")
    elif veg == "nonveg":
        facts.append("eats non-veg")

    budget = get_preference("max_budget", uid=uid)
    if isinstance(budget, (int, float)) and budget > 0:
        facts.append(f"max budget ~₹{int(budget)}")

    recent = recent_orders(limit=20, uid=uid)
    if recent:
        by_rest = Counter(
            r["restaurant_name"] for r in recent if r["restaurant_name"]
        )
        top_rest, n = (by_rest.most_common(1) or [(None, 0)])[0]
        if top_rest and n >= 2:
            facts.append(f"orders from {top_rest} often ({n}x)")

        last = recent[0]
        if last["restaurant_name"]:
            ago = datetime.fromtimestamp(last["ts"])
            facts.append(
                f"last order: {last['restaurant_name']} on "
                f"{ago.strftime('%a %d %b')}"
            )

    return facts[:max_facts]


def suggest_usual(now: datetime | None = None, uid: str | None = None) -> dict | None:
    uid = uid or _current_uid()
    if not uid:
        return None
    now = now or datetime.now()
    hour = now.hour

    def slot(ts: float) -> int:
        return datetime.fromtimestamp(ts).hour

    matching = [o for o in recent_orders(limit=50, uid=uid) if abs(slot(o["ts"]) - hour) <= 1]
    if not matching:
        return None

    by_rest = Counter(o["restaurant_name"] for o in matching if o["restaurant_name"])
    if not by_rest:
        return None

    top_rest, n = by_rest.most_common(1)[0]
    if n < 2:
        return None

    for o in matching:
        if o["restaurant_name"] == top_rest:
            return {
                "restaurant_name": top_rest,
                "restaurant_id":   o["restaurant_id"],
                "items":           o["items"],
                "n_times":         n,
            }
    return None


def clear_all(uid: str | None = None) -> None:
    """Test helper. Without uid, wipes the whole DB."""
    with _conn() as c:
        if c is None:
            return
        if uid:
            c.execute("DELETE FROM profile    WHERE uid=?", (uid,))
            c.execute("DELETE FROM orders     WHERE uid=?", (uid,))
            c.execute("DELETE FROM rejections WHERE uid=?", (uid,))
        else:
            c.execute("DELETE FROM profile")
            c.execute("DELETE FROM orders")
            c.execute("DELETE FROM rejections")
