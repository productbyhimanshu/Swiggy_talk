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
    get_greeting_template,
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
    if route == Route.GREETING:
        return get_greeting_template()

    elif route == Route.CART_ACTION:
        # Do cart logic...
        return get_cart_template({"cart_total": 450})

    elif route == Route.CANCEL:
        # Reset mutable search state (ConversationState is a Pydantic model — no .clear())
        state.cached_results = []
        state.has_recommendations = False
        state.current_restaurant_id = None
        state.awaiting_clarification = False
        return get_cancel_template()


    # 2. FULL SEARCH PIPELINE
    # AMBIGUOUS also goes through the search pipeline — intent is already parsed
    # by the time we get here (router.py runs parse_intent for AMBIGUOUS too)
    elif route in (Route.NEW_SEARCH, Route.AMBIGUOUS):
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

        # Save top_6 (scored + ranked) so the cards event and REFINE path
        # both see the same structured list the UI was shown.
        state.has_recommendations = True
        state.cached_results = top_6

        # Format into Persona bubbles
        return await format_recommendations(intent, top_6, state.message_history, gemini_client)


    # 3. REFINE PIPELINE (No network call)
    elif route == Route.REFINE:
        if not state.has_recommendations or not state.cached_results:
            return await route_message(Route.NEW_SEARCH, intent, state, swiggy_client, gemini_client)

        raw_restaurants = state.cached_results
        top_6 = await final_rank(raw_restaurants, intent, gemini_client)

        return await format_recommendations(intent, top_6, state.message_history, gemini_client)


    # Fallback for unhandled routes in this phase
    return [{"text": "I'm still learning how to handle that! 😅", "quick_replies": []}]
