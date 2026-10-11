"""User-facing time is India time even when the server clock is UTC."""

from datetime import datetime, timezone

from phases.phase_00 import clock
from phases.phase_06.handlers import opener


def test_local_now_is_utc_plus_530(monkeypatch):
    class _UTC9pmIndia(datetime):
        @classmethod
        def now(cls, tz=None):
            utc = datetime(2026, 10, 11, 15, 30, tzinfo=timezone.utc)  # = 21:00 IST
            return utc.astimezone(tz) if tz else utc.replace(tzinfo=None)

    monkeypatch.setattr(clock, "datetime", _UTC9pmIndia)
    assert clock.local_now() == datetime(2026, 10, 11, 21, 0)


def test_timestamp_converts_to_india_wall_clock():
    ts = datetime(2026, 10, 11, 18, 45, tzinfo=timezone.utc).timestamp()  # 00:15 IST next day
    assert clock.local_from_timestamp(ts) == datetime(2026, 10, 12, 0, 15)


def test_opener_says_dinner_at_9pm_india(monkeypatch):
    monkeypatch.setattr(opener, "local_now", lambda: datetime(2026, 10, 11, 21, 0))
    monkeypatch.setattr(opener.user_memory, "suggest_usual", lambda now=None: None)
    assert opener.build_opener()["text"].startswith("dinner time")
