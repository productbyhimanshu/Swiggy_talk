Swiggy Talk — System Architecture & Build Instructions
For: Cursor Agent / Claude Code / Antigravity Version: 4.0 (final) Stack: React + FastAPI + Gemini 2.0 Flash + Swiggy Food API

1. Project overview
Project: Swiggy Talk Goal: Conversational AI food ordering assistant — chat-first, not browse-first. Core philosophy: "Talk your way to what you want to eat. No browsing. No overthinking."
A chat interface where users describe what they want in natural language. An AI understands intent, searches real Swiggy restaurants, scores and ranks results, and presents 6 high-accuracy recommendations. Users refine through conversation, build a cart, and place real orders.
What this is NOT: A wrapper around Swiggy's app. Not a chatbot with canned responses. Not mock data. Everything hits real Swiggy APIs.

2. Data source — single source of truth
ALL data comes from Swiggy Food API via HTTP endpoints.
Base URL: https://mcp.swiggy.com/food
Auth: OAuth 2.1 + PKCE (personal account)
Protocol: JSON-RPC tool calls (treat as standard HTTP API, NOT MCP protocol wrappers)
Reference: https://mcp.swiggy.com/builders/docs/
GitHub: https://github.com/Swiggy/swiggy-mcp-server-manifest
No mock data. No staging endpoints. No MCP protocol wrappers.
Available tools (Swiggy Food server)
Tool
Purpose
Side effects
get_addresses
Get user's saved delivery addresses
None (read)
search_restaurants
Find restaurants by query + addressId
None (read)
get_restaurant_menu
Full menu for a restaurant
None (read)
search_menu
Search items within/across restaurants
None (read)
update_food_cart
Add/remove items in cart
Writes to cart
get_food_cart
View cart + bill breakdown
None (read)
flush_food_cart
Clear cart when switching restaurant
Clears cart
fetch_food_coupons
List available coupons
None (read)
apply_food_coupon
Apply coupon to cart
Modifies cart
place_food_order
Place real order (COD only)
REAL ORDER — irreversible
track_food_order
Track order status
None (read)
get_food_orders
Order history
None (read)

API flow (canonical 7-tool journey)
get_addresses
     │
     ▼
search_restaurants ──► get_restaurant_menu
                            │
                            ▼
                       update_food_cart ◄── fetch_food_coupons
                            │                       │
                            ▼                       │
                       get_food_cart ◄── apply_food_coupon
                            │
                            ▼
                       place_food_order
                            │
                            ▼
                       track_food_order

Critical constraints from Swiggy
Cart is single-restaurant. Changing restaurant flushes the cart.
₹1000 hard cap on Builders Club orders.
COD only in v1. Filter coupons that require online payment.
place_food_order is NOT idempotent. If it fails with 5xx, call get_food_orders to check if order actually placed before retrying.
availabilityStatus must be "OPEN" — never recommend closed restaurants.
addressId is required for search_restaurants — always resolve address first.

3. Tech stack
Layer
Technology
Frontend
React (Vite)
Chat UI
Custom components (streaming multi-bubble)
Backend
FastAPI (Python 3.11+, async)
AI
Gemini 2.0 Flash (google-generativeai Python SDK)
Validation
Pydantic v2 models (replaces hand-written Agent 2)
Swiggy API
httpx async client + OAuth 2.1 + PKCE
State
In-memory session store (per-user dict, Redis if scaling)
Scheduler
APScheduler (for timing engine cron)
Streaming
Server-Sent Events (SSE) via FastAPI StreamingResponse
Testing
pytest + pytest-asyncio for agent evals
Logging
structlog (JSON, every pipeline run logged)

Why FastAPI over Express
Gemini Python SDK is first-class with native structured output (response_schema)
Pydantic models = free validation for Agent 2 (intent schema, cart schema)
Native async/await for parallel Swiggy API calls
SSE streaming is built-in (StreamingResponse)
Scoring algorithm is cleaner in Python
Type hints catch bugs at dev time
Environment variables
GEMINI_API_KEY=xxxxx
SWIGGY_OAUTH_CLIENT_ID=xxxxx
SWIGGY_OAUTH_CLIENT_SECRET=xxxxx
SWIGGY_OAUTH_REDIRECT_URI=http://localhost:3000/callback
SWIGGY_FOOD_URL=https://mcp.swiggy.com/food
FRONTEND_URL=http://localhost:5173
ORDER_ENABLED=false
LOG_LEVEL=debug
SESSION_TIMEOUT_MINUTES=30


4. System architecture — 5 layers
┌──────────────────────────────────────────────────────────┐
│  LAYER 1: React Chat UI                                  │
│  Streaming multi-bubble | Dish cards (6) | Sticky cart   │
│  Quick reply chips | Optimistic cart updates             │
│  Order button (user-only) | Schedule picker              │
└──────────────────────┬───────────────────────────────────┘
                       │ SSE stream (Server-Sent Events)
                       ▼
