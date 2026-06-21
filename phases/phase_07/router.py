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

from phases.phase_00.config import get_settings
from phases.phase_00.services.gemini_client import GeminiModel
from phases.phase_00.logging_setup import get_logger
from phases.phase_01.models.intent import UserIntent
from phases.phase_01.models.state import ConversationState, check_staleness
from phases.phase_02.orchestrator import classify, Route
from phases.phase_03.agents.intent_parser import parse_intent
from phases.phase_04.services.swiggy_read import SwiggyReadClient
from phases.phase_06.handlers.opener import build_opener
from phases.phase_06.orchestrator import route_message
from phases.phase_06.utils.templates import get_stale_template
from phases.phase_07.session import get_session, save_session

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


class SetRestaurantRequest(BaseModel):
    session_id: str
    restaurant_id: str
    restaurant_name: str = ""


# ── Address REST endpoints ────────────────────────────────────────────────────

@router.get("/api/addresses")
async def addresses_endpoint(session_id: str):
    """Return user's saved Swiggy delivery addresses (for popup, not chat flow)."""
    swiggy_client = SwiggyReadClient()
    try:
        addresses = await swiggy_client.get_addresses()
        return {"addresses": addresses}
    except Exception as exc:
        log.error("get_addresses_endpoint_failed", error=str(exc))
        return {"addresses": [], "error": str(exc)}


@router.post("/api/set-address")
async def set_address_endpoint(req: SetAddressRequest):
    """Store user-selected address in session (called by address popup)."""
    state = get_session(req.session_id)
    state.address_id = req.address_id
    state.touch_activity()
    save_session(state)
    log.info("address_set_via_popup", session=req.session_id, address_id=req.address_id, label=req.label)
    return {"ok": True}


@router.get("/api/opener")
async def opener_endpoint():
    """
    Context-aware first-message for empty chats.
    Uses long-term memory + clock — zero LLM, sub-10ms.
    """
    return build_opener()


@router.post("/api/set-restaurant")
async def set_restaurant_endpoint(req: SetRestaurantRequest):
    """
    Track which restaurant the user just added to cart.
    Called by the frontend after a successful addToCart so that
    'More from here' (IN_RESTAURANT route) knows which menu to fetch.
    Also writes the order to long-term memory so future sessions can
    learn the user's habits.
    """
    state = get_session(req.session_id)
    state.current_restaurant_id = req.restaurant_id
    state.cart_restaurant_id = req.restaurant_id
    state.cart_has_items = True
    state.touch_activity()
    save_session(state)
    # Memory: record this restaurant as a recent pick. We don't have item
    # detail at this endpoint yet (the frontend hits set-restaurant per Add),
    # so we look up the dish from cached_results if we can match the id.
    try:
        from phases.phase_00.services import memory as user_memory
        picked = next(
            (d for d in state.cached_results
             if str(d.get("restaurantId") or "") == req.restaurant_id),
            None,
        )
        items = [picked] if picked else []
        user_memory.record_order(
            restaurant_id=req.restaurant_id,
            restaurant_name=req.restaurant_name or (picked or {}).get("restaurant"),
            items=items,
            total=float((picked or {}).get("price", 0)),
        )
    except Exception as exc:
        log.warning("memory_record_failed", error=str(exc))
    log.info("restaurant_set", session=req.session_id, restaurant_id=req.restaurant_id)
    return {"ok": True}


# ── Chat SSE endpoint ─────────────────────────────────────────────────────────

_EPHEMERAL_FIELDS = {"timing", "timing_type"}


def _merge_intents(prior: UserIntent, refined: UserIntent) -> UserIntent:
    """
    REFINE merge: prefer the refined intent's non-None fields, fall back to
    the prior intent for anything the user didn't override this turn.

    "Pure veg only" should set veg_nonveg="veg" but keep search_query="momos"
    and budget_max=250 from the original turn.

    Ephemeral fields (timing, timing_type) are NOT carried forward — they
    belong to a specific request, and re-using them on a later refine causes
    a "too tight" loop when the original time window has already passed.
    """
    prior_d = prior.model_dump()
    refined_d = refined.model_dump()
    merged = {}
    for k in prior_d.keys():
        if k in _EPHEMERAL_FIELDS:
            merged[k] = refined_d.get(k)  # don't carry forward
        else:
            merged[k] = refined_d[k] if refined_d.get(k) is not None else prior_d.get(k)
    try:
        return UserIntent.model_validate(merged)
    except Exception:
        return refined


