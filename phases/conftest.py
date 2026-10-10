"""Shared pytest hooks for all phase tests."""

import os
import tempfile
from pathlib import Path

import pytest


def pytest_configure(config):
    os.environ.setdefault("ORDER_ENABLED", "false")
    os.environ.setdefault("EVAL_SUITE_PASSED", "false")
    os.environ.setdefault("SESSION_SECRET", "test-session-secret-not-for-prod")
    # Isolate the memory DB so tests never touch a developer's real .memory/
    # (and so parallel test runs don't collide). The redirect only applies if
    # someone imports token_store/memory from scratch inside tests — most
    # tests mock SwiggyApiClient so they never hit SQLite anyway.
    _redirect_memory_db()


def _redirect_memory_db() -> None:
    """Point memory + token store at a tempdir for the test session."""
    tmp_root = Path(tempfile.mkdtemp(prefix="bhook_test_"))
    try:
        from phases.phase_00.services import memory as _memory
        _memory._DB_PATH = tmp_root / "user.db"
    except Exception:
        pass
    try:
        from phases.phase_00.services import token_store as _ts
        _ts._DB_PATH = tmp_root / "user.db"
    except Exception:
        pass


@pytest.fixture
def clean_env(monkeypatch):
    for key in (
        "ORDER_ENABLED",
        "EVAL_SUITE_PASSED",
        "GEMINI_API_KEY",
        "SWIGGY_OAUTH_CLIENT_ID",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ORDER_ENABLED", "false")
    monkeypatch.setenv("EVAL_SUITE_PASSED", "false")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-not-for-prod")
    from phases.phase_00.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def test_uid():
    """Seed a uid onto current_uid_var for tests that call memory/session code directly."""
    from phases.phase_00.services.identity import current_uid_var
    token = current_uid_var.set("u_test_user")
    try:
        yield "u_test_user"
    finally:
        current_uid_var.reset(token)
