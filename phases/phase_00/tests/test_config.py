"""Phase 0.E1 — config and order safety gate."""

from phases.phase_00.config import get_settings


def test_order_enabled_defaults_false(clean_env):
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.order_enabled is False
    assert settings.orders_allowed is False


def test_orders_allowed_requires_order_enabled(clean_env, monkeypatch):
    monkeypatch.setenv("ORDER_ENABLED", "true")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.orders_allowed is True


def test_get_settings_cached(clean_env):
    a = get_settings()
    b = get_settings()
    assert a is b