┌──────────────────────────────────────────────────────────┐
│  LAYER 2: ORCHESTRATOR (top-level router)                │
│  FastAPI endpoint: POST /api/chat                        │
│  Hybrid classifier: regex (free) + Gemini (ambiguous)    │
│  Owns: conversation state, session cache, routing        │
│  Routes to only the agents needed per message            │
└──────┬──────────┬──────────┬──────────┬─────────────────┘
       │          │          │          │
  ┌────▼───┐ ┌───▼───┐ ┌───▼───┐ ┌───▼────┐
  │Agent 1 │ │Agent 2│ │Agent 3│ │Agent 4 │
  │Intent  │ │Validate│ │Score │ │Persona │
  │(Gemini)│ │(Pydantic)│(Math+│ │(Gemini)│
  │        │ │        │ │Gemini)│ │        │
  └────────┘ └────────┘ └───────┘ └────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────┐
│  LAYER 3: Safety + Testing                               │
│  Order blocked until frontend click | Eval loop          │
│  Hallucination catch | Cart cap ₹1000 | Staleness check │
└──────────────────────┬───────────────────────────────────┘
                       │ httpx async + OAuth 2.1
                       ▼
┌──────────────────────────────────────────────────────────┐
│  LAYER 4: Swiggy Food API                                │
│  mcp.swiggy.com/food (real data, single source)          │
└──────────────────────────────────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────────┐
│  LAYER 5: Observability                                  │
│  structlog: route type, agents called, latency per call  │
│  Gemini token usage, Swiggy API latency, final response  │
└──────────────────────────────────────────────────────────┘


5. Orchestrator — the brain on top
Why it exists
Without the orchestrator, every message walks through all 4 agents sequentially. "Add to cart" takes 3 Gemini calls (~1100ms) when it needs zero. The orchestrator classifies the message type first, then dispatches to ONLY the agents that route needs.
How it classifies (hybrid: regex + Gemini)
Use regex/keyword matching for obvious cases (free, instant). Only call Gemini for ambiguous messages.
# orchestrator.py

import re
from enum import Enum

class Route(str, Enum):
    NEW_SEARCH = "new_search"
    CLARIFY_REPLY = "clarify_reply"
    REFINE = "refine"
    CART_ACTION = "cart_action"
    IN_RESTAURANT = "in_restaurant"
    ORDER = "order"
    SCHEDULE = "schedule"
    GREETING = "greeting"
    CANCEL = "cancel"
    AMBIGUOUS = "ambiguous"  # needs Gemini classify

PATTERNS = {
    Route.GREETING: r"^(hi|hey|hello|sup|yo|good morning|thanks|thank you|bye|ok|cool|nice)\s*[!.?]*$",
    Route.CANCEL: r"\b(cancel|stop|nevermind|forget it|scratch that|nvm|start over|clear cart)\b",
    Route.ORDER: r"\b(order it|place order|checkout|confirm order|buy it|proceed|place it)\b",
    Route.CART_ACTION: r"\b(add|remove|delete|drop|take out|minus|plus|increase|decrease|qty|quantity)\b",
    Route.REFINE: r"\b(faster|cheaper|healthier|more protein|less spicy|different|instead|re-?suggest|better options|something else|show me)\b",
    Route.IN_RESTAURANT: r"\b(same restaurant|same place|also add from|search .+ in|from same|from there|what else)\b",
    Route.SCHEDULE: r"\b(at \d{1,2}|by \d{1,2}|before \d{1,2}|lunch at|dinner at|breakfast at|schedule|deliver by)\b",
}

def classify(message: str, state: "ConversationState") -> Route:
    msg = message.strip()

    # Priority 1: If we're waiting for clarification reply
    if state.awaiting_clarification:
        return Route.CLARIFY_REPLY

    # Priority 2: Regex matches (free, <1ms)
    for route, pattern in PATTERNS.items():
        if re.search(pattern, msg, re.IGNORECASE):
            # Context guards
            if route == Route.ORDER and not state.cart_has_items:
                continue  # can't order with empty cart
            if route == Route.REFINE and not state.has_recommendations:
                continue  # can't refine without recommendations
            if route == Route.IN_RESTAURANT and not state.current_restaurant_id:
                continue  # no restaurant context
            return route

    # Priority 3: Short ambiguous messages → Gemini classify
    if len(msg) > 5:
        return Route.AMBIGUOUS  # will trigger fast Gemini classify call

    return Route.NEW_SEARCH

Gemini classify call (only for ambiguous messages)
Separate from Agent 1. Returns only a route label. ~50-100ms.
async def gemini_classify(message: str, last_2_messages: list[str]) -> Route:
    response = await gemini.generate_content(
        contents=f"Classify: '{message}'\nContext: {last_2_messages}",
        generation_config={
            "response_mime_type": "application/json",
            "response_schema": {"type": "object", "properties": {"route": {"type": "string", "enum": [r.value for r in Route if r != Route.AMBIGUOUS]}}},
            "max_output_tokens": 10,
            "temperature": 0,
        },
    )
    return Route(response.parsed["route"])

Route table — what each route calls
Route
Agents called
Gemini calls
Swiggy API calls
Est. time
new_search
1 → 2 → 3 → 4
3 (intent + rerank + persona)
search_restaurants + get_restaurant_menu
~1000-1200ms
clarify_reply
2 → 3 → 4
2 (rerank + persona)
search_restaurants
~700-900ms
refine
3 → 4
1-2 (rerank + persona)
None (re-score cached data)
~500-700ms
cart_action
None
0 (template ack)
update_food_cart
~100-200ms
in_restaurant
3 → 4
1-2 (rerank + persona)
search_menu
~500-700ms
order
None
0
None (route to frontend)
~50ms
schedule
Timing engine
0-1 (persona for plan)
None
~200-400ms
greeting
4
1 (persona)
None
~200-300ms
cancel
None
0 (template ack)
flush_food_cart
~100-150ms

