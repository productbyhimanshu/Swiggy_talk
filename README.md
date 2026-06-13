# Swiggy Talk · Bhook

> A conversational AI food-ordering assistant built on real Swiggy Food APIs.
> Talk your way to dinner — no browsing, no ten-tap filters, no "20 results loaded."

```text
        ┌──────────────────────────────────────────────┐
        │  user: "comfort food, something under 300"  │
        │                                              │
        │  Bhook: "ok, sending warm food 🍜 want      │
        │         butter chicken vibes or biryani?"   │
        │  [butter chicken] [biryani] [re-suggest]    │
        │                                              │
        │  📷 6 cards — bestsellers + cheap + fast    │
        └──────────────────────────────────────────────┘
```

That's the goal: a friend on WhatsApp who *knows* food, the user's preferences,
the city's restaurants, and how to ask one good follow-up question instead of
five form fields.

---

## What makes Bhook different from "a chat UI on top of Swiggy"

| Most food chatbots | Bhook |
|---|---|
| Parse a keyword, query the API, dump 20 cards | Translate intent (`"comfort food"`) into 4 concrete dishes Swiggy can actually find, search in parallel, return 6 ranked picks |
| Same generic reply every turn | A character with a scratchpad — adapts tone to "rough day" vs "celebrating" |
| Stateless | Remembers your last orders, favourite spots, and dietary defaults across sessions |
| One probe per request, then guess | Confidence-driven clarification ladder — asks the right follow-up only when needed |
| Static intent schema | Memory-injected prompt, free-form mood detection, vague-query expansion via LLM |
| Bug-driven prompt edits | Quality judge with 12 ideal-reply transcripts — graded on relevance / tone / brevity / helpfulness |

The core architectural commitment: **the system understands intent before it
touches Swiggy**. The big risk in this kind of product is becoming a thin
proxy over an upstream search; everything below was built to push back on
that tendency.

---

## Architecture in one diagram

```text
              ┌─────────────────────────────────────────────────────┐
              │  React UI  (Vite)                                   │
              │  · streaming bubbles  · dish cards w/ images        │
              │  · proactive opener  · address picker popup         │
              └─────────────────────────────────────────────────────┘
                                  │  SSE
                                  ▼
              ┌─────────────────────────────────────────────────────┐
              │  FastAPI router  (phase_07)                         │
              │  · /api/chat   · /api/opener   · /api/addresses     │
              │  · /api/cart/* · /api/set-restaurant                │
              │  · disk-backed sessions  · order guard              │
              └─────────────────────────────────────────────────────┘
                                  │
   ┌──────────────────────────────┼──────────────────────────────┐
   ▼                              ▼                              ▼
┌──────────┐   ┌──────────────────────────┐   ┌────────────────────────┐
│Classifier│   │  Intent pipeline         │   │   Search & scoring     │
│ regex →  │   │  parse_intent (LLM)      │   │   expand_intent (LLM)  │
│ Gemini   │   │   ↳ confidence + probe   │   │   parallel multi-      │
│          │   │  validate (Pydantic)     │   │     search_restaurants │
│          │   │  _merge_intents (refine) │   │   get_restaurant_menu  │
└──────────┘   └──────────────────────────┘   │     cached 5 min       │
                                              │   dish scoring with    │
                                              │     keyword boost      │
                                              │   cross-result dedupe  │
                                              └────────────────────────┘
                                                       │
                                                       ▼
                                              ┌────────────────────────┐
                                              │  Persona  (LLM)        │
                                              │  · character doc       │
                                              │  · thinking scratchpad │
                                              │  · few-shot tones      │
                                              │  · memory facts in     │
                                              │     system prompt      │
                                              └────────────────────────┘
                                                       │
                                              ┌────────────────────────┐
                                              │  Long-term memory      │
                                              │  SQLite: profile,      │
                                              │   orders, rejections   │
                                              │  → proactive opener    │
                                              │  → fact injection      │
                                              └────────────────────────┘
```

---

## The features the architecture buys you

### 1. Vague queries don't dead-end

> *"comfort food"* used to return Swiggy garbage (item names with `undefined★`).
> Now: an LLM-driven **Intent Expander** maps it to 4 concrete search terms
> (`biryani`, `dal makhani`, `butter chicken`, `thali`), Bhook fires those in
> parallel, merges by `restaurantId`, then ranks. The persona is told *what
> angle* was taken so it can say *"sending warm food 🍜"* honestly.

[`phases/phase_06/agents/intent_expander.py`](phases/phase_06/agents/intent_expander.py)

### 2. Memory turns "input/output" into "a friend who knows you"

> An SQLite table per session writes every Add to cart, every rejection.
> On every Persona call, the top 5 facts get injected: `["veg only", "max
> ₹500", "orders from Wow! Momo often (3x)", "last order: Marky Momos"]`.
> Bhook references those naturally: *"same Wow! Momo as usual?"*

