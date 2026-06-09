"""Parse Swiggy MCP text-blob responses into structured dicts.

Swiggy's API follows MCP protocol: all tool results come back as
  [{"type": "text", "text": "...formatted string..."}]

search_restaurants text blob format:
  "Found 10 restaurants for \"pizza\":\n
   1. Domino's Pizza — Pizzas, Italian | 4.3★ | 25 min | ₹400 for two (ID: 45605)\n"

get_addresses text blob format (confirmed from live API):
  "Found 8 saved addresses:
   1. [Other] Himanshu Mahawar: Hotel Vachi Inn, Malviya Nagar, ... (ID: 107675381)
   2. [home] Himanshu Mahawar: 6, Unnamed Road, Amer, ... (ID: 92680741)
   ..."

This module parses those blobs into lists of plain dicts that the
scorer, persona, address picker, and frontend can consume.
"""

from __future__ import annotations

import re
from collections import Counter

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
# Real Swiggy format (confirmed live):
#   "N. [Label] Person Name: Full Address, City, State PIN (ID: 12345)"
# e.g.:
#   "1. [Other] Himanshu Mahawar: Hotel Vachi Inn, Malviya Nagar, ... (ID: 107675381)"
#   "2. [home] Himanshu Mahawar: 6, Unnamed Road, Amer, ... (ID: 92680741)"

_ADDR_RE = re.compile(
    r"\d+\.\s+"           # "1. "
    r"\[([^\]]+)\]"        # [Label]  — e.g. "Other", "home", "Hotel"
    r"\s+[^:]+:\s*"        # " Person Name: "
    r"([^\n(]+?)"          # full address (stops before "(ID: ...")
    r"\s*\(ID:\s*(\w+)\)", # (ID: 12345)
    re.UNICODE,
)


def _short_area(address: str) -> str:
    """
    Extract a short, human-readable area name from a full address string.
    Takes the first non-trivial comma-segment (not a bare number or 'Unnamed Road').
    Truncated to 28 chars so it fits comfortably in a chip.
    """
    parts = [p.strip() for p in address.split(",")]
    for part in parts[:4]:
        if (
            part
            and not part.replace(" ", "").isdigit()
            and "unnamed" not in part.lower()
            and len(part) > 2
        ):
            return part[:28]
    return parts[0][:28] if parts else address[:28]


def parse_addresses(content: list[dict]) -> list[dict]:
    """
    Convert a Swiggy MCP get_addresses content-block list into structured dicts.

    Each dict has:
        addressId (str), label (str), address (str), chip (str)

    chip is the quick-reply text shown to the user: "📍 Home", "📍 Hotel",
    "📍 Malviya Nagar" etc.  Duplicate chips are suffixed " (2)", " (3)" …
    """
    raw: list[dict] = []

    for block in content:
        if not isinstance(block, dict) or block.get("type") != "text":
            continue
        text = block.get("text", "")
        for m in _ADDR_RE.finditer(text):
            label_raw, address, addr_id = m.groups()
            raw.append({
                "addressId": addr_id.strip(),
                "label":     label_raw.strip().title(),   # "other" → "Other"
                "address":   address.strip(),
            })

    if not raw:
        return raw

    # Count how many times each label appears so we know when to disambiguate
    label_counts = Counter(e["label"] for e in raw)

    addresses: list[dict] = []
    chip_seen: dict[str, int] = {}

    for entry in raw:
        label = entry["label"]
        if label_counts[label] == 1:
            # Unique label — show it directly: "📍 Home", "📍 Hotel"
            base_chip = f"📍 {label}"
        else:
            # Multiple addresses share this label (most often "Other") —
            # use the neighbourhood instead so the user can tell them apart.
            base_chip = f"📍 {_short_area(entry['address'])}"

        # Enforce global chip uniqueness with a numeric suffix
        if base_chip not in chip_seen:
            chip_seen[base_chip] = 1
            chip = base_chip
        else:
            chip_seen[base_chip] += 1
            chip = f"{base_chip} ({chip_seen[base_chip]})"

        addresses.append({
            "addressId": entry["addressId"],
            "label":     label,
            "address":   entry["address"],
            "chip":      chip,
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
