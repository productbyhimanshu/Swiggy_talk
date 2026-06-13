"""Quality judge — grade Bhook's actual replies against ideal references.

Why this exists: the basic live_eval checks correctness (right field, right
route). It does NOT check whether replies *feel like Bhook*. Without a
quality judge, every persona prompt edit is vibes.

How it works:
  1. 12 scenarios with hand-written "ideal" Bhook replies.
  2. For each, drive the actual pipeline (mocked Swiggy data, real LLM).
  3. A judge LLM scores the actual reply on 4 axes:
       - relevance (0-5): addresses what the user asked
       - tone     (0-5): sounds like Bhook (warm, casual, no robot-speak)
       - brevity  (0-5): short and punchy (penalises walls of text)
       - helpful  (0-5): moves the conversation forward usefully
  4. We aggregate and gate at avg >= 4.0 on every axis.

Usage:
    PYTHONPATH=. python3.11 scripts/quality_judge.py
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

from phases.phase_00.config import get_settings  # noqa: E402
from phases.phase_00.services.gemini_client import GeminiModel  # noqa: E402
from phases.phase_01.models.intent import UserIntent  # noqa: E402
from phases.phase_06.agents.persona import format_recommendations  # noqa: E402

# ── Sample dish/restaurant data used in the scenarios ─────────────────────────
SAMPLE_DISHES = [
    {"itemId": "1", "name": "Veg Pahari Steam Momo", "restaurant": "Wow! Momo",
     "price": 109, "veg": True, "bestseller": True, "rating": 4.2, "eta": 35},
    {"itemId": "2", "name": "Chicken Crunchy Momo", "restaurant": "Wow! Momo",
     "price": 165, "veg": False, "bestseller": True, "rating": 4.2, "eta": 35},
    {"itemId": "3", "name": "Veg Steamed Momo Plate", "restaurant": "Marky Momos",
     "price": 200, "veg": True, "bestseller": False, "rating": 4.3, "eta": 49},
]

SAMPLE_RESTAURANTS = [
    {"name": "Punjab Grill", "cuisines": "North Indian", "rating": 4.5, "eta": 30, "price": 400, "restaurantId": "1"},
    {"name": "Wok Express",  "cuisines": "Chinese",       "rating": 4.2, "eta": 25, "price": 300, "restaurantId": "2"},
    {"name": "Dosa Plaza",   "cuisines": "South Indian",  "rating": 4.7, "eta": 40, "price": 200, "restaurantId": "3"},
]


# ── 12 scenarios: user input + ideal Bhook reply ──────────────────────────────
SCENARIOS = [
    {
        "name":   "hungry_cheap_dinner",
        "intent": UserIntent(search_query="dinner", budget_max=200, mood="heavy"),
        "items":  SAMPLE_RESTAURANTS,
        "history":[{"role":"user","text":"something cheap and filling for dinner"}],
        "ideal":  "three solid filling picks under ₹200 — pick or i can mix it up",
    },
    {
        "name":   "rough_day_comfort",
        "intent": UserIntent(search_query="comfort food", mood="comfort"),
        "items":  SAMPLE_RESTAURANTS,
        "history":[{"role":"user","text":"had a rough day, comfort food"}],
        "ideal":  "oof, sending warm food. that work or want different?",
    },
    {
        "name":   "celebrating",
        "intent": UserIntent(search_query="dinner", mood="celebratory"),
        "items":  SAMPLE_RESTAURANTS,
        "history":[{"role":"user","text":"celebrating today, want something good"}],
        "ideal":  "nice — picked top-rated spots. sharing or solo?",
    },
    {
        "name":   "veg_momos_specific",
        "intent": UserIntent(search_query="momos", budget_max=200, veg_nonveg="veg"),
        "items":  [d for d in SAMPLE_DISHES if d["veg"]],
        "history":[{"role":"user","text":"veg momos under 200"}],
        "ideal":  "got you two veg momo picks under ₹200. tap to add.",
    },
    {
        "name":   "rushed",
        "intent": UserIntent(search_query="lunch", speed="fast"),
        "items":  SAMPLE_RESTAURANTS,
        "history":[{"role":"user","text":"fast lunch, only have 25 min"}],
        "ideal":  "sorted by speed — fastest is 25 min. pick or want even quicker?",
    },
    {
        "name":   "biryani_vague",
        "intent": UserIntent(search_query="biryani", veg_nonveg="nonveg"),
        "items":  SAMPLE_RESTAURANTS,
        "history":[{"role":"user","text":"biryani"}, {"role":"assistant","text":"veg or non-veg?"},{"role":"user","text":"non-veg"}],
        "ideal":  "non-veg biryani spots — top-rated first 👇 want spicier?",
    },
    {
        "name":   "spicy_request",
        "intent": UserIntent(search_query="spicy", veg_nonveg="nonveg"),
        "items":  SAMPLE_RESTAURANTS,
        "history":[{"role":"user","text":"something spicy"}],
        "ideal":  "spicy non-veg picks 🌶️ — milder if these are too much?",
    },
    {
        "name":   "no_results_friendly",
        "intent": UserIntent(search_query="sushi", budget_max=100),
        "items":  [],
        "history":[{"role":"user","text":"sushi under 100"}],
        "ideal":  "nothing under ₹100 for sushi nearby — bump budget or try something else?",
    },
    {
        "name":   "refine_cheaper",
        "intent": UserIntent(search_query="pizza", budget_max=200, veg_nonveg="veg"),
        "items":  SAMPLE_RESTAURANTS,
        "history":[{"role":"user","text":"pizza"},{"role":"assistant","text":"veg or non-veg?"},{"role":"user","text":"veg"},{"role":"user","text":"cheaper"}],
        "ideal":  "trimmed it — three veg pizza picks under ₹200.",
    },
    {
        "name":   "healthy",
        "intent": UserIntent(search_query="healthy", diet="healthy"),
        "items":  SAMPLE_RESTAURANTS,
        "history":[{"role":"user","text":"healthy lunch"}],
        "ideal":  "lighter spots picked — salad-y or warm-bowl healthy?",
    },
    {
        "name":   "kids_party",
        "intent": UserIntent(search_query="pizza burger"),
        "items":  SAMPLE_RESTAURANTS,
        "history":[{"role":"user","text":"kids party need pizza and burgers"}],
        "ideal":  "got crowd-pleasers — go shareable or individuals?",
    },
    {
        "name":   "single_word",
        "intent": UserIntent(search_query="biryani"),
        "items":  SAMPLE_RESTAURANTS,
        "history":[{"role":"user","text":"biryani"}],
        "ideal":  "biryani spots near you — veg or chicken?",
    },
]


# ── Judge prompt ──────────────────────────────────────────────────────────────

JUDGE_SYSTEM = """\
You are a strict quality evaluator for a conversational food-ordering AI named Bhook. Bhook's character: warm, friend-on-WhatsApp, casual lowercase, max 2 short bubbles, 1 emoji max per bubble, never lists restaurant names or prices in text (cards do that), always asks a useful follow-up.