In a typical conversation, ~60% of messages are cart actions, refinements, or order/cancel — all sub-300ms.
Conversation state (what orchestrator tracks)
from pydantic import BaseModel
from datetime import datetime

class ConversationState(BaseModel):
    # Clarification
    awaiting_clarification: bool = False
    clarify_field: str | None = None

    # Intent
    current_intent: dict | None = None

    # Recommendations
    has_recommendations: bool = False
    cached_results: list[dict] = []        # last Swiggy search results (for re-scoring)
    current_restaurant_id: str | None = None

    # Cart
    cart_has_items: bool = False
    cart_restaurant_id: str | None = None

    # Scheduler
    scheduled_order: dict | None = None

    # Session
    message_history: list[dict] = []       # sliding window: last 6 messages
    last_activity: datetime = datetime.now()
    address_id: str | None = None

    # Token budget: only send last 6 messages to Gemini
    def get_context_window(self) -> list[dict]:
        return self.message_history[-6:]

Session staleness detection
If user leaves and comes back after 30+ minutes, restaurants may have closed, ETAs changed.
from datetime import datetime, timedelta

def check_staleness(state: ConversationState) -> bool:
    if datetime.now() - state.last_activity > timedelta(minutes=30):
        # Invalidate cached results, force fresh search
        state.cached_results = []
        state.has_recommendations = False
        state.current_restaurant_id = None
        return True  # notify user: "been a while — let me refresh what's available"
    return False


6. Agent pipeline
Agent 1 — Intent parser
Type: Gemini API call Job: Extract structured JSON from natural language. No free-text output.
from pydantic import BaseModel, Field

class UserIntent(BaseModel):
    mood: str | None = Field(None, description="comfort, light, heavy, celebratory")
    diet: str | None = Field(None, description="high_protein, low_carb, healthy, comfort")
    budget_max: int | None = Field(None, ge=1, le=5000)
    timing: str | None = Field(None, description="HH:MM format or null")
    timing_type: str | None = Field(None, description="deliver_by, order_now, null")
    cuisine: str | None = Field(None, description="north_indian, chinese, italian, etc")
    veg_nonveg: str | None = Field(None, description="veg, nonveg, both, NEEDS_CLARIFICATION")
    speed: str | None = Field(None, description="fast, normal, null")
    search_query: str | None = Field(None, description="keyword for Swiggy search")

# Gemini call
async def parse_intent(message: str, context: list[dict]) -> UserIntent:
    response = await gemini.generate_content(
        contents=f"User: {message}\nContext: {context}",
        generation_config={
            "response_mime_type": "application/json",
            "response_schema": UserIntent.model_json_schema(),
            "temperature": 0.1,
        },
    )
    return UserIntent.model_validate(response.parsed)

Anti-hallucination: Pydantic schema forces valid types and ranges. If Gemini invents budget_max: -500, Pydantic rejects it before it reaches Agent 3.
Agent 2 — Validator
Type: Pydantic validation + business logic. NOT an LLM call. Zero hallucination.
class ValidationResult(BaseModel):
    valid: bool
    clarify_field: str | None = None
    clarify_question: str | None = None
    quick_replies: list[str] | None = None

def validate_intent(intent: UserIntent) -> ValidationResult:
    # Budget cap
    if intent.budget_max and intent.budget_max > 1000:
        return ValidationResult(
            valid=False,
            clarify_field="budget_max",
            clarify_question="swiggy caps at ₹1000 — keep it under that?",
            quick_replies=["Under ₹500", "Under ₹800", "Max ₹1000"]
        )

    # Needs clarification
    if intent.veg_nonveg == "NEEDS_CLARIFICATION":
        return ValidationResult(
            valid=True,
            clarify_field="veg_nonveg",
            clarify_question="veg or non-veg?",
            quick_replies=["🥦 Veg", "🍗 Non-veg", "Both work"]
        )

    # Enough signal to search?
    signals = [intent.mood, intent.diet, intent.cuisine, intent.search_query]
    if not any(signals):
        return ValidationResult(
            valid=False,
            clarify_question="what are you in the mood for today?",
        )

    return ValidationResult(valid=True)

Agent 3 — Recommendation scorer
Type: Deterministic scoring + 1 Gemini call for soft re-rank.
Step 1 — Hard filters
Every filter maps to a real Swiggy API field. Fail any = killed.
Gate
Swiggy field
Kill if
Source
Open
availabilityStatus
!= "OPEN"
search_restaurants
Deliverable
addressId param
API handles this (only returns deliverable)
get_addresses → search_restaurants
Rating
rating
< 4.0
search_restaurants
ETA
deliveryTime
max_eta > user_time_window
search_restaurants ("25-30 mins" → parse max: 30)
Diet
isVeg per item / pureVeg badge
user said veg AND item.isVeg == false
get_restaurant_menu
Budget
item.price
> user_budget OR cart_total > 1000
get_restaurant_menu

