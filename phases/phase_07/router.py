"""FastAPI SSE router (Architecture §8)."""

import json
import asyncio
import logging
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import google.generativeai as genai

from phases.phase_00.config import get_settings
from phases.phase_00.logging_setup import get_logger
from phases.phase_01.models.intent import UserIntent
from phases.phase_01.models.state import check_staleness
from phases.phase_02.orchestrator import classify, Route
from phases.phase_03.agents.intent_parser import parse_intent
from phases.phase_04.services.swiggy_read import SwiggyReadClient
from phases.phase_06.orchestrator import route_message
from phases.phase_06.utils.templates import get_stale_template
from phases.phase_07.session import get_session

log = get_logger(__name__)
router = APIRouter()


class ChatRequest(BaseModel):
    session_id: str
    message: str


async def stream_response(request: ChatRequest, client_request: Request):
    """Async generator that yields SSE events."""
    state = get_session(request.session_id)
    settings = get_settings()
    
    genai.configure(api_key=settings.gemini_api_key)
    gemini_client = genai.GenerativeModel("gemini-2.0-flash")
    swiggy_client = SwiggyReadClient()

    # 1. Check staleness (Architecture §8)
    if check_staleness(state):
        bubbles = get_stale_template()
        for bubble in bubbles:
            yield f"data: {json.dumps(bubble)}\n\n"
        yield "data: [DONE]\n\n"
        return

    msg = request.message.strip()
    state.append_message("user", msg)

    # 2. Classify route
    route = classify(msg, state)
    
    # Fast path for CART_ACTION to return cart_update
    if route == Route.CART_ACTION:
        # Mocking cart action since we don't have the ordering endpoint active yet
        state.cart_has_items = True
        bubbles = await route_message(route, UserIntent(), state, swiggy_client, gemini_client)
        for bubble in bubbles:
            yield f"data: {json.dumps(bubble)}\n\n"
            
        yield f"data: {json.dumps({'type': 'cart_update', 'cart': {'total': 450}})}\n\n"
        yield "data: [DONE]\n\n"
        return

    # 3. Parse intent (Agent 1) if needed
    intent = state.current_intent
    if route in (Route.NEW_SEARCH, Route.REFINE, Route.AMBIGUOUS):
        try:
            intent = await parse_intent(msg, state.get_context_window())
            state.current_intent = intent
        except Exception as e:
            log.error(f"Intent parse failed: {e}")
            intent = UserIntent()

    # 4. Run Pipeline (Agent 3 + 4)
    start_time = asyncio.get_event_loop().time()
    
    bubbles = await route_message(route, intent, state, swiggy_client, gemini_client)
    
    latency = (asyncio.get_event_loop().time() - start_time) * 1000
    log.info("pipeline_complete", route=route.value, latency_ms=latency)

    # 5. Stream bubbles with typing delay
    for i, bubble in enumerate(bubbles):
        # Client disconnect check (Architecture edge case)
        if await client_request.is_disconnected():
            log.warning("Client disconnected mid-stream")
            return
            
        if i > 0:
            await asyncio.sleep(0.08)  # 80ms delay between bubbles
            
        # Ensure type is set
        bubble["type"] = "bubble"
        yield f"data: {json.dumps(bubble)}\n\n"

    # 6. Stream cards if we generated recommendations
    if route in (Route.NEW_SEARCH, Route.REFINE) and state.has_recommendations:
        yield f"data: {json.dumps({'type': 'cards', 'dishes': state.cached_results[:6]})}\n\n"

    yield "data: [DONE]\n\n"


@router.post("/api/chat")
async def chat_endpoint(request: ChatRequest, client_request: Request):
    """SSE endpoint for chat UI."""
    return StreamingResponse(
        stream_response(request, client_request),
        media_type="text/event-stream"
    )
