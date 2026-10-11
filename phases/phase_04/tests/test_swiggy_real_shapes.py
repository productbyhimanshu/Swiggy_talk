"""Parsers and cart writes against shapes captured from the live Swiggy MCP."""

import pytest

from phases.phase_00.services.swiggy_api import SwiggyApiError
from phases.phase_04.services.swiggy_read import SwiggyReadClient
from phases.phase_04.utils.parse_swiggy_content import (
    parse_menu_structured,
    parse_restaurants_structured,
)


def test_search_restaurants_structured():
    sc = {"restaurants": [
        {"id": "195224", "name": "Biryani Blues (Ad)", "cuisines": ["Biryani", "Hyderabadi"],
         "avgRating": 4.2, "totalRatings": "6.1K+", "costForTwo": "₹400 for two", "areaName": "Malviya Nagar",
         "distanceKm": 3, "deliveryTimeMinutes": 29, "deliveryTimeRange": "25-30 MINS",
         "imageUrl": "https://img", "availabilityStatus": "OPEN"},
        {"id": "46311", "name": "Chhabra's Pure Veg", "cuisines": ["North Indian"], "avgRating": 4.4,
         "costForTwo": "₹200 for two", "deliveryTimeMinutes": 26, "veg": True, "availabilityStatus": "OPEN"},
    ], "dishes": [], "total": 2, "hasMore": True, "nextOffset": 10}
    out = parse_restaurants_structured(sc)
    assert [r["name"] for r in out] == ["Biryani Blues", "Chhabra's Pure Veg"]
    assert out[0]["costForTwo"] == 400 and out[0]["eta"] == 29 and out[0]["pureVeg"] is False
    assert out[1]["pureVeg"] is True and out[1]["veg"] is True


def test_empty_search_is_empty_list():
    assert parse_restaurants_structured({"restaurants": [], "dishes": [], "total": 0}) == []


def test_menu_structured_dedupes_drops_out_of_stock_and_marks_nonveg():
    sc = {"restaurant": {"id": "195224", "name": "Biryani Blues", "isOpen": True, "deliveryTime": 26,
                         "slaString": "20-25 MINS", "avgRating": 4.2},
          "categories": [
              {"title": "Recommended", "items": [
                  {"id": "1", "name": "Chicken Biryani", "price": 329, "inStock": 1, "isBestseller": True,
                   "rating": "4.6", "hasVariants": False, "hasAddons": True},
                  {"id": "2", "name": "Veg Dum Biryani", "price": 129, "inStock": 1, "isVeg": True,
                   "hasVariants": True}]},
              {"title": "Biryani Bowls", "items": [
                  {"id": "1", "name": "Chicken Biryani", "price": 329, "inStock": 1},  # repeat
                  {"id": "3", "name": "Sold Out Bowl", "price": 99, "inStock": 0, "isVeg": True}]},
          ], "totalCategories": 14, "page": 1, "pageSize": 5, "hasMore": True}
    m = parse_menu_structured(sc)
    assert [i["id"] for i in m["items"]] == ["1", "2"]
    assert m["items"][0]["veg"] is False and m["items"][1]["veg"] is True  # no isVeg → non-veg
    assert m["items"][0]["bestseller"] and m["items"][0]["dishRating"] == 4.6
    assert m["items"][0]["category"] == "Recommended" and m["hasMore"] is True


def test_unknown_restaurant_menu_is_empty():
    sc = {"restaurant": {"id": "?", "name": "Unknown Restaurant"}, "categories": [],
          "totalCategories": 0, "page": 1, "pageSize": 5, "hasMore": False}
    assert parse_menu_structured(sc)["items"] == []


class _Api:
    def __init__(self, result):
        self.result, self.calls = result, []

    async def call_tool_structured(self, name, args):
        self.calls.append((name, args))
        return self.result

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        return self.result


@pytest.mark.asyncio
async def test_update_cart_soft_failure_raises():
    # Swiggy's response for an unavailable item: no isError, statusCode 1.
    api = _Api({"statusCode": 1, "statusMessage": "Restaurant may have removed the item(s) from their menu.",
                "titleMessage": "Apologies! one or more items in your cart are no longer available",
                "errorCodes": ["INVALID_ITEM_IDS_IN_REQUEST"], "data": None})
    with pytest.raises(SwiggyApiError, match="no longer available"):
        await SwiggyReadClient(api=api).update_food_cart(
            [{"menu_item_id": "1", "quantity": 1}], "r1", "addr1")


@pytest.mark.asyncio
async def test_update_cart_never_sends_quantity_zero_and_empty_flushes():
    api = _Api({"statusCode": 0, "data": {"items": []}})
    client = SwiggyReadClient(api=api)
    await client.update_food_cart([{"id": "1", "quantity": 0}, {"id": "2", "quantity": 1}], "r1", "addr1")
    assert api.calls[-1] == ("update_food_cart", {"restaurantId": "r1", "addressId": "addr1",
                                                  "cartItems": [{"menu_item_id": "2", "quantity": 1}]})
    await client.update_food_cart([{"id": "1", "quantity": 0}], "r1", "addr1")
    assert api.calls[-1][0] == "flush_food_cart"