def parse_eta(delivery_time_str: str) -> int:
    """'25-30 mins' → 30 (always worst-case max)"""
    nums = [int(n) for n in re.findall(r"\d+", delivery_time_str)]
    return max(nums) if nums else 45  # default 45 if unparseable

Filter execution order: Open → Deliverable (free) → Rating → ETA → Diet → Budget. Cheapest checks first.
Step 2 — Weighted scoring
score = (W1 × rating_score) + (W2 × eta_score) + (W3 × intent_match)
      + (W4 × price_value) + (W5 × distance_score) + (W6 × time_relevance)

Data point
Calculation
Default W
rating_score
(rating - 4.0) / 1.0 × 100
0.20
eta_score
max(0, (60 - eta_min) / 60 × 100)
0.20
intent_match
Gemini re-rank score 0-100
0.25
price_value
(budget - price) / budget × 100
0.15
distance_score
max(0, (10 - km) / 10 × 100)
0.10
time_relevance
dish appropriate for current time?
0.10

Dynamic weight shifting
def get_weights(intent: UserIntent) -> dict:
    base = {"rating": 0.20, "eta": 0.20, "intent": 0.25, "price": 0.15, "distance": 0.10, "time": 0.10}

    if intent.speed == "fast":
        return {**base, "eta": 0.35, "rating": 0.15, "intent": 0.15}
    if intent.diet in ("high_protein", "healthy", "low_carb"):
        return {**base, "intent": 0.35, "price": 0.10, "eta": 0.15}
    if intent.budget_max and intent.budget_max <= 200:
        return {**base, "price": 0.30, "rating": 0.15, "intent": 0.20}
    if intent.mood in ("comfort", "heavy", "filling"):
        return {**base, "intent": 0.30, "eta": 0.25}
    if intent.speed == "nearby":
        return {**base, "distance": 0.25, "eta": 0.25, "intent": 0.15}

    return base

Weight shifting is a code lookup table, not an LLM decision.
Step 3 — Gemini soft re-rank (top 10 only)
async def gemini_rerank(intent: UserIntent, top_10: list[dict]) -> list[int]:
    dishes = [{"name": d["name"], "desc": d.get("description", ""), "category": d.get("category", "")} for d in top_10]
    response = await gemini.generate_content(
        contents=f"User wants: {intent.model_dump_json()}.\nRate each dish 0-100 on intent match.\nReturn ONLY a JSON array of numbers.",
        generation_config={
            "response_mime_type": "application/json",
            "temperature": 0,
        },
    )
    scores = response.parsed
    # Guard: if invalid, return equal scores
    if not isinstance(scores, list) or len(scores) != len(top_10):
        return [50] * len(top_10)
    return scores

Final: combine deterministic score + Gemini intent_match → sort → return top 6.
Agent 4 — Persona formatter
Type: Gemini API call Job: Takes scored results + conversation context → wraps in foodie-friend tone. CANNOT modify data.
System prompt:
You are Swiggy Talk's personality layer. You receive:
1. An array of scored dish recommendations with LOCKED data (name, restaurant, price, ETA, rating)
2. The user's conversation history (last 6 messages)
3. The current intent

Rules:
- Casual, warm, foodie-friend tone. Like texting a friend who knows food.
- Short messages. Max 2 lines per message. Split into multiple if needed.
- Emojis: 1-2 per message, as punctuation not decoration.
- After showing recommendations: ALWAYS ask "need anything else to narrow down?" + [Re-suggest]
- Before ordering: ALWAYS show items + total + ETA and ask for confirmation.

HARD RULES:
- NEVER change prices, ETAs, ratings, or restaurant names from input data.
- NEVER invent dishes or restaurants not in input data.
- NEVER place an order or suggest auto-ordering.
- NEVER send walls of text.
- Return response as a JSON array of message bubbles: [{"text": "...", "quick_replies": [...]}]

Returning multiple bubbles as a JSON array is what enables the multi-bubble streaming UX (see Section 8).

7. Parallelization
Route A (new_search) — parallel Swiggy call + weight config
After Agent 2 validates intent, two things can happen simultaneously:
import asyncio

async def route_new_search(intent: UserIntent, state: ConversationState):
    # Agent 2 validates
    validation = validate_intent(intent)
    if not validation.valid:
        return clarification_response(validation)

    # Parallel: Swiggy search + weight calculation
    swiggy_task = asyncio.create_task(
        swiggy.search_restaurants(intent.search_query, state.address_id)
    )
    weights = get_weights(intent)  # instant, code-only

    restaurants = await swiggy_task

    # Cache results in session (for re-scoring on refine)
    state.cached_results = restaurants
    state.has_recommendations = True

    # Hard filters → score → Gemini rerank → top 6
    survivors = apply_filters(restaurants, intent)
    scored = score_dishes(survivors, weights)
    top_10 = scored[:10]
    intent_scores = await gemini_rerank(intent, top_10)
    top_6 = final_rank(top_10, intent_scores, weights)[:6]

    # Agent 4: format
    bubbles = await persona_format(top_6, intent, state.get_context_window())
    return bubbles

