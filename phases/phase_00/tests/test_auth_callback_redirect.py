"""Successful OAuth callback lands on the app with ?connected=1 (skips the start screen)."""

from fastapi.testclient import TestClient

from phases.phase_00 import main as main_mod


def test_callback_redirects_to_app_with_connected_flag(clean_env, monkeypatch):
    monkeypatch.setenv("FRONTEND_URL", "https://bhook.example.com/")
    main_mod.get_settings.cache_clear()

    async def fake_exchange(self, code, state):
        return None

    monkeypatch.setattr(main_mod.SwiggyAuthService, "exchange_code", fake_exchange)

    r = TestClient(main_mod.app).get(
        "/auth/callback", params={"code": "c", "state": "s"}, follow_redirects=False
    )
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "https://bhook.example.com/?connected=1"
