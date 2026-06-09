"""FastAPI SSE router (Architecture §8).

Address resolution rule (architecture §2):
  - NEVER use GPS / coordinates.
  - address_id comes exclusively from get_addresses → user selection.
  - On the first message of every session: call get_addresses.
      • 1 address  → auto-select silently, continue.
      • 2+ addresses → show chips, pause until user picks.
  - Safety net: if address_id is still None before any search, re-fetch.
  - Original query saved in state.pending_search_query, replayed after pick.
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


class ChatRequest(BaseModel):
    session_id: str
    message: str


# ── Address resolution helpers ────────────────────────────────────────────────

async def _fetch_and_resolve_address(
    state: ConversationState,
    swiggy_client: SwiggyReadClient,
    pending_query: str,
):
    """
    Call get_addresses, then either:
    - Auto-select (1 address):  set state.address_id, yield confirmation bubble.
    - Show picker (2+ addresses): yield chip bubble, set awaiting_address_pick.
    - Error / 0 addresses:       yield error bubble.

    Yields raw JSON strings (caller wraps in "data: ...\n\n").
    After this generator finishes, check state.address_id to know if address
    was resolved (auto-select path) or if we need to wait for user reply (picker path).
    """
    try:
        addresses = await swiggy_client.get_addresses()
    except Exception as exc:
        log.error("get_addresses_failed", error=str(exc))
        yield json.dumps({
            "type": "bubble",
            "text": "Couldn't fetch your saved addresses right now 😕 — try again in a moment.",
            "quick_replies": ["Try again"],
        })
        return

    if not addresses:
        yield json.dumps({
            "type": "bubble",
            "text": "No saved addresses found on your Swiggy account. "
                    "Please add one in the Swiggy app first.",
            "quick_replies": [],
        })
        return

    # Cache in state so the address-pick reply can resolve a chip back to an ID
    state.addresses = addresses

    if len(addresses) == 1:
        addr = addresses[0]
        state.address_id = addr["addressId"]
        log.info("address_auto_selected", address_id=state.address_id, label=addr.get("label"))
        yield json.dumps({
            "type": "bubble",
            "text": f"Delivering to {addr.get('label', 'your address')} 📍",
            "quick_replies": [],
        })
        return  # state.address_id is now set → caller continues pipeline

    # Multiple addresses — show picker, pause pipeline until user picks
    state.awaiting_address_pick = True
    state.pending_search_query = pending_query
    chips = [a["chip"] for a in addresses]
    yield json.dumps({
        "type": "bubble",
        "text": "Where should I deliver? Pick your address 📍",
        "quick_replies": chips,
    })
    # state.address_id remains None → caller yields [DONE] and returns


def _resolve_chip_to_address(msg: str, addresses: list[dict]) -> dict | None:
    """
    Match user's chip-tap reply to one of the stored address dicts.
    Strips the 📍 prefix and does case-insensitive comparison.
    Returns the matching address dict or None.
    """
    msg_clean = msg.strip().lower()
    # strip emoji prefix variants
    for prefix in ("📍 ", "📍", "📌 ", "📌"):
        if msg_clean.startswith(prefix):
            msg_clean = msg_clean[len(prefix):]
            break
    msg_clean = msg_clean.strip()

    for addr in addresses:
        chip_clean = addr.get("chip", "").lower()
        for prefix in ("📍 ", "📍", "📌 ", "📌"):
            if chip_clean.startswith(prefix):
                chip_clean = chip_clean[len(prefix):]
                break
        chip_clean = chip_clean.strip()

        label_clean = addr.get("label", "").lower().strip()
        if msg_clean in (chip_clean, label_clean):
            return addr
    return None


# ── Main SSE generator ────────────────────────────────────────────────────────

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

    # ── 2. Address-pick reply handler ─────────────────────────────────────────
    # Must check BEFORE anything else — user is answering a "pick address" prompt.
    if state.awaiting_address_pick:
        matched = _resolve_chip_to_address(msg, state.addresses)
        if matched:
            state.address_id = matched["addressId"]
            state.awaiting_address_pick = False
            log.info("address_selected", address_id=state.address_id, label=matched.get("label"))
            # Confirm selection to user
            confirm_text = f"Got it — delivering to {matched['label']} 📍"
            yield f"data: {json.dumps({'type': 'bubble', 'text': confirm_text, 'quick_replies': []})}\n\n"
            # Resume the original query
            if state.pending_search_query:
                msg = state.pending_search_query
                state.pending_search_query = None
                state.append_message("user", msg)
                # Fall through to pipeline with the restored query
            else:
                yield "data: [DONE]\n\n"
                return
        else:
            # Didn't match — re-show picker
            chips = [a["chip"] for a in state.addresses]
            yield (
                f"data: {json.dumps({'type': 'bubble', 'text': 'Please tap one of the options 👇', 'quick_replies': chips})}\n\n"
            )
            yield "data: [DONE]\n\n"
            return

    # ── 3. Address init — run whenever address_id is missing (on session start AND
    #         as a safety net on any later message where it gets cleared).
    if not state.address_id and not state.awaiting_address_pick:
        async for payload in _fetch_and_resolve_address(state, swiggy_client, msg):
            yield f"data: {payload}\n\n"

        if not state.address_id:
            # Picker chips were sent — wait for user to pick
            yield "data: [DONE]\n\n"
            return
        # Single address auto-selected — continue pipeline

    # ── 4. Classify route ─────────────────────────────────────────────────────
    route = classify(msg, state)

    # Fast path for CART_ACTION
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