Saves ~200-400ms because Swiggy API latency runs in parallel with weight calculation.
Session cache for re-scoring
"Re-suggest" and "make it healthier" do NOT call search_restaurants again. They re-score the cached results with new weights.
async def route_refine(refinement: str, state: ConversationState):
    # Update weights based on refinement
    updated_intent = update_intent_from_refinement(state.current_intent, refinement)
    weights = get_weights(updated_intent)

    # Re-score CACHED data — zero Swiggy API calls
    survivors = apply_filters(state.cached_results, updated_intent)
    scored = score_dishes(survivors, weights)
    top_10 = scored[:10]
    intent_scores = await gemini_rerank(updated_intent, top_10)
    top_6 = final_rank(top_10, intent_scores, weights)[:6]

    bubbles = await persona_format(top_6, updated_intent, state.get_context_window())
    return bubbles


8. Streaming + multi-bubble responses
The problem
User sends a message → waits 1-2 seconds staring at nothing → full response dumps. Feels slow and robotic.
The fix: SSE streaming with multi-bubble
Agent 4 returns responses as a JSON array of message bubbles. The backend streams each bubble as a separate SSE event with a small delay between them.
# FastAPI endpoint
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import json
import asyncio

app = FastAPI()

@app.post("/api/chat")
async def chat(request: ChatRequest):
    return StreamingResponse(
        stream_response(request),
        media_type="text/event-stream"
    )

async def stream_response(request: ChatRequest):
    state = get_session(request.session_id)

    # Check staleness
    if check_staleness(state):
        yield f"data: {json.dumps({'type': 'bubble', 'text': 'been a while! let me refresh what\\'s available 🔄'})}\n\n"

    # Classify and route
    route = classify(request.message, state)

    if route == Route.CART_ACTION:
        # Fast path: template ack, no Gemini
        result = await handle_cart_action(request.message, state)
        yield f"data: {json.dumps({'type': 'bubble', 'text': result})}\n\n"
        yield f"data: {json.dumps({'type': 'cart_update', 'cart': state.cart_data})}\n\n"
        return

    # Full/partial pipeline
    bubbles = await run_pipeline(route, request.message, state)

    # Stream each bubble with micro-delay
    for i, bubble in enumerate(bubbles):
        if i > 0:
            await asyncio.sleep(0.08)  # 80ms between bubbles — feels like typing
        yield f"data: {json.dumps(bubble)}\n\n"

    # If recommendations, stream dish cards after bubbles
    if "cards" in bubbles[-1]:
        yield f"data: {json.dumps({'type': 'cards', 'dishes': bubbles[-1]['cards']})}\n\n"

    yield "data: [DONE]\n\n"

Frontend SSE consumption
// useChat.js (React hook)
const eventSource = new EventSource(`/api/chat?session=${sessionId}`);

eventSource.onmessage = (event) => {
  if (event.data === "[DONE]") {
    eventSource.close();
    return;
  }

  const data = JSON.parse(event.data);

  if (data.type === "bubble") {
    // Add message bubble with typing animation
    addMessage({ text: data.text, quick_replies: data.quick_replies, sender: "ai" });
  }

  if (data.type === "cards") {
    // Render 6 dish cards
    setRecommendations(data.dishes);
  }

  if (data.type === "cart_update") {
    // Update cart sidebar
    setCart(data.cart);
  }
};

This means the first bubble appears in ~100ms. Subsequent bubbles arrive 80ms apart. The user sees a response building in real-time — not a dump.

9. Optimistic cart UI
When user says "add to cart," don't wait for Swiggy API confirmation. Show it immediately, call the API in the background.
// CartSidebar.jsx
function handleAddToCart(item) {
  // Immediately show in cart (optimistic)
  setCartItems(prev => [...prev, { ...item, status: "pending" }]);

  // API call in background
  fetch("/api/cart/add", { method: "POST", body: JSON.stringify(item) })
    .then(res => res.json())
    .then(data => {
      // Confirm: update status
      setCartItems(prev => prev.map(i =>
        i.id === item.id ? { ...i, status: "confirmed" } : i
      ));
    })
    .catch(() => {
      // Rollback: remove item, show error
      setCartItems(prev => prev.filter(i => i.id !== item.id));
      addMessage({ text: "oops, that didn't stick — try adding again", sender: "ai" });
    });
}

User never waits for API. Cart feels instant.

10. Template responses (zero Gemini for trivial acks)
For cart actions, cancellations, and order routing, skip Agent 4 entirely. Use templates.
TEMPLATES = {
    "cart_added": lambda item, restaurant: f"added {item} from {restaurant} ✓",
    "cart_removed": lambda item: f"dropped {item} from your cart",
    "cart_cleared": lambda: "cart cleared, starting fresh 🔄",
    "schedule_cancelled": lambda: "schedule cancelled, no order will be placed",
    "order_routing": lambda: "let me pull up your order summary...",
    "stale_session": lambda: "been a while! let me refresh what's available 🔄",
    "swiggy_down": lambda: "swiggy's taking a nap — try again in a sec?",
}

Routes D (cart), F (order), I (cancel) → zero Gemini calls in most cases.

