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

# Restaurant thumbnail at the top of get_restaurant_menu blob:
#   "Menu for Wow! Momo (ID: 1018997) [image: https://...JPG]"
_MENU_HEADER_RE = re.compile(
    r"Menu\s+for\s+(.+?)\s+\(ID:\s*(\w+)\)"
    r"(?:\s*\[image:\s*(https?://\S+?)\])?",
    re.UNICODE,
)

# One menu item line in get_restaurant_menu blob:
#   "  - Dish Name — ₹129 | Veg/Non-veg[, Bestseller][, has addons] [image: URL] (ID: 12345)"
_MENU_ITEM_RE = re.compile(
    r"^\s*[-•]\s+"                  # bullet
    r"(.+?)"                        # dish name
    r"\s*[—–-]\s*"                  # separator
    r"₹(\d+(?:\.\d+)?)"             # price
    r"\s*\|\s*"
    r"(Veg|Non-veg)"                # veg status
    r"([^[\n(]*)"                   # trailing tags (e.g. ", Bestseller, has addons")
    r"(?:\s*\[image:\s*(https?://\S+?)\])?"  # optional image URL
    r"\s*\(ID:\s*(\w+)\)",           # itemId
    re.UNICODE | re.MULTILINE,
)

# Category header inside menu blob: "## 99 Store" / "## Minimum 50% off"
_MENU_CATEGORY_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


