"""Phase 5 Orchestrator integration — Parallelization and REFINE route."""

import asyncio
from phases.phase_01.models.intent import UserIntent
from phases.phase_01.models.state import ConversationState
from phases.phase_04.services.swiggy_read import SwiggyReadClient
from phases.phase_05.utils.weights import get_weights
from phases.phase_05.agents.scorer import final_rank, calculate_base_score

# Note: Agent 2 validation is normally done before this.
# This assumes intent has already been validated.

async def route_new_search(intent: UserIntent, state: ConversationState, swiggy_client: SwiggyReadClient, gemini_client) -> list[dict]:
    """
    Parallel routing for Route.NEW_SEARCH (Architecture §7).
    Fires the network call and configures weights simultaneously.
    """
    # 1. Start the Swiggy API call in the background
    search_task = asyncio.create_task(
        swiggy_client.search_restaurants(
            query=intent.search_query or "food",
            lat=state.lat,
            lng=state.lng
        )
    )
    
    # 2. Compute weights synchronously (instant)
    weights = get_weights(intent)
    
    # 3. Wait for the API call to finish
    try:
        raw_restaurants = await search_task
    except Exception as e:
        # Fallback or error handling
        return []

    # 4. In a full pipeline, filters would be applied here (Agent 3 step 1)
    # For Phase 5 demonstration, we assume `raw_restaurants` are pre-filtered or we just score them all.
    # We pass the full list to final_rank.
    
    top_6 = await final_rank(raw_restaurants, intent, gemini_client)
    
    # Cache the results in state for the REFINE route
    state.has_recommendations = True
    state.cached_restaurants = raw_restaurants
    
    return top_6


async def route_refine(intent: UserIntent, state: ConversationState, gemini_client) -> list[dict]:
    """
    Routing for Route.REFINE (Architecture §7).
    Re-scores the cached restaurant list without hitting the network again.
    """
    if not state.has_recommendations or not hasattr(state, "cached_restaurants") or not state.cached_restaurants:
        # If no cache, fall back to new search
        return []

    raw_restaurants = state.cached_restaurants
    
    # 1. Get NEW weights based on the refined intent
    weights = get_weights(intent)
    
    # 2. Re-score and rerank the cached data using the new intent
    top_6 = await final_rank(raw_restaurants, intent, gemini_client)
    
    return top_6