[`phases/phase_00/services/memory.py`](phases/phase_00/services/memory.py)

### 3. Proactive opener — empty chats aren't a wall

> The first bubble on a fresh chat is **context-aware**:
> - 12:45 PM on Friday + Wow! Momo habit → *"same Wow! Momo as usual?"*
> - 8 AM, no habit yet → *"morning! what's for breakfast? ☀️"*
> - Late night → *"late night cravings? 🌙 i got you"*

Zero LLM calls — pure clock + memory lookup. < 10ms.

[`phases/phase_06/handlers/opener.py`](phases/phase_06/handlers/opener.py)

### 4. Character document instead of a rule list

> The persona prompt isn't 20 bullet rules — it's three paragraphs describing
> *who Bhook is*: lowercase friend on WhatsApp, adjusts tone to mood, never
> says "I'd be happy to assist you", references the **shape** of results
> rather than listing names. Plus 5 few-shot conversations showing tone
> shifts (hangry / rough day / celebrating / repeat customer / rushed).

[`phases/phase_06/agents/persona.py`](phases/phase_06/agents/persona.py)

### 5. Thinking scratchpad before output

> The persona LLM is instructed to (silently) reason about the user's vibe
> and the angle on the results *before* it writes. The thinking is stripped
> from output. Costs ~200ms, buys 10× the personality variance.

### 6. Confidence-driven clarification ladder

> `UserIntent.confidence` is filled by the intent parser (0.0–1.0).
> - `≥0.8`: search immediately
> - `0.6–0.8`: search + offer refine chips
> - `<0.6`: ask the **single best probe** the LLM picked (`"for one or sharing?"`)

No more universally asking veg/non-veg. The system asks what's actually missing.

[`phases/phase_01/models/intent.py`](phases/phase_01/models/intent.py)

### 7. Dish-level recommendations with images

> When the query is dish-specific (`"momos under 200"`), Bhook fetches the
> top 6 restaurants' menus **in parallel** (5-min cache), filters items by
> name+diet+budget, ranks with a keyword-match score boost (+60 for exact
> phrase), cross-restaurant dedupes, and returns **6 actual dishes** with
> images, prices, bestseller flags, and per-card "why this pick" badges.

[`phases/phase_06/orchestrator.py`](phases/phase_06/orchestrator.py)

### 8. Conversational scheduling

> *"deliver lunch by 1 pm"* gets a real proposal: calculates fire time
> (1pm − 30min ETA − 5min buffer = 12:25pm), shows confirm chip. Tap
> "Confirm" → an APScheduler job registers. Tap "No, order now" → it
> vanishes cleanly. Combined queries like *"momos at 8pm"* get food
> results first, schedule offer at the end.

[`phases/phase_06/handlers/schedule_handler.py`](phases/phase_06/handlers/schedule_handler.py)

### 9. Quality judge for prompt iteration

> 12 hand-written ideal Bhook replies. A strict judge LLM scores actual
> output on relevance / tone / brevity / helpfulness. Gates at avg ≥4.0
> on every axis. **Current status: ✅ all axes passing.** Use it to iterate
> persona prompts with discipline instead of vibes.

```bash
PYTHONPATH=. python3.11 scripts/quality_judge.py
```

[`scripts/quality_judge.py`](scripts/quality_judge.py)

### 10. Three live eval scripts

- [`scripts/live_eval.py`](scripts/live_eval.py) — intent + persona, real LLM (~67s)
- [`scripts/live_eval_extended.py`](scripts/live_eval_extended.py) — context, rerank, injection resistance, hallucination starvation (~27s)
- [`scripts/live_eval_e2e.py`](scripts/live_eval_e2e.py) — end-to-end via the running backend, cart-flush cleanup, **proves the order guard blocks live ordering** (~21s)

---

## Order safety — why it's actually safe, not just a flag

`ORDER_ENABLED=false` by default. **Three layers** prevent a real order from
being placed:

1. **Guard** ([`phase_00/services/order_guard.py`](phases/phase_00/services/order_guard.py)) — `assert_orders_enabled()` raises `OrderDisabledError` unless **both** `ORDER_ENABLED` and `EVAL_SUITE_PASSED` are `true`.
2. **Architectural separation** — `place_food_order` is **not importable** from `/api/chat` or any agent module. The AI literally has no path to it.
3. **Scheduler stub** — even a confirmed scheduled order hits the guard first and returns `{ok: false, reason: "order_disabled"}` (verified live in [`live_eval_e2e.py`](scripts/live_eval_e2e.py)).

21 of the 224 offline tests are dedicated to verifying these can't be bypassed.

---

