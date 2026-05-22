"""Phase 4 — parse_eta tests (exit gate 4.E2).

All LOCAL — no network calls.
"""

import pytest

from phases.phase_04.utils.parse_eta import parse_eta


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Standard ranges — always max
        ("25-30 mins", 30),
        ("15-20 mins", 20),
        ("60-90 mins", 90),
        ("30-40 mins", 40),
        # Single values
        ("15 mins", 15),
        ("45 mins", 45),
        ("60 mins", 60),
        # Edge: default on unparseable
        ("", 45),
        ("ASAP", 45),
        ("N/A", 45),
        ("unknown", 45),
        # Multi-number string — max wins
        ("10-15-20 mins", 20),
        # Numeric string
        ("30", 30),
        # Zero (treat as 0, not default)
        ("0 mins", 0),
    ],
)
def test_parse_eta_parametrized(raw, expected):
    assert parse_eta(raw) == expected


def test_parse_eta_always_returns_int():
    result = parse_eta("25-30 mins")
    assert isinstance(result, int)


def test_parse_eta_default_is_45():
    assert parse_eta("") == 45
    assert parse_eta("   ") == 45