Score the ACTUAL reply on each axis 0-5. Be strict — 5 is reserved for ideal output.

Axes:
  relevance: does it address what the user asked?  (0=ignores user, 5=perfectly addressed)
  tone:      does it sound like Bhook?  (0=robotic/corporate, 5=natural friend tone)
  brevity:   is it short and punchy?  (0=wall of text, 5=under 25 words total)
  helpful:   does it move the convo forward?  (0=dead-end, 5=clear next action)

Penalise heavily:
  - "I'd be happy to assist you" or other corporate-AI phrases (tone: max 2)
  - Listing restaurant/dish names in the text (relevance: max 2; tone: max 2)
  - 3+ bubbles or any bubble over 30 words (brevity: max 2)
  - No follow-up question or chip (helpful: max 2)

Output ONLY JSON: {"relevance":N,"tone":N,"brevity":N,"helpful":N,"comment":"one sentence"}.
"""


async def judge_one(client, scenario_name: str, user_msgs: list[str], ideal: str, actual: str) -> dict:
    payload = json.dumps({
        "scenario":     scenario_name,
        "user_history": user_msgs,
        "ideal_reply":  ideal,
        "actual_reply": actual,
    }, ensure_ascii=False)
    try:
        resp = await client.generate_content_async(
            contents=[JUDGE_SYSTEM, payload],
            generation_config={
                "response_mime_type": "application/json",
                "temperature": 0.0,
                "max_output_tokens": 512,
            },
        )
        data = json.loads((resp.text or "{}").strip())
        return {
            "relevance": float(data.get("relevance", 0)),
            "tone":      float(data.get("tone", 0)),
            "brevity":   float(data.get("brevity", 0)),
            "helpful":   float(data.get("helpful", 0)),
            "comment":   str(data.get("comment", ""))[:140],
        }
    except Exception as exc:
        return {"relevance": 0, "tone": 0, "brevity": 0, "helpful": 0, "comment": f"judge_error: {exc}"}


async def run_one(client, sc: dict) -> tuple[dict, str]:
    bubbles = await format_recommendations(sc["intent"], sc["items"], sc["history"], client)
    text = " ".join(b.get("text", "") for b in bubbles)
    user_msgs = [m.get("text", "") for m in sc["history"] if m.get("role") == "user"]
    score = await judge_one(client, sc["name"], user_msgs, sc["ideal"], text)
    return score, text


async def main() -> int:
    print("=" * 64)
    print("  QUALITY JUDGE — 12 scenarios scored on 4 axes")
    print("=" * 64)
    settings = get_settings()
    client = GeminiModel(api_key=settings.gemini_api_key)
    start = time.time()

    rows: list[tuple[str, dict, str]] = []
    for sc in SCENARIOS:
        score, actual = await run_one(client, sc)
        rows.append((sc["name"], score, actual))
        sym = "✅" if min(score["relevance"], score["tone"], score["brevity"], score["helpful"]) >= 4.0 else "⚠️"
        print(f"\n{sym} {sc['name']}")
        print(f"   r:{score['relevance']:.1f} t:{score['tone']:.1f} b:{score['brevity']:.1f} h:{score['helpful']:.1f} — {score['comment']}")
        print(f"   actual: {actual[:120]}")

    print("\n" + "=" * 64)
    avg = {
        ax: sum(s[ax] for _, s, _ in rows) / len(rows)
        for ax in ("relevance", "tone", "brevity", "helpful")
    }
    print(f"  AVG  relevance={avg['relevance']:.2f}  tone={avg['tone']:.2f}  "
          f"brevity={avg['brevity']:.2f}  helpful={avg['helpful']:.2f}")
    passed = all(v >= 4.0 for v in avg.values())
    print(f"  {'✅ PASS' if passed else '❌ FAIL'} (target: avg ≥4.0 on every axis) — {time.time() - start:.0f}s")
    print("=" * 64)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
