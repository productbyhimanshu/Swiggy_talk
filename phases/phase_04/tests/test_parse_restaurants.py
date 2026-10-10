"""parse_restaurants handles both Swiggy search formats (JSON and legacy text)."""

import json

from phases.phase_04.utils.parse_swiggy_content import parse_restaurants


def _block(text: str) -> list[dict]:
    return [{"type": "text", "text": text}]


def test_json_format():
    payload = {
        "restaurants": [
            {
                "id": "195224",
                "name": "Biryani Blues (Ad)",
                "cuisines": ["Biryani", " Hyderabadi"],
                "avgRating": 4.2,
                "costForTwo": "₹400 for two",
                "deliveryTimeMinutes": 29,
                "deliveryTimeRange": "25-30 MINS",
                "imageUrl": "https://example.com/a.jpg",
                "availabilityStatus": "OPEN",
            },
            {"id": "926057", "name": "Bikkgane Biryani", "cuisines": [],
             "avgRating": None, "costForTwo": "", "deliveryTimeMinutes": 21},
        ]
    }
    out = parse_restaurants(_block(json.dumps(payload)))

    assert [r["id"] for r in out] == ["195224", "926057"]
    first = out[0]
    assert first["name"] == "Biryani Blues"
    assert first["cuisines"] == "Biryani, Hyderabadi"
    assert first["rating"] == 4.2
    assert first["eta"] == 29 and first["deliveryTime"] == "29 min"
    assert first["costForTwo"] == 400
    assert first["availabilityStatus"] == "OPEN"
    assert first["imageUrl"] == "https://example.com/a.jpg"
    assert out[1]["rating"] is None and out[1]["costForTwo"] == 0


def test_json_with_trailing_text():
    text = (
        '{"restaurants":[{"id":"1","name":"A","avgRating":4.1,'
        '"deliveryTimeMinutes":20,"costForTwo":"₹300 for two"}]}\n\n'
        "Note: a widget already displays these results."
    )
    out = parse_restaurants(_block(text))
    assert len(out) == 1 and out[0]["id"] == "1"


def test_json_empty_list():
    assert parse_restaurants(_block('{"restaurants": []}')) == []


def test_legacy_text_format_still_parses():
    text = (
        'Found 1 restaurants for "pizza":\n'
        "1. Domino's Pizza — Pizzas, Italian | 4.3★ | 25 min | ₹400 for two (ID: 45605)\n"
    )
    out = parse_restaurants(_block(text))
    assert len(out) == 1
    assert out[0]["id"] == "45605" and out[0]["rating"] == 4.3
