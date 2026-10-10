"""SwiggyReadClient.search_menu maps structuredContent; auth errors are not retried."""

import pytest

from phases.phase_00.services.swiggy_auth import ReauthRequired
from phases.phase_04.services.swiggy_read import SwiggyReadClient


class _FakeApi:
    def __init__(self, result=None, exc=None):
        self.result, self.exc, self.calls = result, exc, []

    async def call_tool_structured(self, name, args):
        self.calls.append((name, args))
        if self.exc:
            raise self.exc
        return self.result

    async def call_tool(self, name, args):
        return await self.call_tool_structured(name, args)


@pytest.mark.asyncio
async def test_search_menu_maps_items_and_sends_veg_filter():
    api = _FakeApi({"items": [
        {"name": "Dal Makhani", "price": 259, "isVeg": True, "menu_item_id": "11425741",
         "inStock": 1, "restaurant_id": "49215", "restaurant_name": "Hotel Mini Mahal",
         "rating": "3.8", "hasAddons": True, "imageUrl": "https://img"},
        {"name": "Out", "price": 99, "isVeg": True, "menu_item_id": "2", "inStock": 0,
         "restaurant_id": "1", "restaurant_name": "X"},
    ], "hasMore": True, "nextOffset": 10})
    client = SwiggyReadClient(api=api)
    page = await client.search_menu("dal makhani", "addr1", veg_only=True)

    assert api.calls == [("search_menu", {"query": "dal makhani", "addressId": "addr1", "vegFilter": 1})]
    assert page["has_more"] is True and page["next_offset"] == 10
    assert len(page["items"]) == 1  # out-of-stock dropped
    d = page["items"][0]
    assert d["id"] == d["itemId"] == "11425741"
    assert d["veg"] is True and d["price"] == 259 and d["dishRating"] == 3.8
    assert d["restaurant"] == "Hotel Mini Mahal" and d["restaurantId"] == "49215"
    assert d["imageUrl"] == "https://img"


@pytest.mark.asyncio
async def test_reauth_is_not_retried_or_wrapped():
    api = _FakeApi(exc=ReauthRequired("token gone"))
    client = SwiggyReadClient(api=api)
    with pytest.raises(ReauthRequired):
        await client.search_menu("biryani", "addr1")
    assert len(api.calls) == 1
