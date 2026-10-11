"""Addresses: structured data first; text fallback copes with brackets in the address."""

from phases.phase_04.utils.parse_swiggy_content import parse_addresses, parse_addresses_structured


def test_structured_addresses_keep_custom_tags():
    sc = {"addresses": [
        {"id": "A1", "addressTag": "Home3", "addressCategory": "Home",
         "addressLine": "Himanshu Mahawar: F-2206, Apex The Kremlin. (Apex The Kremlin), Ghaziabad"},
        {"id": "A2", "addressTag": "home", "addressCategory": "Home",
         "addressLine": "Himanshu Mahawar: 6, Unnamed Road, Amer"},
        {"id": "A3", "addressTag": None, "addressCategory": "Other",
         "addressLine": "Himanshu Mahawar: Birla Institute of Technology, Malviya Nagar"},
    ]}
    out = parse_addresses_structured(sc)
    assert [a["addressId"] for a in out] == ["A1", "A2", "A3"]
    assert [a["label"] for a in out] == ["Home3", "Home", "Other"]
    assert out[0]["address"].startswith("F-2206")  # "Name: " prefix stripped
    assert out[0]["chip"] == "📍 Home3"


def test_text_fallback_handles_brackets_in_address():
    text = (
        "Found 2 saved addresses:\n"
        "1. [Home3] Himanshu Mahawar: F-2206, Apex. (Apex The Kremlin), Ghaziabad (ID: 1_AbC-x)\n"
        "2. [home] Himanshu Mahawar: 6, Unnamed Road, Amer (ID: 92680741__AZv)\n"
    )
    out = parse_addresses([{"type": "text", "text": text}])
    assert [a["addressId"] for a in out] == ["1_AbC-x", "92680741__AZv"]
    assert "(Apex The Kremlin)" in out[0]["address"]
