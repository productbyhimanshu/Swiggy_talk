"""Parse Swiggy MCP text-blob responses into structured dicts.

Swiggy's API follows MCP protocol: all tool results come back as
  [{"type": "text", "text": "...formatted string..."}]

search_restaurants text blob format:
  "Found 10 restaurants for \"pizza\":\n
   1. Domino's Pizza — Pizzas, Italian | 4.3★ | 25 min | ₹400 for two (ID: 45605)\n"

get_addresses text blob format (observed):
  "1. Home — 123 Indiranagar, Bangalore (ID: 107675381)\n
   2. Work — 456 MG Road, Bangalore (ID: 98765432)\n"
  or with full street:
  "1. Home\n   Full address text (ID: 107675381)\n"

This module parses those blobs into lists of plain dicts that the
scorer, persona, address picker, and frontend can consume.
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


# ── Address parsing ───────────────────────────────────────────────────────────
# Swiggy get_addresses returns a text blob.  We try multiple patterns because
# the exact format has varied across API versions.

# Pattern A: "N. Label — Full address (ID: 12345)"
_ADDR_RE_A = re.compile(
    r"\d+\.\s+"
    r"([^\n—–(]+?)"          # label e.g. "Home" or "Work"
    r"\s*[—–]\s*"
    r"([^\n(]+?)"            # full address text
    r"\s*\(ID:\s*(\w+)\)",
    re.UNICODE,
)

# Pattern B: just "(ID: 12345)" anywhere on a line that also has a label keyword
_ADDR_RE_B = re.compile(
    r"(Home|Work|Other|Office|Flat|house|Apartment|hostel)[^\n]*"
    r"\(ID:\s*(\w+)\)",
    re.IGNORECASE | re.UNICODE,
)

# Pattern C: bare "addressId": "12345" (JSON-ish fallback)
_ADDR_RE_C = re.compile(r'"?addressId"?\s*[:\s]\s*"?(\w+)"?', re.IGNORECASE)


def parse_addresses(content: list[dict]) -> list[dict]:
    """
    Convert a Swiggy MCP get_addresses content-block list into structured dicts.

    Each dict has:
        addressId (str), label (str), address (str), chip (str)

    chip is the quick-reply text shown to the user: "📍 Home", "📍 Work", etc.
    """
    addresses: list[dict] = []
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "text":
            continue
        text = block.get("text", "")

        # Try Pattern A first (most descriptive)
        matches_a = list(_ADDR_RE_A.finditer(text))
        if matches_a:
            for m in matches_a:
                label, addr, addr_id = m.groups()
                label = label.strip()
                addresses.append({
                    "addressId": addr_id.strip(),
                    "label": label,
                    "address": addr.strip(),
                    "chip": f"📍 {label}",
                })
            continue

        # Try Pattern B
        matches_b = list(_ADDR_RE_B.finditer(text))
        if matches_b:
            for m in matches_b:
                label, addr_id = m.groups()
                label = label.strip().title()
                addresses.append({
                    "addressId": addr_id.strip(),
                    "label": label,
                    "address": label,
                    "chip": f"📍 {label}",
                })
            continue

        # Pattern C — bare IDs, try to pair with surrounding label text
        ids = _ADDR_RE_C.findall(text)
        for i, addr_id in enumerate(ids):
            label = f"Address {i + 1}"
            addresses.append({
                "addressId": addr_id.strip(),
                "label": label,
                "address": label,
                "chip": f"📍 {label}",
            })

    return addresses


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
