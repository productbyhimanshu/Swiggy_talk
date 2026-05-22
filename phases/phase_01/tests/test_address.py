"""Address parsing from get_addresses payloads."""

import pytest

from phases.phase_01.services.address import pick_default_address


def test_pick_from_list():
    data = [{"id": "addr_1", "label": "Home"}, {"addressId": "addr_2"}]
    assert pick_default_address(data) == "addr_1"


def test_pick_from_wrapped_dict():
    data = {"addresses": [{"addressId": "addr_x"}]}
    assert pick_default_address(data) == "addr_x"


def test_pick_empty_returns_none():
    assert pick_default_address([]) is None
    assert pick_default_address({}) is None


@pytest.mark.asyncio
async def test_resolve_session_address_mocked(monkeypatch):
    from phases.phase_01.services import address as address_mod
    from phases.phase_01.services.session import clear_all_sessions, get_session

    clear_all_sessions()

    class FakeClient:
        async def get_addresses(self):
            return [{"id": "addr_home", "label": "Home"}]

    monkeypatch.setattr(address_mod, "SwiggyApiClient", FakeClient)

    state = await address_mod.resolve_session_address("sess-1")
    assert state.address_id == "addr_home"
    assert get_session("sess-1", touch=False).address_id == "addr_home"
