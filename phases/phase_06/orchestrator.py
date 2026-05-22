"""Phase 6 Orchestrator integration — Personas and Templates."""

import asyncio
from typing import Any

from phases.phase_01.models.intent import UserIntent
from phases.phase_01.models.state import ConversationState
from phases.phase_02.orchestrator import Route
from phases.phase_04.services.swiggy_read import SwiggyReadClient
from phases.phase_05.utils.weights import get_weights
from phases.phase_05.agents.scorer import final_rank

from phases.phase_06.agents.persona import format_recommendations
from phases.phase_06.utils.templates import (
    get_cart_template,
    get_cancel_template,
    get_swiggy_down_template
)


async def route_message(
    route: Route, 
    intent: UserIntent, 
    state: ConversationState, 
    swiggy_client: SwiggyReadClient, 
    gemini_client
) -> list[dict[str, Any]]:
    """
    Main entrypoint that routes the classified message (Architecture §6).
    Returns the JSON bubble array for the UI.
    """
    
    # 1. TEMPLATE SHORT-CIRCUITS (Zero LLM calls)
    if route == Route.CART_ACTION:
        # Do cart logic...
        return get_cart_template({"cart_total": 450})
        
    elif route == Route.CANCEL:
        # Clear state...
        state.clear()
        return get_cancel_template()
        
        
    # 2. FULL SEARCH PIPELINE
    elif route == Route.NEW_SEARCH:
        search_task = asyncio.create_task(
            swiggy_client.search_restaurants(
                query=intent.search_query or "food",
                address_id=state.address_id
            )
        )
        
        weights = get_weights(intent)
        
        try:
            raw_restaurants = await search_task
        except Exception:
            return get_swiggy_down_template()
            
        top_6 = await final_rank(raw_restaurants, intent, gemini_client)
        
        # Save to state
        state.has_recommendations = True
        state.cached_restaurants = raw_restaurants
        
        # Format into Persona bubbles
        return await format_recommendations(intent, top_6, state.history, gemini_client)
        
        
    # 3. REFINE PIPELINE (No network call)
    elif route == Route.REFINE:
        if not state.has_recommendations or not hasattr(state, "cached_restaurants") or not state.cached_restaurants:
            return await route_message(Route.NEW_SEARCH, intent, state, swiggy_client, gemini_client)
            
        raw_restaurants = state.cached_restaurants
        top_6 = await final_rank(raw_restaurants, intent, gemini_client)
        
        return await format_recommendations(intent, top_6, state.history, gemini_client)

    
    # Fallback for unhandled routes in this phase
    return [{"text": "I'm still learning how to handle that! 😅", "quick_replies": []}]
