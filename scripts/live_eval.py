"""Live eval — runs intent + persona checks against the REAL Gemini API.

Unlike the Phase 12 suite (mocked fixtures), this catches model drift:
  - 20 intent prompts → field-level accuracy (target >= 95%)
  - 5 persona scenarios → fabrication + no-listing rule (target: 0 violations)

Rate-limit aware: free tier is 20 req/min, so calls are spaced ~4s apart.
Total runtime ~2 min. Never places orders; read-only Gemini calls.

Usage:
    PYTHONPATH=. python3.11 scripts/live_eval.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
logging.disable(logging.CRITICAL)

from phases.phase_01.models.intent import UserIntent  # noqa: E402
from phases.phase_00.config import get_settings  # noqa: E402

CALL_GAP_SECS = 0.5  # Emergent proxy has no free-tier rate cap

# ── Intent eval set — prompt + field predicates ───────────────────────────────
# Each check: field name → predicate(value) -> bool

def _contains(*words):
    return lambda v: v is not None and any(w in str(v).lower() for w in words)

def _equals(*allowed):
    return lambda v: v in allowed

def _is_none(v):
    return v is None

INTENT_CASES: list[tuple[str, dict]] = [
    ("veg pizza under 300",                        {"search_query": _contains("pizza"), "veg_nonveg": _equals("veg"), "budget_max": _equals(300)}),
    ("chicken biryani",                            {"search_query": _contains("biryani"), "veg_nonveg": _equals("nonveg", None)}),
    ("something healthy and light",                {"diet": _contains("healthy", "light"), "search_query": lambda v: v is not None}),
    ("I want dinner delivered by 9 pm",            {"timing": _equals("21:00"), "timing_type": _equals("deliver_by")}),
    ("cheap food under 150 rupees",                {"budget_max": _equals(150)}),
    ("fast delivery burgers",                      {"search_query": _contains("burger"), "speed": _equals("fast")}),
    ("south indian breakfast",                     {"search_query": _contains("south indian", "dosa", "idli", "breakfast")}),
    ("paneer dishes",                              {"search_query": _contains("paneer"), "veg_nonveg": _equals("veg", None)}),
    ("comfort food it's been a rough day",         {"mood": _contains("comfort")}),
    ("high protein meals",                         {"diet": _contains("protein")}),
    ("chinese noodles under 250",                  {"search_query": _contains("noodle", "chinese"), "budget_max": _equals(250)}),
    ("ice cream",                                  {"search_query": _contains("ice cream", "icecream", "dessert")}),
    ("lunch at 1pm tomorrow",                      {"timing": _equals("13:00")}),
    ("anything spicy",                             {"search_query": _contains("spicy")}),
    ("pure veg thali",                             {"search_query": _contains("thali"), "veg_nonveg": _equals("veg")}),
    ("momos",                                      {"search_query": _contains("momo")}),
    ("italian pasta nothing too expensive",        {"search_query": _contains("pasta", "italian")}),
    ("non veg starters for a party",               {"veg_nonveg": _equals("nonveg")}),
    ("I have 500 rupees what can I get",           {"budget_max": _equals(500)}),
    ("late night snacks",                          {"search_query": _contains("snack", "late night")}),
]

# ── Persona eval set — fixed input data, check output rules ──────────────────

PERSONA_RESTAURANTS = [
    {"name": "Punjab Grill", "cuisines": "North Indian", "rating": 4.5, "eta": 30, "costForTwo": 400, "restaurantId": "1"},
    {"name": "Wok Express", "cuisines": "Chinese", "rating": 4.2, "eta": 25, "costForTwo": 300, "restaurantId": "2"},
    {"name": "Dosa Plaza", "cuisines": "South Indian", "rating": 4.7, "eta": 40, "costForTwo": 200, "restaurantId": "3"},
]

PERSONA_CASES = [
    UserIntent(search_query="north indian", budget_max=400),
    UserIntent(search_query="chinese", speed="fast"),
    UserIntent(search_query="dosa", veg_nonveg="veg"),
    UserIntent(search_query="dinner", mood="comfort"),
    UserIntent(search_query="food"),
]


async def eval_intent() -> tuple[int, int, list[str]]:
    from phases.phase_03.agents.intent_parser import parse_intent

    total_checks = passed_checks = 0
    failures: list[str] = []

    for prompt, checks in INTENT_CASES:
        try:
            intent = await parse_intent(prompt, [])
        except Exception as exc:
            total_checks += len(checks)
            failures.append(f"  ✗ {prompt!r} — parse failed: {str(exc)[:80]}")
            await asyncio.sleep(CALL_GAP_SECS)
            continue

        for field, predicate in checks.items():
            total_checks += 1
            value = getattr(intent, field, None)
            if predicate(value):
                passed_checks += 1
            else:
                failures.append(f"  ✗ {prompt!r} — {field}={value!r}")

        await asyncio.sleep(CALL_GAP_SECS)

    return passed_checks, total_checks, failures


async def eval_persona() -> tuple[int, int, list[str]]:
    from phases.phase_00.services.gemini_client import GeminiModel
    from phases.phase_06.agents.persona import format_recommendations

    settings = get_settings()
    client = GeminiModel(api_key=settings.gemini_api_key)

    total = len(PERSONA_CASES)
    passed = 0
    failures: list[str] = []
    input_names = [r["name"] for r in PERSONA_RESTAURANTS]

    for i, intent in enumerate(PERSONA_CASES):
        bubbles = await format_recommendations(intent, PERSONA_RESTAURANTS, [], client)
        violations = []

        if not isinstance(bubbles, list) or not all(isinstance(b, dict) and "text" in b for b in bubbles):
            violations.append("invalid bubble schema")
        else:
            all_text = " ".join(b["text"] for b in bubbles)
            # No-listing rule: persona must not name restaurants (cards show them)
            leaked = [n for n in input_names if n in all_text]
            if leaked:
                violations.append(f"listed restaurants in text: {leaked}")
            if len(bubbles) > 3:
                violations.append(f"too many bubbles ({len(bubbles)})")
            # Fabrication: prices not present in input data
            import re
            for amount in re.findall(r"₹\s*(\d+)", all_text):
                if int(amount) not in (200, 300, 400) and int(amount) != (intent.budget_max or -1):
                    violations.append(f"fabricated price ₹{amount}")

        if violations:
            failures.append(f"  ✗ persona case {i+1} ({intent.search_query}): {'; '.join(violations)}")
        else:
            passed += 1

        await asyncio.sleep(CALL_GAP_SECS)

    return passed, total, failures


async def main() -> int:
    print("=" * 64)
    print("  LIVE EVAL — real Gemini calls (rate-limit paced, ~2 min)")
    print("=" * 64)

    start = time.time()

    print("\n[1/2] Intent accuracy (20 prompts)...")
    ok, total, failures = await eval_intent()
    intent_pct = 100.0 * ok / total if total else 0.0
    print(f"  intent checks: {ok}/{total} = {intent_pct:.1f}%  (target ≥95%)")
    for f in failures:
        print(f)

    print("\n[2/2] Persona fabrication / no-listing (5 scenarios)...")
    p_ok, p_total, p_failures = await eval_persona()
    print(f"  persona clean: {p_ok}/{p_total}  (target {p_total}/{p_total})")
    for f in p_failures:
        print(f)

    elapsed = time.time() - start
    intent_pass = intent_pct >= 95.0
    persona_pass = p_ok == p_total
    verdict = "✅ PASS" if (intent_pass and persona_pass) else "❌ FAIL"

    print("\n" + "=" * 64)
    print(f"  {verdict} — intent {intent_pct:.1f}% | persona {p_ok}/{p_total} | {elapsed:.0f}s")
    print("=" * 64)
    return 0 if (intent_pass and persona_pass) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
