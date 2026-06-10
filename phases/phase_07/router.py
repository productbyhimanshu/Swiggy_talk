"""FastAPI SSE router (Architecture §8).

Address resolution rule (architecture §2):
  - address_id is set via POST /api/set-address (frontend popup flow).
  - NEVER via GPS.  NEVER injected into the chat message stream.
  - If a search is attempted without an address, a single gentle bubble is
    returned asking the user to tap the 📍 button; no gate, no blocking loop.

SSE event types emitted:
  bubble      — AI chat bubble with optional quick_replies[]
  cards       — restaurant card list
  cart_update — cart total change
  [DONE]      — stream end sentinel
"""

import json
import asyncio
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import google.generativeai as genai

from phases.phase_00.config import get_settings
from phases.phase_00.logging_setup import get_logger
from phases.phase_01.models.intent import UserIntent
from phases.phase_01.models.state import ConversationState, check_staleness
from phases.phase_02.orchestrator import classify, Route
from phases.phase_03.agents.intent_parser import parse_intent
from phases.phase_04.services.swiggy_read import SwiggyReadClient
from phases.phase_06.orchestrator import route_message
from phases.phase_06.utils.templates import get_stale_template
from phases.phase_07.session import get_session

log = get_logger(__name__)
router = APIRouter()


# ── Request / response models ─────────────────────────────────────────────────

class ChatRequest(BaseModel):
    session_id: str
    message: str


class SetAddressRequest(BaseModel):
    session_id: str
    address_id: str
    label: str = ""
    chip:  str = ""
    address: str = ""


# ── Address REST endpoints ────────────────────────────────────────────────────

@router.get("/api/addresses")
async def addresses_endpoint(session_id: str):
    """
    Return the user's saved Swiggy delivery addresses.
    Called by the frontend address picker popup — never from the chat flow.
    """
    swiggy_client = SwiggyReadClient()
    try:
        addresses = await swiggy_client.get_addresses()
        return {"addresses": addresses}
    except Exception as exc:
        log.error("get_addresses_endpoint_failed", error=str(exc))
        return {"addresses": [], "error": str(exc)}


@router.post("/api/set-address")
async def set_address_endpoint(req: SetAddressRequest):
    """
    Store the user-selected addressId in session state.
    Called when the user picks an address in the popup.
    """
    state = get_session(req.session_id)
    state.address_id = req.address_id
    log.info("address_set_via_popup", session=req.session_id, address_id=req.address_id, label=req.label)
    return {"ok": True}


# ── Chat SSE endpoint ─────────────────────────────────────────────────────────

async def stream_response(request: ChatRequest, client_request: Request):
    """Async generator that yields SSE events."""
    state = get_session(request.session_id)
    settings = get_settings()

    genai.configure(api_key=settings.gemini_api_key)
    gemini_client = genai.GenerativeModel("gemini-2.5-flash-lite")
    swiggy_client = SwiggyReadClient()

    # ── 1. Staleness check ────────────────────────────────────────────────────
    if check_staleness(state):
        for bubble in get_stale_template():
            yield f"data: {json.dumps(bubble)}\n\n"
        yield "data: [DONE]\n\n"
        return

    msg = request.message.strip()
    state.append_message("user", msg)

    # ── 2. Classify route ─────────────────────────────────────────────────────
    route = classify(msg, state)

    # ── 3. Address guard (non-blocking) ──────────────────────────────────────
    # If the user is trying to search but hasn't set an address yet, nudge them
    # to use the 📍 button — don't block the whole conversation.
    search_routes = (Route.NEW_SEARCH, Route.AMBIGUOUS, Route.REFINE, Route.IN_RESTAURANT, Route.SCHEDULE)
    if route in search_routes and not state.address_id:
        yield f"data: {json.dumps({'type': 'bubble', 'text': 'Tap 📍 above to set your delivery address first — then I can find restaurants near you!', 'quick_replies': []})}\n\n"
        yield "data: [DONE]\n\n"
        return

    # ── 4. Fast path for CART_ACTION ─────────────────────────────────────────
    if route == Route.CART_ACTION:
        state.cart_has_items = True
        bubbles = await route_message(route, UserIntent(), state, swiggy_client, gemini_client)
        for bubble in bubbles:
            bubble.setdefault("type", "bubble")
            yield f"data: {json.dumps(bubble)}\n\n"
        yield f"data: {json.dumps({'type': 'cart_update', 'cart': {'total': 450}})}\n\n"
        yield "data: [DONE]\n\n"
        return

    # ── 5. Parse intent (Agent 1) ─────────────────────────────────────────────
    intent = state.current_intent or UserIntent()
    if route in (Route.NEW_SEARCH, Route.REFINE, Route.AMBIGUOUS):
        try:
            intent = await parse_intent(msg, state.get_context_window())
            state.current_intent = intent
        except Exception as exc:
            log.error("intent_parse_failed", error=str(exc))
            intent = UserIntent()

    # ── 6. Run pipeline (Agents 2 + 3 + 4 via phase_06) ─────────────────────
    start = asyncio.get_event_loop().time()
    bubbles = await route_message(route, intent, state, swiggy_client, gemini_client)
    elapsed_ms = round((asyncio.get_event_loop().time() - start) * 1000)
    log.info("pipeline_complete", route=route.value, latency_ms=elapsed_ms)

    # ── 7. Stream bubbles ─────────────────────────────────────────────────────
    for i, bubble in enumerate(bubbles):
        if await client_request.is_disconnected():
            log.warning("client_disconnected_mid_stream")
            return
        if i > 0:
            await asyncio.sleep(0.08)
        bubble.setdefault("type", "bubble")
        yield f"data: {json.dumps(bubble)}\n\n"

    # ── 8. Stream restaurant cards ────────────────────────────────────────────
    if route in (Route.NEW_SEARCH, Route.REFINE, Route.AMBIGUOUS) and state.has_recommendations:
        yield f"data: {json.dumps({'type': 'cards', 'dishes': state.cached_results[:6]})}\n\n"

    yield "data: [DONE]\n\n"


@router.post("/api/chat")
async def chat_endpoint(request: ChatRequest, client_request: Request):
    """SSE endpoint — streams bubbles and card events to the React frontend."""
    return StreamingResponse(
        stream_response(request, client_request),
        media_type="text/event-stream",
    )
