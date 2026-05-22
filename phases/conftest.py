"""Shared pytest hooks for all phase tests."""

import os

import pytest


def pytest_configure(config):
    os.environ.setdefault("ORDER_ENABLED", "false")
    os.environ.setdefault("EVAL_SUITE_PASSED", "false")


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
    from phases.phase_00.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
