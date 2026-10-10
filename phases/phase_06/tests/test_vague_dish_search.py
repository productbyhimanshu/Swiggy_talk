"""Dish cards come from Swiggy search_menu — vague and specific queries."""

import pytest

from phases.phase_00.services.swiggy_auth import ReauthRequired
from phases.phase_01.models.intent import UserIntent
from phases.phase_06 import orchestrator as orch


def test_keyword_match_levels():
    terms = ["dal makhani", "paneer butter masala", "khichdi"]
    assert orch._keyword_match("dal makhani (half)", terms) == (3, "dal makhani")
    assert orch._keyword_match("butter paneer masala", terms) == (2, "paneer butter masala")
    assert orch._keyword_match("masala dosa", terms) == (1, "paneer butter masala")
    assert orch._keyword_match("chocolate cake", terms) == (0, None)
    assert orch._keyword_match("sandalwood shake", ["dal"]) == (0, None)


def test_exact_phrase_strips_budget_words():
    assert orch._exact_phrase("butter chicken under 300") == "butter chicken"


def _dish(i, name, rest, veg=True, price=200, rating=None):
    return {"id": i, "itemId": i, "name": name, "veg": veg, "price": price,
            "restaurant": rest, "restaurantId": rest, "imageUrl": None,
            "dishRating": rating, "bestseller": False}


class _FakeMenuClient:
    def __init__(self, by_term, raise_exc=None):
        self.by_term = by_term
        self.calls = []
        self.raise_exc = raise_exc

    async def search_menu(self, query, address_id, veg_only=False, offset=None):
        self.calls.append((query, veg_only, offset))
        if self.raise_exc:
            raise self.raise_exc
        return {"items": self.by_term.get(query, []), "has_more": False, "next_offset": None}


@pytest.mark.asyncio
async def test_search_dishes_passes_veg_filter_and_tags_terms():
    client = _FakeMenuClient({"khichdi": [_dish("1", "Veg Khichdi", "r1")]})
    intent = UserIntent(search_query="veg food", veg_nonveg="veg")
    hits = await orch._search_dishes(client, ["khichdi", "thali"], intent, "addr")
    assert hits == [("khichdi", client.by_term["khichdi"][0])]
    assert all(veg for _q, veg, _o in client.calls)


class _PagedClient:
    """10 items per page; only the last item of each page is within budget."""

    def __init__(self, pages):
        self.pages, self.calls = pages, 0

    async def search_menu(self, query, address_id, veg_only=False, offset=None):
        idx = (offset or 0) // 10
        self.calls += 1
        items = [_dish(f"{idx}-{j}", "Butter Chicken", f"r{idx}{j}", veg=False,
                       price=250 if j == 9 else 500) for j in range(10)]
        return {"items": items, "has_more": idx + 1 < self.pages, "next_offset": (idx + 1) * 10}


@pytest.mark.asyncio
async def test_single_dish_query_pages_until_budget_matches_or_cap():
    client = _PagedClient(pages=10)
    intent = UserIntent(search_query="butter chicken under 300", budget_max=300)
    hits = await orch._search_dishes(client, ["butter chicken"], intent, "addr")
    assert client.calls == orch._MAX_DISH_PAGES
    assert sum(d["price"] <= 300 for _t, d in hits) == orch._MAX_DISH_PAGES


@pytest.mark.asyncio
async def test_single_dish_query_stops_after_first_page_without_budget():
    client = _PagedClient(pages=10)
    await orch._search_dishes(client, ["butter chicken"], UserIntent(search_query="butter chicken"), "addr")
    assert client.calls == 1


@pytest.mark.asyncio
async def test_search_dishes_propagates_reauth():
    client = _FakeMenuClient({}, raise_exc=ReauthRequired("expired"))
    with pytest.raises(ReauthRequired):
        await orch._search_dishes(client, ["biryani"], UserIntent(search_query="biryani"), "addr")


def test_rank_vague_gives_one_per_term_and_caps_restaurants():
    rest = {"r1": {"rating": 4.5, "deliveryTime": "20 min", "eta": 20, "availabilityStatus": "OPEN"},
            "r2": {"rating": 4.2, "deliveryTime": "25 min", "eta": 25, "availabilityStatus": "OPEN"}}
    hits = [
        ("dal makhani", _dish("1", "Dal Makhani", "r1")),
        ("dal makhani", _dish("2", "Dal Makhani", "r2")),          # same name → collapsed
        ("dal makhani", _dish("3", "Dal Makhani Thali", "r1")),
        ("paneer butter masala", _dish("4", "Paneer Butter Masala", "r1")),
        ("khichdi", _dish("5", "Veg Khichdi", "r2")),
        ("khichdi", _dish("6", "Chicken Khichdi", "r2", veg=False)),  # diet filtered
    ]
    intent = UserIntent(search_query="veg food", veg_nonveg="veg")
    out = orch._rank_dishes(hits, intent, rest, variety=True)
    names = [d["name"] for d in out]
    assert names.count("Dal Makhani") == 1
    assert "Chicken Khichdi" not in names
    assert {"Paneer Butter Masala", "Veg Khichdi"} <= set(names)
    assert sum(d["restaurantId"] == "r1" for d in out) <= 2
    assert out[0]["eta"] in (20, 25)  # enriched from restaurant search


def test_rank_dish_query_keeps_same_dish_from_different_places():
    hits = [("butter chicken", _dish(str(i), "Butter Chicken", f"r{i}", veg=False, price=250))
            for i in range(5)]
    intent = UserIntent(search_query="butter chicken under 300", budget_max=300)
    out = orch._rank_dishes(hits, intent, {}, variety=False)
    assert len(out) == 5 and len({d["restaurantId"] for d in out}) == 5


def test_rank_drops_over_budget_and_closed():
    rest = {"r1": {"rating": 4.5, "availabilityStatus": "CLOSED"}}
    hits = [("pizza", _dish("1", "Pizza", "r1", price=200)),
            ("pizza", _dish("2", "Pizza Large", "r2", price=900))]
    out = orch._rank_dishes(hits, UserIntent(search_query="pizza", budget_max=300), rest, variety=False)
    assert out == []