11. Quick reply lifecycle
After user taps a quick reply chip:
Chip disappears from that message (like WhatsApp)
Selected value appears as a new user message bubble
Pipeline processes it via the orchestrator
Stale chips from older messages are disabled (grayed out, not tappable)
// QuickReplies.jsx
function QuickReply({ options, messageId, onSelect }) {
  const [selected, setSelected] = useState(null);
  const isStale = useIsStaleMessage(messageId);  // true if newer messages exist

  if (selected || isStale) return null;  // hide after selection or if stale

  return (
    <div className="quick-replies">
      {options.map(opt => (
        <button
          key={opt}
          onClick={() => {
            setSelected(opt);
            onSelect(opt);  // sends as user message via orchestrator
          }}
        >
          {opt}
        </button>
      ))}
    </div>
  );
}


12. Timing scheduler engine
User confirms the schedule during the chat. System handles ordering at the right time.
Flow
11:30 AM — User: "my lunch is at 1 PM"
    │
    ▼
11:30 AM — Agent 1: { timing: "13:00", timing_type: "deliver_by" }
    │
    ▼
11:30 AM — Calculate:
    order_time = delivery_target - max_eta - buffer
    order_time = 13:00 - 30min - 5min = 12:25 PM
    │
    ▼
11:30 AM — AI confirms NOW:
    "got it, 1 pm lunch 🕐 I'll order Butter Chicken + Naan from
     Punjab Grill (₹347) at 12:25 so it arrives by 1 PM. lock this in?"
    [Confirm schedule] [Change items] [Order now instead]
    │
    ▼
11:30 AM — User taps "confirm schedule"
    System saves schedule. APScheduler sets job for 12:25 PM.
    │
    ▼
12:20 PM — Pre-order check (5 min before):
    - Restaurant still OPEN?
    - ETA still within target?
    - Cart still valid?
    - If ANYTHING fails → cancel, notify user
    │
    ▼
12:25 PM — Order fires automatically
    place_food_order (COD) → notify user

from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()

def calculate_order_time(delivery_target: datetime, eta_str: str) -> dict:
    max_eta = parse_eta(eta_str)
    buffer = 5  # minutes
    order_time = delivery_target - timedelta(minutes=max_eta + buffer)
    pre_check_time = order_time - timedelta(minutes=5)
    now = datetime.now()

    if order_time <= now:
        return {"order_now": True, "reason": "delivery time already tight"}
    if (order_time - now).total_seconds() > 4 * 3600:
        return {"order_now": False, "warn": "that's far out — ETA might change, I'll re-check closer"}

    return {
        "order_now": False,
        "scheduled_time": order_time,
        "pre_check_time": pre_check_time,
        "estimated_delivery": delivery_target,
    }

async def schedule_order(state: ConversationState, schedule: dict):
    # Pre-check job
    scheduler.add_job(
        pre_order_check, "date",
        run_date=schedule["pre_check_time"],
        args=[state.session_id],
    )
    # Order job
    scheduler.add_job(
        execute_scheduled_order, "date",
        run_date=schedule["scheduled_time"],
        args=[state.session_id],
    )

async def pre_order_check(session_id: str):
    state = get_session(session_id)
    # Re-verify restaurant is OPEN
    restaurants = await swiggy.search_restaurants(state.current_intent.search_query, state.address_id)
    current = next((r for r in restaurants if r["id"] == state.cart_restaurant_id), None)

    if not current or current["availabilityStatus"] != "OPEN":
        cancel_schedule(session_id)
        notify_user(session_id, "Punjab Grill just closed 😕 want me to find a backup?")
        return

    new_eta = parse_eta(current["deliveryTime"])
    if datetime.now() + timedelta(minutes=new_eta + 5) > state.scheduled_order.estimated_delivery:
        cancel_schedule(session_id)
        notify_user(session_id, f"delivery time jumped to {new_eta} min, won't make it. order now anyway?")

Safety nets
Restaurant closed at pre-check → cancel, notify with backup offer
ETA spiked beyond target → cancel, notify with options
User says "cancel" anytime → kill scheduler, clear cart
place_food_order fails → check get_food_orders before retry
User in chat at order time → live "ordering now..." status
User not in chat → will see notification when they return

13. Personalization layer — the "foodie friend"
Not a separate service. It's the system prompt rules for Agent 4 + frontend formatting.
Persona identity
Voice: casual, warm, like texting a friend who knows food
NOT a character with a name — just a helpful, food-obsessed tone
Never robotic, never formal, never "I'd be happy to assist you"
References user's constraints naturally: "still keeping it under ₹300 👍"
Behavior rules
One message = one idea. Max 2 lines per bubble. Split into multiple bubbles.
Emojis: 1-2 per message, as punctuation not decoration
Quick reply chips at every decision point
After every recommendation: "need anything else to narrow down?" + [Re-suggest]
Always confirms before ordering: items + total + ETA + explicit "yes"
Remembers within session: never re-asks what was already answered
Branches naturally: "search chapati in same restaurant" works without losing cart

