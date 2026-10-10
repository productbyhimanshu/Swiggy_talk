"""Scheduler jobs carry the owner's uid; the uid is active during execution."""

from datetime import datetime, timedelta

import pytest

from phases.phase_00.services.identity import current_uid_var
from phases.phase_11.services import scheduler as sch


@pytest.fixture(autouse=True)
def clean_jobs():
    sch.clear_all_jobs()
    yield
    sch.clear_all_jobs()


def _as(uid, fn, *args, **kw):
    tok = current_uid_var.set(uid)
    try:
        return fn(*args, **kw)
    finally:
        current_uid_var.reset(tok)


def test_job_carries_creator_uid(clean_env):
    future = datetime.now() + timedelta(hours=1)
    result = _as("u_alice", sch.create_job, "sess-1", future, "30-35 mins")
    job = sch.get_job(result["job_id"])
    assert job.uid == "u_alice"


def test_execute_sets_contextvar(clean_env):
    captured: dict[str, str] = {}

    original = sch.assert_orders_enabled

    def spy_assert():
        captured["uid"] = current_uid_var.get()
        original()

    future = datetime.now() + timedelta(hours=1)
    result = _as("u_bob", sch.create_job, "sess-2", future, "30-35 mins")

    sch.assert_orders_enabled = spy_assert
    try:
        # Caller is a different user — but execution must still see u_bob.
        _as("u_someone_else", sch.execute_scheduled_order, result["job_id"])
    finally:
        sch.assert_orders_enabled = original

    assert captured["uid"] == "u_bob"
