"""MCP tool errors (result.isError) must raise, never look like success."""

import time

import pytest

from phases.phase_00.services import swiggy_api
from phases.phase_00.services.identity import current_uid_var
from phases.phase_00.services.swiggy_api import SwiggyApiClient, SwiggyApiError
from phases.phase_00.services.token_store import SqliteTokenStore, set_token_store


class _Resp:
    status_code = 200
    text = ""

    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


def _client_returning(body):
    class _C:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, headers=None): return _Resp(body)
    return _C


@pytest.fixture
def authed(clean_env, tmp_path, monkeypatch):
    from phases.phase_00.services import token_store
    monkeypatch.setattr(token_store, "_DB_PATH", tmp_path / "user.db")
    store = SqliteTokenStore()
    store.set("u_t", "tok", time.time() + 3600)
    set_token_store(store)
    tok = current_uid_var.set("u_t")
    yield
    current_uid_var.reset(tok)


@pytest.mark.asyncio
async def test_is_error_result_raises_non_retryable(authed, monkeypatch):
    body = {"result": {"isError": True, "content": [{"type": "text", "text": "addressId is required"}]}}
    monkeypatch.setattr(swiggy_api.httpx, "AsyncClient", _client_returning(body))
    with pytest.raises(SwiggyApiError, match="addressId is required") as e:
        await SwiggyApiClient().call_tool("get_food_cart", {})
    assert e.value.status_code == 422


@pytest.mark.asyncio
async def test_place_food_order_sends_swiggy_format(authed, monkeypatch):
    monkeypatch.setenv("ORDER_ENABLED", "true")
    from phases.phase_00.config import get_settings
    get_settings.cache_clear()
    sent = {}

    class _C:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, headers=None):
            sent.update(json["params"]["arguments"])
            return _Resp({"result": {"structuredContent": {"orderId": "42"}, "content": []}})

    monkeypatch.setattr(swiggy_api.httpx, "AsyncClient", _C)
    out = await SwiggyApiClient().place_food_order(address_id="addr1")
    assert sent == {"addressId": "addr1", "paymentMethod": "Cash"}
    assert out == {"orderId": "42"}
    get_settings.cache_clear()