# Matches one restaurant line in the Swiggy search_restaurants text blob.
# Format: N. Name [(Ad)] — Cuisines | Rating★ | ETA min | ₹Cost for two (ID: id)
_RESTAURANT_RE = re.compile(
    r"\d+\.\s+"               # "1. "
    r"(.+?)"                  # name (non-greedy)
    r"(?:\s*\(Ad\))?"         # optional "(Ad)" badge
    r"\s*[—–-]\s*"            # em-dash separator
    r"(.+?)"                  # cuisines
    r"\s*\|\s*"
    r"([\d.]+|undefined)★"    # rating, may be literally "undefined" for new places
    r"\s*\|\s*"
    r"(\d+)\s*min"            # ETA minutes
    r"\s*\|\s*"
    r"₹(\d+)\s*for two"       # cost-for-two in INR
    r"\s*\(ID:\s*(\w+)\)",    # restaurantId
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


# Cuisine → emoji map. Used as a visual placeholder in DishCard because
# Swiggy's search_restaurants text blob carries no image URLs.
_CUISINE_EMOJI = [
    ("pizza", "🍕"), ("biryani", "🍛"), ("burger", "🍔"), ("chinese", "🥡"),
    ("pasta", "🍝"), ("italian", "🍝"), ("sushi", "🍣"), ("dosa", "🥞"),
    ("south indian", "🥞"), ("indian", "🍛"), ("north indian", "🫓"),
    ("mughlai", "🍢"), ("kebab", "🍢"), ("dessert", "🍰"), ("cake", "🍰"),
    ("ice cream", "🍦"), ("falooda", "🍨"), ("shake", "🥤"), ("juice", "🥤"),
    ("coffee", "☕"), ("cafe", "☕"), ("beverages", "🥤"), ("tea", "🍵"),
    ("bakery", "🥐"), ("sandwich", "🥪"), ("salad", "🥗"), ("healthy", "🥗"),
    ("snack", "🍿"), ("street food", "🌮"), ("chicken", "🍗"), ("seafood", "🦐"),
    ("thai", "🍜"), ("noodle", "🍜"), ("momo", "🥟"), ("fast food", "🍟"),
    ("american", "🍔"), ("continental", "🍽️"), ("paneer", "🧀"),
]


def _cuisine_emoji(cuisines: str) -> str:
    """Pick the best matching emoji for the first cuisine token in the string."""
    lower = cuisines.lower()
    for needle, emoji in _CUISINE_EMOJI:
        if needle in lower:
            return emoji
    return "🍽️"  # generic plate fallback


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
            try:
                rating_val = float(rating_s)
            except (TypeError, ValueError):
                # "undefined" — newly listed restaurant; treat as unrated.
                # The 3.5 rating gate will drop it (correct behavior — unproven).
                rating_val = None
            restaurants.append({
                # IDs
                "restaurantId": rest_id.strip(),
                "id": rest_id.strip(),          # DishCard key / cart key
                # Swiggy MCP search only returns open+deliverable restaurants;
                # set explicitly so the OPEN hard gate (filters.py) passes.
                "availabilityStatus": "OPEN",
                # Display
                "name": name.strip(),
                "restaurant": name.strip(),     # alias used by persona _prepare_context
                "cuisines": cuisines.strip(),
                # Scoring fields
                "rating": rating_val,
                "deliveryTime": f"{eta_int} min",  # string for parse_eta()
                "eta": eta_int,                    # integer for DishCard display
                # Pricing
                "costForTwo": cost_int,
                "price": cost_int,              # DishCard renders ₹{price}
                "priceLabel": "for 2",          # shown next to price in card
                # Cuisine-based placeholder emoji so cards have a visual identity
                # even without real image URLs (Swiggy search blob has none)
                "placeholder": _cuisine_emoji(cuisines),
                # Veg status unknown at restaurant level
                "veg": None,
            })
    return restaurants


# ── Menu item parsing (get_restaurant_menu) ──────────────────────────────────

def parse_menu(content: list[dict]) -> dict:
    """
    Parse a get_restaurant_menu MCP response into:
      {
        "restaurantId": str,
        "name":         str,
        "thumbnail":    str | None,
        "items":        list[dict],   # ready for DishCard
      }
    Each item carries: id, name, price, veg (bool), category, imageUrl,
    bestseller, restaurantId, restaurant (name) — so it slots straight into
    state.cached_results and the `cards` SSE event.
    """
    name = ""
    rest_id = ""
    thumbnail = None
    items: list[dict] = []

    for block in content:
        if not isinstance(block, dict) or block.get("type") != "text":
            continue
        text = block.get("text", "")

        # Errors come back as a plain "addressId is required..." string — bail
        if "addressId is required" in text or text.startswith("Error"):
            return {"restaurantId": "", "name": "", "thumbnail": None, "items": []}

        m = _MENU_HEADER_RE.search(text)
        if m:
            name = m.group(1).strip()
            rest_id = m.group(2).strip()
            thumbnail = m.group(3)

        # Build a line→category map so each item carries its section name
        category_at: list[tuple[int, str]] = []
        for cm in _MENU_CATEGORY_RE.finditer(text):
            category_at.append((cm.start(), cm.group(1).strip()))

        def category_for(offset: int) -> str:
            cur = ""
            for off, label in category_at:
                if off <= offset:
                    cur = label
                else:
                    break
            return cur

        for im in _MENU_ITEM_RE.finditer(text):
            dish_name, price_s, veg_s, tags, image_url, item_id = im.groups()
            try:
                price = int(float(price_s))
            except (TypeError, ValueError):
                continue
            is_veg = veg_s.lower() == "veg"
            bestseller = "bestseller" in (tags or "").lower()
            items.append({
                "id":           item_id.strip(),
                "itemId":       item_id.strip(),
                "name":         dish_name.strip(),
                "restaurant":   name,
                "restaurantId": rest_id,
                "price":        price,
                "veg":          is_veg,
                "category":     category_for(im.start()),
                "imageUrl":     image_url,
                "bestseller":   bestseller,
                # Cards reuse these fields:
                "cuisines":     category_for(im.start()) or name,
                "rating":       None,  # menu items don't have per-item ratings
                "placeholder":  "⭐" if bestseller else _cuisine_emoji(category_for(im.start()) or name),
            })

    return {"restaurantId": rest_id, "name": name, "thumbnail": thumbnail, "items": items}