def _resolve_clarify_intent(msg: str, state: ConversationState) -> UserIntent:
    """
    When the user answers a clarification question, patch the saved intent
    with their reply and return the updated UserIntent.
    """
    # state.current_intent may be a UserIntent OR a dict (after disk reload it
    # comes back as a dict from model_dump_json). Coerce either to UserIntent
    # so the search_query and other fields actually carry forward.
    raw = state.current_intent
    if isinstance(raw, UserIntent):
        intent = raw
    elif isinstance(raw, dict):
        try:
            intent = UserIntent.model_validate(raw)
        except Exception:
            intent = UserIntent()
    else:
        intent = UserIntent()

    if state.clarify_field == "veg_nonveg":
        lower = msg.lower()
        if "non" in lower or "🍗" in lower:
            intent.veg_nonveg = "nonveg"
        elif "both" in lower:
            intent.veg_nonveg = "both"
        else:
            intent.veg_nonveg = "veg"

    elif state.clarify_field == "budget_max":
        import re
        nums = re.findall(r"\d+", msg)
        if nums:
            intent.budget_max = int(nums[-1])

    return intent


async def stream_response(request: ChatRequest, client_request: Request):
    """Async generator that yields SSE events."""
    state = get_session(request.session_id)
    settings = get_settings()

    gemini_client = GeminiModel(api_key=settings.gemini_api_key)
    swiggy_client = SwiggyReadClient()

    # ── 1. Staleness check ────────────────────────────────────────────────────
    if check_staleness(state):
        for bubble in get_stale_template():
            bubble.setdefault("type", "bubble")
            yield f"data: {json.dumps(bubble)}\n\n"
        yield "data: [DONE]\n\n"
        return

    msg = request.message.strip()
    state.append_message("user", msg)

    # ── 1b. Intercept schedule-control chips before any intent parsing ───────
    # These come from propose_schedule_after_search / handle_schedule quick
    # replies and need explicit handling — otherwise Gemini parses them as
    # empty intents and the user gets a confusing "what are you in the mood
    # for today?" loop with no way out.
    msg_lower = msg.lower()
    if msg_lower in {"no, order now", "order now", "order now instead"}:
        # User declined the schedule — wipe any proposal and let them keep
        # chatting normally. Don't run search; cart/composer takes over.
        state.scheduled_order = None
        bubble = {"type": "bubble", "text": "Cool — no schedule. Add what you want and order whenever you’re ready! 🛒", "quick_replies": []}
        yield f"data: {json.dumps(bubble)}\n\n"
        save_session(state)
        yield "data: [DONE]\n\n"
        return
    if msg_lower in {"pick a later time", "change time", "different time"}:
        state.scheduled_order = None
        bubble = {"type": "bubble", "text": "Sure — what time should I aim for? ⏰", "quick_replies": ["1:00 PM", "8:00 PM", "9:00 PM"]}
        yield f"data: {json.dumps(bubble)}\n\n"
        save_session(state)
        yield "data: [DONE]\n\n"
        return

    # ── 2. Classify route ─────────────────────────────────────────────────────
    route = classify(msg, state)

    # ── 3. Address guard (non-blocking) ──────────────────────────────────────
    search_routes = (Route.NEW_SEARCH, Route.AMBIGUOUS, Route.REFINE, Route.IN_RESTAURANT, Route.SCHEDULE)
    if route in search_routes and not state.address_id:
        yield f"data: {json.dumps({'type': 'bubble', 'text': 'Tap 📍 above to set your delivery address first — then I can find restaurants near you!', 'quick_replies': []})}\n\n"
        yield "data: [DONE]\n\n"
        return

    # ── 3b. Early "thinking" bubble for slow paths ───────────────────────────
    # Dish search costs ~6s end-to-end (intent → search → 6 menus → persona).
    # Emitting an immediate placeholder makes the UI feel responsive —
    # `loading: true` lets the frontend show a typing-style spinner rather
    # than a static bubble, then the real reply overwrites it once ready.
    slow_routes = (Route.NEW_SEARCH, Route.AMBIGUOUS, Route.REFINE, Route.IN_RESTAURANT)
    if route in slow_routes:
        msg_lc = msg.lower()
        if any(w in msg_lc for w in ("momo", "biryani", "chicken", "pizza", "burger", "dosa", "pasta", "thali")):
            thinking = "scanning menus near you... 🔎"
        else:
            thinking = "looking around for that... 🔎"
        yield f"data: {json.dumps({'type': 'thinking', 'text': thinking})}\n\n"

    # ── 4. Fast path for CART_ACTION ─────────────────────────────────────────
    if route == Route.CART_ACTION:
        state.cart_has_items = True
        bubbles = await route_message(route, UserIntent(), state, swiggy_client, gemini_client)
        for bubble in bubbles:
            bubble.setdefault("type", "bubble")
            yield f"data: {json.dumps(bubble)}\n\n"
        yield "data: [DONE]\n\n"
        return

    # ── 5. Parse intent (Agent 1) ─────────────────────────────────────────────
    if route == Route.CLARIFY_REPLY:
        # User answered a clarification question — patch saved intent, don't re-parse
        intent = _resolve_clarify_intent(msg, state)
        state.current_intent = intent
        route = Route.NEW_SEARCH  # now do the actual search
    elif route == Route.SCHEDULE and state.scheduled_order and state.scheduled_order.get("status") == "proposed":
        # Confirming a pending schedule proposal — no Gemini needed
        raw_ci = state.current_intent
        if isinstance(raw_ci, UserIntent):
            intent = raw_ci
        elif isinstance(raw_ci, dict):
            try:
                intent = UserIntent.model_validate(raw_ci)
            except Exception:
                intent = UserIntent()
        else:
            intent = UserIntent()
    elif route in (Route.NEW_SEARCH, Route.REFINE, Route.AMBIGUOUS, Route.SCHEDULE):
        # Hold onto the prior intent so REFINE turns ("pure veg only",
        # "fastest delivery") don't lose the original search_query/budget.
        prior_intent = state.current_intent
        if isinstance(prior_intent, dict):
            try:
                prior_intent = UserIntent.model_validate(prior_intent)
            except Exception:
                prior_intent = None
        if not isinstance(prior_intent, UserIntent):
            prior_intent = None

        try:
            parsed = await parse_intent(msg, state.get_context_window())
            # On REFINE, carry forward any field the user didn't override
            # this turn. Gemini sometimes returns sparse intents for chips
            # like "Pure veg only" — without this merge the validator would
            # ask "what are you in the mood for today?" and lose context.
            if route == Route.REFINE and prior_intent is not None:
                intent = _merge_intents(prior_intent, parsed)
            else:
                intent = parsed
            # Last-resort signal recovery: if Gemini gave us a completely
            # empty intent but the user clearly typed a request, use the
            # raw message as search_query. Stops the "no signal → ask again"
            # loop dead in its tracks.
            if not any([intent.search_query, intent.mood, intent.diet, intent.cuisine]) and len(msg) > 2:
                intent.search_query = msg
            state.current_intent = intent
        except Exception as exc:
            log.error("intent_parse_failed", error=str(exc))
            # Fallback: keep the prior intent only if it has a real signal,
            # otherwise use the raw message as search_query so the validator
            # doesn't block.
            if prior_intent and any([prior_intent.search_query, prior_intent.mood, prior_intent.diet, prior_intent.cuisine]):
                intent = prior_intent
            else:
                intent = UserIntent(search_query=msg)
    else:
        intent = state.current_intent or UserIntent()

    # current_intent may have been deserialised from disk as a dict —
    # downstream code uses attribute access (intent.veg_nonveg, etc.)
    # so coerce defensively before handing to the orchestrator.
    if isinstance(intent, dict):
        try:
            intent = UserIntent.model_validate(intent)
        except Exception:
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
    send_cards_routes = (Route.NEW_SEARCH, Route.REFINE, Route.AMBIGUOUS, Route.IN_RESTAURANT)
    # Don't leak stale cards on a clarification turn — the bubble is asking the
    # user a question; results should appear only after they answer.
    is_clarification_turn = state.awaiting_clarification
    if route in send_cards_routes and state.has_recommendations and not is_clarification_turn:
        yield f"data: {json.dumps({'type': 'cards', 'dishes': state.cached_results[:6]})}\n\n"

    save_session(state)
    yield "data: [DONE]\n\n"


@router.post("/api/chat")
async def chat_endpoint(request: ChatRequest, client_request: Request):
    """SSE endpoint — streams bubbles and card events to the React frontend."""
    return StreamingResponse(
        stream_response(request, client_request),
        media_type="text/event-stream",
    )
