"""Agent 3 — Recommendation scorer (Architecture §6 & §7)."""

import json
from phases.phase_01.models.intent import UserIntent
from phases.phase_04.utils.parse_eta import parse_eta
from phases.phase_05.utils.weights import get_weights
import google.generativeai as genai

import logging

log = logging.getLogger(__name__)


def calculate_base_score(restaurant: dict, intent: UserIntent, weights: dict[str, float]) -> float:
    """
    Calculate deterministic score based on architecture §6.
    """
    # 1. rating_score
    raw_rating = restaurant.get("rating")
    try:
        rating = float(raw_rating) if raw_rating else 4.0
    except (TypeError, ValueError):
        rating = 4.0
    rating_score = ((rating - 4.0) / 1.0) * 100

    # 2. eta_score
    eta_min = parse_eta(restaurant.get("deliveryTime", ""))
    eta_score = max(0, ((60.0 - eta_min) / 60.0) * 100)

    # 3. price_value
    # Without item detail at search time, we approximate using costForTwo.
    try:
        cost = float(restaurant.get("costForTwo", 0)) / 2.0  # Approx per person
    except (TypeError, ValueError):
        cost = 0.0

    budget = intent.budget_max or 500  # fallback
    price_value = ((budget - cost) / budget) * 100 if budget else 100
    price_value = max(0, min(100, price_value)) # Clamp to 0-100

    # 4. distance_score
    try:
        km = float(restaurant.get("distance", 5.0))
    except (TypeError, ValueError):
        km = 5.0
    distance_score = max(0, ((10.0 - km) / 10.0) * 100)

    # 5. time_relevance (mocked to 100 for now as it needs complex logic)
    time_relevance = 100.0

    base_score = (
        (weights.get("rating", 0) * rating_score)
        + (weights.get("eta", 0) * eta_score)
        + (weights.get("price", 0) * price_value)
        + (weights.get("distance", 0) * distance_score)
        + (weights.get("time", 0) * time_relevance)
    )

    return base_score


async def gemini_rerank(intent: UserIntent, top_10: list[dict], gemini_client) -> list[float]:
    """
    Gemini soft re-rank (top 10 only) as per architecture §6.
    Returns a list of intent_match scores (0-100) in the same order.
    """
    if not top_10:
        return []

    dishes = [
        {
            "name": d.get("name", ""),
            "desc": d.get("description", ""),
            "category": d.get("category", ""),
            "cuisines": d.get("cuisines", [])
        }
        for d in top_10
    ]

    prompt = (
        f"User wants: {intent.model_dump_json()}.\n"
        f"Here are {len(dishes)} restaurants/dishes: {json.dumps(dishes)}.\n"
        "Rate each from 0 to 100 on how well it matches the user's intent.\n"
        "Return ONLY a JSON array of numbers, e.g. [85, 90, 40]."
    )

    try:
        response = await gemini_client.generate_content_async(
            contents=prompt,
            generation_config={
                "response_mime_type": "application/json",
                "temperature": 0,
            },
        )
        scores = json.loads(response.text)
        
        # Guard: if invalid, return equal scores
        if not isinstance(scores, list) or len(scores) != len(top_10):
            raise ValueError("Invalid array length or type")
            
        # Ensure all are numbers
        scores = [float(s) for s in scores]
        return scores
        
    except Exception as e:
        log.warning(f"Gemini rerank failed: {e}. Falling back to 50s.")
        return [50.0] * len(top_10)


async def final_rank(survivors: list[dict], intent: UserIntent, gemini_client) -> list[dict]:
    """
    Combine deterministic score + Gemini intent_match -> sort -> return top 6.
    """
    if not survivors:
        return []

    weights = get_weights(intent)
    
    # Calculate base scores for all survivors
    for r in survivors:
        r["_base_score"] = calculate_base_score(r, intent, weights)
        
    # Sort by base score and take top 10
    survivors.sort(key=lambda x: x["_base_score"], reverse=True)
    top_10 = survivors[:10]
    
    # Get Gemini intent scores for top 10
    intent_scores = await gemini_rerank(intent, top_10, gemini_client)
    
    intent_weight = weights.get("intent", 0)
    
    # Calculate final scores
    for i, r in enumerate(top_10):
        r["_intent_score"] = intent_scores[i]
        r["_final_score"] = r["_base_score"] + (intent_weight * intent_scores[i])
        
    # Sort top 10 by final score and return top 6
    top_10.sort(key=lambda x: x["_final_score"], reverse=True)
    return top_10[:6]