14. Error fallback chain
Failure
Fallback
Orchestrator can't classify
Default to new_search (full pipeline)
Agent 1 fails
Retry 3x → "sorry, didn't catch that — could you say it differently?"
Agent 2 rejects
Ask clarification for invalid field
Agent 3 fails
Show raw Swiggy results sorted by rating (no smart scoring)
Agent 3 Gemini rerank fails
Use deterministic scores only (skip intent_match)
Agent 4 fails
Show scored results in plain format (no personality, data intact)
Swiggy API timeout
httpx retry 3x with exponential backoff → template: "swiggy's taking a nap"
Restaurant closed between search and order
Re-run search_restaurants, suggest alternatives
Cart exceeds ₹1000
Block: "swiggy caps at ₹1000 — want to remove something?"
Coupon requires online payment
Filter upstream — only show COD-compatible coupons
Stale session (30+ min)
Re-validate state, fresh search, notify user
Scheduled order pre-check fails
Cancel schedule, notify with options


15. Order safety — architectural, not behavioral
The AI NEVER calls place_food_order. This is a code constraint, not a prompt instruction.
# FastAPI routes

@app.post("/api/chat")
async def chat(request: ChatRequest):
    """AI pipeline. Can search, score, format. CANNOT place orders."""
    # ... orchestrator + agents
    # place_food_order is NOT importable here

@app.post("/api/schedule")
async def schedule(request: ScheduleRequest):
    """Sets timer. Requires confirmed=True from frontend."""
    if not request.confirmed:
        raise HTTPException(400, "User must confirm schedule")
    # ... APScheduler job

@app.post("/api/place-order")
async def place_order(request: OrderRequest):
    """Places real order. ONLY callable from frontend button or confirmed scheduler."""
    if not request.confirmed:
        raise HTTPException(400, "User must confirm order")
    # Re-validate: cart ≤ ₹1000, restaurant OPEN
    cart = await swiggy.get_food_cart()
    if cart["total"] > 1000:
        raise HTTPException(400, "Cart exceeds ₹1000")
    # Place real order
    return await swiggy.place_food_order(payment_method="COD")

ORDER_ENABLED=false by default. Flip to true only after eval suite passes.

16. Observability — log every pipeline run
import structlog

log = structlog.get_logger()

async def run_pipeline(route: Route, message: str, state: ConversationState):
    start = time.time()
    pipeline_log = {
        "route": route.value,
        "message_length": len(message),
        "agents_called": [],
        "gemini_calls": 0,
        "gemini_latency_ms": [],
        "swiggy_calls": 0,
        "swiggy_latency_ms": [],
    }

    # ... run agents, track each call ...

    pipeline_log["total_latency_ms"] = (time.time() - start) * 1000
    log.info("pipeline_complete", **pipeline_log)

    # Example log output:
    # {
    #   "route": "new_search",
    #   "agents_called": ["intent", "validate", "score", "persona"],
    #   "gemini_calls": 3,
    #   "gemini_latency_ms": [280, 190, 310],
    #   "swiggy_calls": 2,
    #   "swiggy_latency_ms": [420, 180],
    #   "total_latency_ms": 1120
    # }

This data is how you tune scoring weights, identify slow routes, and debug recommendation quality.

17. Token budget management
Conversation grows. Message 15 sending full history to Gemini blows the context window.
Rule: Send only what each agent needs.
Agent
Context sent
Agent 1 (intent)
Current message + last 2 messages (for "make it healthier" context)
Agent 3 (rerank)
Current intent JSON + 10 dish names/descriptions only
Agent 4 (persona)
Last 6 messages + current intent + 6 dish results
Gemini classify
Current message + last 2 messages

Never send full message history. Never send raw Swiggy API responses to Gemini (too large). Extract only the fields each agent needs.
def prepare_agent4_context(state: ConversationState, dishes: list[dict]) -> str:
    # Compact: only last 6 messages
    history = state.get_context_window()
    # Compact: only relevant dish fields
    compact_dishes = [
        {"name": d["name"], "restaurant": d["restaurant_name"],
         "price": d["price"], "eta": d["eta"], "rating": d["rating"]}
        for d in dishes
    ]
    return json.dumps({"history": history, "dishes": compact_dishes, "intent": state.current_intent})


18. Project structure
swiggy-talk/
├── backend/
│   ├── main.py                    # FastAPI app, routes, SSE streaming
│   ├── orchestrator.py            # Message classifier + router
│   ├── agents/
│   │   ├── intent_parser.py       # Agent 1: Gemini structured output
│   │   ├── validator.py           # Agent 2: Pydantic validation
│   │   ├── scorer.py              # Agent 3: filters + weighted scoring
│   │   └── persona.py             # Agent 4: Gemini persona formatting
│   ├── services/
│   │   ├── swiggy_api.py          # All Swiggy tool calls (httpx async)
│   │   ├── swiggy_auth.py         # OAuth 2.1 + PKCE flow
│   │   └── scheduler.py           # APScheduler timing engine
│   ├── models/
│   │   ├── intent.py              # UserIntent Pydantic model
│   │   ├── state.py               # ConversationState model
│   │   └── responses.py           # Response bubble models
│   ├── utils/
│   │   ├── filters.py             # Hard filter gates
│   │   ├── weights.py             # Dynamic weight shifting
│   │   ├── parse_eta.py           # "25-30 mins" → 30
│   │   └── templates.py           # Template responses
│   ├── tests/
│   │   ├── test_intent.py         # 20+ intent parsing tests
│   │   ├── test_filters.py        # 10+ filter gate tests
│   │   ├── test_scoring.py        # 10+ scoring accuracy tests
│   │   ├── test_orchestrator.py   # Route classification tests
│   │   └── test_timing.py         # 10+ scheduler calculation tests
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── Chat/
│   │   │   │   ├── ChatPanel.jsx
│   │   │   │   ├── MessageBubble.jsx
│   │   │   │   ├── QuickReplies.jsx
│   │   │   │   └── TypingIndicator.jsx
│   │   │   ├── Recommendations/
│   │   │   │   ├── DishCard.jsx
│   │   │   │   ├── DishCardList.jsx
│   │   │   │   └── ResuggestButton.jsx
│   │   │   ├── Cart/
│   │   │   │   ├── CartSidebar.jsx
│   │   │   │   ├── CartItem.jsx
│   │   │   │   └── CartTotal.jsx
│   │   │   └── Order/
│   │   │       ├── OrderConfirm.jsx
│   │   │       ├── ScheduleConfirm.jsx
│   │   │       └── OrderStatus.jsx
│   │   ├── hooks/
│   │   │   ├── useChat.js
│   │   │   ├── useCart.js
│   │   │   ├── useSSE.js
│   │   │   └── useScheduler.js
│   │   └── App.jsx
│   ├── package.json
│   └── vite.config.js
├── architecture.md                 # THIS FILE
└── TODO.md                         # Generated by agent after reading this


