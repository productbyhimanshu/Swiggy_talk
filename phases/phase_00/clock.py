"""The user's wall clock — India time, regardless of where the server runs.

Render (and most hosts) run in UTC, 5h30m behind India, which made 8 PM
read as "lunch time" and "deliver at 9pm" mean 9 PM UTC. Swiggy is India
only and IST has no daylight saving, so a fixed +05:30 offset is exact and
needs no tz database on the host.

Returns naive datetimes so they compare cleanly with the rest of the code's
naive "user-local" times. Durations (staleness, timeouts) don't need this.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30), name="IST")


def local_now() -> datetime:
    """Current India time (naive)."""
    return datetime.now(IST).replace(tzinfo=None)


def local_from_timestamp(ts: float) -> datetime:
    """India wall-clock time of a Unix timestamp (naive)."""
    return datetime.fromtimestamp(ts, IST).replace(tzinfo=None)
