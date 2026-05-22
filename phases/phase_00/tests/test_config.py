"""Phase 0.E1 — config and order safety gates."""

import pytest
from pydantic import ValidationError

from phases.phase_00.config import Settings, get_settings


def test_order_enabled_defaults_false(clean_env):
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.order_enabled is False
    assert settings.eval_suite_passed is False
    assert settings.orders_allowed is False


def test_orders_allowed_requires_both_flags(clean_env, monkeypatch):
    monkeypatch.setenv("ORDER_ENABLED", "true")
    monkeypatch.setenv("EVAL_SUITE_PASSED", "true")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.orders_allowed is True


def test_order_enabled_without_eval_raises(clean_env, monkeypatch):
    monkeypatch.setenv("ORDER_ENABLED", "true")
    monkeypatch.setenv("EVAL_SUITE_PASSED", "false")
    get_settings.cache_clear()
    with pytest.raises(ValidationError, match="EVAL_SUITE_PASSED"):
        get_settings()


def test_get_settings_cached(clean_env):
    a = get_settings()
    b = get_settings()
    assert a is b