## Quick start

### 1. Backend

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cp .env.example .env
# Edit .env: add EMERGENT_LLM_KEY (or GEMINI_API_KEY), Swiggy OAuth creds
```

### 2. Swiggy OAuth

1. [mcp.swiggy.com/access](https://mcp.swiggy.com/access)
2. Redirect URI: `http://localhost:8000/auth/callback`
3. Keep `ORDER_ENABLED=false`

### 3. Run

```bash
uvicorn backend.main:app --port 8000
# OAuth login: http://localhost:8000/auth/swiggy/login
```

### 4. Frontend

```bash
cd frontend && npm install && npm run dev
# http://localhost:5173
```

### 5. Try it

In the chat: `comfort food`, `momos under 200`, `lunch at 1pm`, `something light`.

---

## Tests

```bash
# Offline gate — 224 tests across all phases
bash scripts/run_eval_suite.sh

# Live evals (real LLM, real Swiggy reads, no orders)
PYTHONPATH=. python3.11 scripts/live_eval.py            # intent + persona
PYTHONPATH=. python3.11 scripts/live_eval_extended.py   # context, injection, hallucination
PYTHONPATH=. python3.11 scripts/live_eval_e2e.py        # E2E backend
PYTHONPATH=. python3.11 scripts/quality_judge.py        # 12-scenario quality judge
```

**Current status:** ✅ 224/224 offline, all live evals pass.

---

## Code layout

```
phases/
├── phase_00/   OAuth, Swiggy API client, logging, order guard, LLM adapter (Emergent)
├── phase_01/   Conversation state + intent model
├── phase_02/   Classifier (regex + Gemini fallback, food-aware routing)
├── phase_03/   Intent parser (Agent 1) — confidence + clarify_probe + clarify_options
├── phase_04/   Read tools, filter gates, menu cache
├── phase_05/   Scorer (Agent 3) — multi-factor + Gemini rerank
├── phase_06/
│   ├── agents/
│   │   ├── persona.py            character doc + scratchpad + few-shots
│   │   ├── intent_expander.py    vague → concrete searches (LLM)
│   │   └── why_picker.py         deterministic per-card badges
│   ├── handlers/
│   │   ├── schedule_handler.py   timing engine integration
│   │   └── opener.py             proactive first-message
│   └── orchestrator.py           routes + dish-level pipeline
├── phase_07/   SSE router, disk-backed sessions
├── phase_09/   Cart API (with optimistic UI sync)
├── phase_10/   Retries, fallback chain
├── phase_11/   APScheduler timing engine
└── phase_12/   Full eval suite gate

phase_00/services/
├── memory.py          SQLite — profile, orders, rejections, get_user_facts
├── gemini_client.py   Emergent LLM proxy adapter (replaces deprecated google.generativeai)
└── swiggy_*.py        OAuth + raw HTTP JSON-RPC

frontend/src/
├── components/
│   ├── Chat/          ChatPanel, AppBar, AddressSheet, Composer, MessageBubble
│   ├── Recommendations/  DishCard with image, why-badge, switch-restaurant flag
│   ├── Cart/          CartBar, BasketSheet, DesktopCart
│   └── Layout/        DesktopShell
└── hooks/             useChat, useCart, useAddress

scripts/
├── run_eval_suite.sh        offline 224-test gate
├── live_eval.py             intent + persona quality
├── live_eval_extended.py    context / injection / hallucination
├── live_eval_e2e.py         E2E backend (proves order guard live)
└── quality_judge.py         12-scenario LLM-judged quality
```

---

## What's intentionally not built (yet)

- **Full tool-calling agent loop** — would be the architecturally pure version of the current pipeline. ~1 week refactor; Intent Expansion delivers 70% of the benefit in 1 day.
- **Vector store / RAG** — overkill for a single-user app. Embeddings would need food-domain fine-tuning to match the LLM expansion's quality.
- **Custom restaurant index** — Swiggy has the inventory we don't. The fix isn't a better search engine, it's a better *query* (which is what Intent Expansion delivers).

These are documented as the right architectural answers for *later scale*, not the right answer *now*. See [`doc/architecture.md`](doc/architecture.md) §22 for the full reasoning.

---

## Design docs

- [`doc/architecture.md`](doc/architecture.md) — full architectural spec, updated through Phase 14
- [`TODO.md`](TODO.md) — phase checklist with eval criteria
- [`doc/agent_log.md`](doc/agent_log.md) — running engineering decision log

---

## License & status

**Status:** Phase 12 gate passed (224/224 tests). Phase 13 (real-order
placement) requires manual sign-off — `ORDER_ENABLED=true` only after a
human reviews the eval matrix.

Built with Claude Code · Gemini 2.5 Flash via Emergent · React + Vite + FastAPI.