19. Testing strategy
Phase A — Agent eval (no real orders)
Run before ANY real order. Test everything except place_food_order.
1. Intent accuracy: 20+ prompts → Agent 1 JSON correct?
2. Orchestrator routing: 15+ messages → correct route assigned?
3. Filter accuracy: 10+ scenarios → no closed/over-budget/wrong-diet results?
4. Scoring accuracy: 10+ scenarios → top 6 match human pick ≥80%?
5. Timing calculation: 10+ scenarios → correct order times?
6. Persona quality: 5+ scenarios → no fabricated data, ≤2 lines per bubble?
7. Latency: cart_action < 200ms? new_search < 1200ms?
8. Staleness: simulate 30min gap → state correctly invalidated?

Success criteria:
- Intent accuracy ≥ 95%
- Filter accuracy: 100%
- Orchestrator routing: 100% on regex cases, ≥90% on ambiguous
- Scoring: top 6 match human pick ≥80%
- Persona: zero fabricated data across all tests

Phase B — Real orders (manual, 1-3 orders)
After Phase A passes. Flip ORDER_ENABLED=true.
1. User reviews recommendations in chat
2. User builds cart through conversation
3. User clicks "Confirm Order" button
4. System calls place_food_order (COD)
5. Verify in Swiggy app
6. 1-3 total real orders


20. DO NOT build
❌ User auth system (Swiggy OAuth only — single personal account)
❌ Payment processing (COD only, Swiggy handles)
❌ Multi-user support
❌ MCP protocol handling (standard HTTP)
❌ Mock data or staging endpoints
❌ Auto-ordering without user confirmation
❌ Push notifications (out of MVP)
❌ Order history / cross-session personalization
❌ Voice input
❌ Multi-restaurant cart (Swiggy doesn't support it)
❌ Admin dashboard
❌ Analytics frontend

21. Build order for Cursor Agent
Project scaffolding — FastAPI backend + React frontend + folder structure
Swiggy OAuth flow — get_addresses working, token storage
Chat UI — message panel, SSE consumption, typing indicator, multi-bubble rendering
Orchestrator — regex classifier + conversation state + route dispatch
Agent 1 (intent) + Agent 2 (validator) — Gemini structured output + Pydantic
search_restaurants integration — real API, filter gates
Agent 3 (scorer) — weighted scoring, dynamic weights, Gemini re-rank
Agent 4 (persona) — formatting, tone, multi-bubble JSON output
Dish cards (6) + re-suggest + quick replies + conversational refinement
Cart sidebar — optimistic UI, sticky, add/remove, single-restaurant enforcement
Template responses — zero-Gemini acks for cart/cancel/order
Timing engine — schedule calculator, APScheduler, pre-check, safety nets
Order confirmation — summary screen, confirm button, place_food_order integration
Observability — structlog, pipeline latency tracking
Session management — staleness detection, token budget, sliding window
Eval suite — 20+ intent, 15+ routing, 10+ filter, 10+ scoring, 10+ timing tests
Real order testing — flip ORDER_ENABLED=true, 1-3 manual orders

22. Key reminders for the agent building this
Real APIs only — every call hits mcp.swiggy.com/food
Gemini 2.0 Flash, not Claude — use google-generativeai Python SDK
FastAPI, not Express — Python async backend
Orchestrator routes EVERY message — no agent runs without orchestrator deciding
ORDER_ENABLED=false by default — flip only after eval passes
Cart is single-restaurant — switching flushes (Swiggy constraint)
₹1000 cap — enforce in validator AND before order placement
Parse ETA conservatively — always max from "25-30 mins" (30)
availabilityStatus === "OPEN" — check on EVERY restaurant
place_food_order is NOT idempotent — on 5xx, check get_food_orders first
Stream responses via SSE — first bubble in ~100ms
Log every pipeline run — route, agents, latency, Gemini tokens
Last 6 messages to Gemini, not full history — manage token budget
Quick reply chips disappear after tap — never leave stale chips
Optimistic cart — show immediately, API in background

