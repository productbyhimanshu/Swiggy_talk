"""Long-term memory — SQLite-backed per-app state.

Architecture note: Swiggy Talk is single-user by design (architecture §20 — no
multi-user auth). Memory is therefore per-app, not per-user. One DB file lives
at .memory/user.db. Schema migrations are forward-only (additive).

Public surface (the only functions the rest of the codebase should call):

  • get_user_facts() → list[str]
        Top short facts to inject into the persona system prompt.
        Example: ["likes Wow! Momo (3 orders)", "veg-only", "max ₹500"].

  • record_order(restaurant_id, restaurant_name, items, total)
        Called when the cart is checked out (or, in dev, when items are added).

  • record_rejection(query, dish_names)
        Called when the user dismisses recommendations without picking one.

  • suggest_usual(time_of_day) → dict | None
        For proactive openers: "Same Wow! Momo as last Tuesday?".

  • set_preference(key, value) / get_preference(key)
        Free-form k/v store for user-stated defaults.

All writes are best-effort — failures are logged but never raised. The chat
loop must never crash on memory issues.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_DB_PATH = Path(__file__).resolve().parents[3] / ".memory" / "user.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS profile (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              REAL    NOT NULL,
    restaurant_id   TEXT,
    restaurant_name TEXT,
    items_json      TEXT    NOT NULL,
    total           REAL    NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS rejections (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    ts     REAL    NOT NULL,
    query  TEXT    NOT NULL,
    dishes TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS orders_ts ON orders(ts);
CREATE INDEX IF NOT EXISTS rejections_ts ON rejections(ts);
"""


@contextmanager
def _conn():
    """Open a SQLite connection — best-effort, swallow filesystem errors."""
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

def set_preference(key: str, value: Any) -> None:
    with _conn() as c:
        if c is None:
            return
        c.execute(
            "INSERT INTO profile(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )


def get_preference(key: str, default: Any = None) -> Any:
    with _conn() as c:
        if c is None:
            return default
        row = c.execute("SELECT value FROM profile WHERE key=?", (key,)).fetchone()
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
) -> None:
    """Append an order. `items` should be a JSON-serialisable list of dish dicts."""
    with _conn() as c:
        if c is None:
            return
        # Drop fields we don't need long-term (images, scores)
        compact = [
            {
                "id":      it.get("id") or it.get("itemId"),
                "name":    it.get("name"),
                "price":   it.get("price"),
                "veg":     it.get("veg"),
                "qty":     it.get("qty", 1),
            }
            for it in items
        ]
        c.execute(
            "INSERT INTO orders(ts, restaurant_id, restaurant_name, items_json, total) "
            "VALUES (?, ?, ?, ?, ?)",
            (time.time(), restaurant_id, restaurant_name, json.dumps(compact), total),
        )


def recent_orders(limit: int = 10) -> list[dict]:
    """Return the last N orders, most recent first."""
    with _conn() as c:
        if c is None:
            return []
        rows = c.execute(
            "SELECT ts, restaurant_id, restaurant_name, items_json, total "
            "FROM orders ORDER BY ts DESC LIMIT ?",
            (limit,),
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

def record_rejection(query: str, dishes: list[str]) -> None:
    with _conn() as c:
        if c is None:
            return
        c.execute(
            "INSERT INTO rejections(ts, query, dishes) VALUES (?, ?, ?)",
            (time.time(), query, json.dumps(dishes)),
        )


# ── Reading derived facts ─────────────────────────────────────────────────────

def get_user_facts(max_facts: int = 5) -> list[str]:
    """
    Compact short facts to inject into a persona/system prompt.

    Returns up to `max_facts` strings. Each fact is < 40 chars so several can
    fit without blowing the context budget.
    """
    facts: list[str] = []

    # Explicit preferences win first
    veg = get_preference("veg_default")
    if veg == "veg":
        facts.append("veg only")
    elif veg == "nonveg":
        facts.append("eats non-veg")

    budget = get_preference("max_budget")
    if isinstance(budget, (int, float)) and budget > 0:
        facts.append(f"max budget ~₹{int(budget)}")

    # Most-frequent restaurant in recent orders
    recent = recent_orders(limit=20)
    if recent:
        by_rest = Counter(
            r["restaurant_name"] for r in recent if r["restaurant_name"]
        )
        top_rest, n = (by_rest.most_common(1) or [(None, 0)])[0]
        if top_rest and n >= 2:
            facts.append(f"orders from {top_rest} often ({n}x)")

        # Most-recent order
        last = recent[0]
        if last["restaurant_name"]:
            ago = datetime.fromtimestamp(last["ts"])
            facts.append(
                f"last order: {last['restaurant_name']} on "
                f"{ago.strftime('%a %d %b')}"
            )

    return facts[:max_facts]


def suggest_usual(now: datetime | None = None) -> dict | None:
    """
    Find the most-frequent order around the current time-of-day.
    Returns {restaurant_name, items, n_times} or None.

    Used by the proactive opener: "Same Wow! Momo as last Tuesday?"
    """
    now = now or datetime.now()
    hour = now.hour

    # Group orders by the slot they fell in
    def slot(ts: float) -> int:
        return datetime.fromtimestamp(ts).hour

    matching = [o for o in recent_orders(limit=50) if abs(slot(o["ts"]) - hour) <= 1]
    if not matching:
        return None

    by_rest = Counter(o["restaurant_name"] for o in matching if o["restaurant_name"])
    if not by_rest:
        return None

    top_rest, n = by_rest.most_common(1)[0]
    if n < 2:  # Need at least 2 to call it a pattern
        return None

    # Find the latest order from that restaurant in the slot
    for o in matching:
        if o["restaurant_name"] == top_rest:
            return {
                "restaurant_name": top_rest,
                "restaurant_id":   o["restaurant_id"],
                "items":           o["items"],
                "n_times":         n,
            }
    return None


def clear_all() -> None:
    """Test helper — wipes the DB."""
    with _conn() as c:
        if c is None:
            return
        c.execute("DELETE FROM profile")
        c.execute("DELETE FROM orders")
        c.execute("DELETE FROM rejections")
