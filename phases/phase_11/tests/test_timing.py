"""Phase 11 eval suite — timing + scheduler (architecture §11).

Tests (11 scenarios + edge cases):
  11.E1  : lunch at 1 PM, 30-min ETA → order at 12:25 (30 + 5 buffer)
  11.E1b : dinner at 8 PM, 45-min ETA → order at 19:10
  11.E1c : breakfast at 8 AM, 25-30 mins ETA → order at 07:25 (max=30)
  11.E1d : 10+ scenario coverage — various ETA + target combos
  11.E2  : fire_at already passed (≤ threshold) → order_now=True
  11.E3  : delivery_target >4h away → warn_far_ahead=True
  11.E4  : pre_order_check: restaurant closed → cancel
  11.E5  : pre_order_check: ETA spike blows window → cancel
  11.E5b : pre_order_check: cart empty → cancel
  11.E6  : user cancel before fire → no order call, job.cancelled=True
  11.E7  : execute_scheduled_order: OrderDisabledError (Phase 11 stub)
  11.E7b : execute_scheduled_order: unknown job_id → error dict
  11.E7c : execute_scheduled_order: unknown exception → logged, error dict
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

from phases.phase_11.services.scheduler import (
    calculate_order_time,
    cancel_job,
    clear_all_jobs,
    create_job,
    execute_scheduled_order,
    get_job,
    pre_order_check,
    ORDER_BUFFER_MINUTES,
    ScheduledJob,
)
from phases.phase_00.services.order_guard import OrderDisabledError


# ── Helpers ───────────────────────────────────────────────────────────────────

def _future(hours=2, minutes=0) -> datetime:
    return datetime.now() + timedelta(hours=hours, minutes=minutes)


def _past(minutes=10) -> datetime:
    return datetime.now() - timedelta(minutes=minutes)


@pytest.fixture(autouse=True)
def clean_jobs():
    clear_all_jobs()
    yield
    clear_all_jobs()


# ── 11.E1 — Timing formula ────────────────────────────────────────────────────

def test_lunch_1pm_30min_eta():
    """11.E1 — lunch at 1 PM, 30-min ETA → order at 12:25."""
    now = datetime(2026, 6, 10, 11, 0, 0)   # 11:00 AM (reference time)
    target = datetime(2026, 6, 10, 13, 0, 0)  # 1:00 PM

    result = calculate_order_time(target, "30 mins", now=now)

    expected_fire = datetime(2026, 6, 10, 12, 25, 0)  # 13:00 - 30 - 5 = 12:25
    assert result["fire_at"] == expected_fire
    assert result["eta_minutes"] == 30
    assert result["order_now"] is False
    assert result["warn_far_ahead"] is False


def test_dinner_8pm_45min_eta():
    """11.E1b — dinner at 8 PM, 45-min ETA → order at 19:10."""
    now = datetime(2026, 6, 10, 12, 0, 0)   # noon
    target = datetime(2026, 6, 10, 20, 0, 0)  # 8 PM

    result = calculate_order_time(target, "45 mins", now=now)

    expected_fire = datetime(2026, 6, 10, 19, 10, 0)  # 20:00 - 45 - 5 = 19:10
    assert result["fire_at"] == expected_fire
    assert result["eta_minutes"] == 45


def test_breakfast_8am_range_eta():
    """11.E1c — breakfast, '25-30 mins' → uses max = 30."""
    now = datetime(2026, 6, 10, 6, 0, 0)
    target = datetime(2026, 6, 10, 8, 0, 0)

    result = calculate_order_time(target, "25-30 mins", now=now)

    expected_fire = datetime(2026, 6, 10, 7, 25, 0)  # 08:00 - 30 - 5 = 07:25
    assert result["fire_at"] == expected_fire
    assert result["eta_minutes"] == 30


@pytest.mark.parametrize("eta_str,expected_fire_hour,expected_fire_min", [
    ("15 mins",    12, 40),   # 13:00 - 15 - 5 = 12:40
    ("20 mins",    12, 35),   # 13:00 - 20 - 5 = 12:35
    ("30 mins",    12, 25),   # 13:00 - 30 - 5 = 12:25
    ("45 mins",    12, 10),   # 13:00 - 45 - 5 = 12:10
    ("60 mins",    11, 55),   # 13:00 - 60 - 5 = 11:55
    ("60-90 mins", 11, 25),   # 13:00 - 90 - 5 = 11:25
    ("ASAP",       12, 10),   # default ETA 45 → 13:00 - 45 - 5 = 12:10
    ("",           12, 10),   # default ETA 45 → same
])
def test_timing_parametrize(eta_str, expected_fire_hour, expected_fire_min):
    """11.E1d — 8 parametrised scenarios for lunch at 1 PM."""
    now = datetime(2026, 6, 10, 10, 0, 0)
    target = datetime(2026, 6, 10, 13, 0, 0)

    result = calculate_order_time(target, eta_str, now=now)

    expected = datetime(2026, 6, 10, expected_fire_hour, expected_fire_min, 0)
    assert result["fire_at"] == expected, (
        f"eta_str={eta_str!r}: expected {expected}, got {result['fire_at']}"
    )


# ── 11.E2 — order_now ────────────────────────────────────────────────────────

def test_order_now_when_fire_at_passed():
    """11.E2 — fire_at already past → order_now=True."""
    # delivery_target 5 minutes from now; ETA 30 min → fire_at is 30 min in the past
    now = datetime.now()
    target = now + timedelta(minutes=5)

    result = calculate_order_time(target, "30 mins", now=now)

    assert result["order_now"] is True


def test_order_now_when_within_threshold():
    """11.E2b — fire_at is only 1 min away → order_now=True (within 2-min threshold)."""
    now = datetime.now()
    target = now + timedelta(minutes=36)  # 30 ETA + 5 buffer + 1 min remaining

    result = calculate_order_time(target, "30 mins", now=now)

    assert result["order_now"] is True


# ── 11.E3 — warn far ahead ────────────────────────────────────────────────────

def test_warn_far_ahead_over_4h():
    """11.E3 — delivery_target >4h from now → warn_far_ahead=True."""
    now = datetime.now()
    target = now + timedelta(hours=5)

    result = calculate_order_time(target, "30 mins", now=now)

    assert result["warn_far_ahead"] is True


def test_no_warn_under_4h():
    """11.E3b — delivery_target <4h from now → no warn."""
    now = datetime.now()
    target = now + timedelta(hours=3)

    result = calculate_order_time(target, "30 mins", now=now)

    assert result["warn_far_ahead"] is False


# ── 11.E4 — pre_order_check: closed ──────────────────────────────────────────

def test_pre_check_restaurant_closed():
    """11.E4 — restaurant closed → pre_order_check returns cancel."""
    job_info = create_job("s1", _future(hours=2), "30 mins")
    job = get_job(job_info["job_id"])

    result = pre_order_check(job, "30 mins", restaurant_open=False, cart_has_items=True)

    assert result["ok"] is False
    assert result["reason"] == "restaurant_closed"
    assert result["cancel"] is True


# ── 11.E5 — pre_order_check: ETA spike ───────────────────────────────────────

def test_pre_check_eta_spike():
    """11.E5 — ETA spikes so food would arrive after delivery_target → cancel."""
    # Target 10 minutes from now; new ETA is 60 mins → would arrive way late
    target = datetime.now() + timedelta(minutes=10)
    job_info = create_job("s2", target, "10 mins")
    job = get_job(job_info["job_id"])

    result = pre_order_check(job, "60 mins", restaurant_open=True, cart_has_items=True)

    assert result["ok"] is False
    assert result["reason"] == "eta_spike"
    assert result["cancel"] is True


def test_pre_check_cart_empty():
    """11.E5b — cart is empty → pre_order_check fails."""
    job_info = create_job("s3", _future(hours=2), "30 mins")
    job = get_job(job_info["job_id"])

    result = pre_order_check(job, "30 mins", restaurant_open=True, cart_has_items=False)

    assert result["ok"] is False
    assert result["reason"] == "cart_empty"


def test_pre_check_all_ok():
    """11.E5c — all conditions pass → ok=True."""
    target = datetime.now() + timedelta(hours=3)
    job_info = create_job("s4", target, "30 mins")
    job = get_job(job_info["job_id"])

    result = pre_order_check(job, "30 mins", restaurant_open=True, cart_has_items=True)

    assert result["ok"] is True


# ── 11.E6 — user cancel ───────────────────────────────────────────────────────

def test_cancel_before_fire_blocks_execute():
    """11.E6 — cancel job → execute returns job_cancelled, no order placed."""
    job_info = create_job("s5", _future(hours=2), "30 mins")
    job_id = job_info["job_id"]

    cancel_result = cancel_job(job_id)
    assert cancel_result["ok"] is True

    job = get_job(job_id)
    assert job.cancelled is True
    assert job.fired is False

    # execute should bail out without touching order guard
    exec_result = execute_scheduled_order(job_id)
    assert exec_result["ok"] is False
    assert exec_result["reason"] == "job_cancelled"


def test_cancel_unknown_job():
    """11.E6b — cancel non-existent job_id → job_not_found."""
    result = cancel_job("fake_job_xyz")
    assert result["ok"] is False
    assert result["reason"] == "job_not_found"


# ── 11.E7 — execute_scheduled_order: Phase 11 stub ──────────────────────────

def test_execute_blocked_by_order_guard():
    """11.E7 — ORDER_ENABLED=false → OrderDisabledError; returns order_disabled, not a crash."""
    job_info = create_job("s6", _future(hours=2), "30 mins")

    # Default env has ORDER_ENABLED=false — assert_orders_enabled() raises
    result = execute_scheduled_order(job_info["job_id"])

    assert result["ok"] is False
    assert result["reason"] == "order_disabled"
    # Job is NOT marked fired — it was blocked
    job = get_job(job_info["job_id"])
    assert job.fired is False


def test_execute_unknown_job():
    """11.E7b — unknown job_id → job_not_found without crash."""
    result = execute_scheduled_order("totally_fake_id")
    assert result["ok"] is False
    assert result["reason"] == "job_not_found"


def test_execute_already_fired():
    """11.E7c — double-fire → already_fired guard."""
    job_info = create_job("s7", _future(hours=2), "30 mins")
    job = get_job(job_info["job_id"])
    job.fired = True  # Simulate already fired

    result = execute_scheduled_order(job_info["job_id"])

    assert result["ok"] is False
    assert result["reason"] == "already_fired"


def test_execute_unexpected_exception_logged():
    """11.E7d — unexpected exception inside execute → logged, error dict, no crash."""
    job_info = create_job("s8", _future(hours=2), "30 mins")

    with patch(
        "phases.phase_11.services.scheduler.assert_orders_enabled",
        side_effect=RuntimeError("surprise!"),
    ):
        result = execute_scheduled_order(job_info["job_id"])

    assert result["ok"] is False
    assert result["reason"] == "unexpected_error"
    assert "surprise!" in result["detail"]
