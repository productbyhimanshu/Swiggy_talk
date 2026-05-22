"""Parse Swiggy MCP text-blob responses into structured dicts.

Swiggy's API follows MCP protocol: all tool results come back as
  [{"type": "text", "text": "...formatted string..."}]

search_restaurants returns one text block with all results packed in:
  "Found 10 restaurants for \"pizza\":\n
   1. Domino's Pizza — Pizzas, Italian | 4.3★ | 25 min | ₹400 for two (ID: 45605)\n
   ..."

This module parses those blobs into lists of plain dicts that the
scorer, persona, and frontend DishCard can consume.
"""

from __future__ import annotations

import re

# Matches one restaurant line in the Swiggy search_restaurants text blob.
# Format: N. Name [(Ad)] — Cuisines | Rating★ | ETA min | ₹Cost for two (ID: id)
_RESTAURANT_RE = re.compile(
    r"\d+\.\s+"          # "1. "
    r"(.+?)"             # name (non-greedy)
    r"(?:\s*\(Ad\))?"    # optional "(Ad)" badge
    r"\s*[—–-]\s*"       # em-dash separator
    r"(.+?)"             # cuisines
    r"\s*\|\s*"
    r"([\d.]+)★"         # rating  e.g. "4.3★"
    r"\s*\|\s*"
    r"(\d+)\s*min"       # ETA minutes
    r"\s*\|\s*"
    r"₹(\d+)\s*for two"  # cost-for-two in INR
    r"\s*\(ID:\s*(\w+)\)",  # restaurantId
    re.UNICODE,
)


def parse_restaurants(content: list[dict]) -> list[dict]:
    """
    Convert a Swiggy MCP content-block list into structured restaurant dicts.

    Each returned dict has fields expected by the scorer, persona, and
    frontend DishCard:
        restaurantId, id, name, restaurant, cuisines,
        rating (float), deliveryTime (str), eta (int),
        costForTwo (int), price (int), priceLabel, veg
    """
    restaurants: list[dict] = []
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "text":
            continue
        text = block.get("text", "")
        for m in _RESTAURANT_RE.finditer(text):
            name, cuisines, rating_s, eta_s, cost_s, rest_id = m.groups()
            eta_int = int(eta_s)
            cost_int = int(cost_s)
            restaurants.append({
                # IDs
                "restaurantId": rest_id.strip(),
                "id": rest_id.strip(),          # DishCard key / cart key
                # Display
                "name": name.strip(),
                "restaurant": name.strip(),     # alias used by persona _prepare_context
                "cuisines": cuisines.strip(),
                # Scoring fields
                "rating": float(rating_s),
                "deliveryTime": f"{eta_int} min",  # string for parse_eta()
                "eta": eta_int,                    # integer for DishCard display
                # Pricing
                "costForTwo": cost_int,
                "price": cost_int,              # DishCard renders ₹{price}
                "priceLabel": "for 2",          # shown next to price in card
                # Veg status unknown at restaurant level
                "veg": None,
            })
    return restaurants
