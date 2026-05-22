# Swiggy Talk — Phased Development Checklist

> **Source of truth:** [`doc/architecture.md`](doc/architecture.md)  
> **Code layout:** [`phases/`](phases/) — one folder per phase (`phase_00/` … `phase_13/`), not markdown docs  
> **Swiggy API reference (endpoints/tools only — we do NOT use MCP protocol):** [swiggy-mcp-server-manifest](https://github.com/Swiggy/swiggy-mcp-server-manifest) · [Builders docs](https://mcp.swiggy.com/builders/docs/)  
> **Transport:** `httpx` async → `https://mcp.swiggy.com/food` · JSON-RPC tool calls · OAuth 2.1 + PKCE  

**Legend:** `[LOCAL]` · `[GEMINI]` · `[SWIGGY READ]` · `[SWIGGY WRITE]`

---

## Global safety rules (all phases)

| Rule | Enforcement |
|------|-------------|
| **No real orders in dev/test** | `ORDER_ENABLED=false` default; `place_food_order` stubbed/mocked until Phase 12 gate |
| **AI never places orders** | `place_food_order` not importable from `/api/chat` or agent modules |
| **No MCP SDK/wrappers** | `services/swiggy_api.py` = raw HTTP JSON-RPC only |
| **No mock restaurant data** | Reads hit real Swiggy; writes to cart allowed; **order placement blocked** |
| **₹1000 cap** | Validator + pre-order route checks |
| **COD only** | Filter online-payment coupons upstream |

---

## Phase 0 — Environment, dependencies, OAuth, local config

**Goal:** Runnable local stack with auth working; **zero order capability**.

| # | Task | Label | Depends on |
|---|------|-------|------------|
| 0.1 | Create repo layout per architecture §18 (`backend/`, `frontend/`, `backend/tests/`) | LOCAL | — |
| 0.2 | Python 3.11+ venv; `backend/requirements.txt` (FastAPI, httpx, pydantic v2, google-generativeai, apscheduler, structlog, pytest, pytest-asyncio) | LOCAL | 0.1 |
| 0.3 | React + Vite scaffold; `frontend/package.json` | LOCAL | 0.1 |
| 0.4 | `.env.example` with all vars from architecture §3; **document `ORDER_ENABLED=false` required for dev** | LOCAL | 0.1 |
| 0.5 | `.gitignore`: `.env`, token files, `*.token`, secrets | LOCAL | 0.1 |
| 0.6 | `config.py`: load env; **`ORDER_ENABLED` defaults `false`**; raise if `ORDER_ENABLED=true` without `EVAL_SUITE_PASSED=true` | LOCAL | 0.4 |
| 0.7 | Register Swiggy Builders OAuth app; set redirect `http://localhost:3000/callback` (or architecture URI) | LOCAL | — |
| 0.8 | Implement `services/swiggy_auth.py`: OAuth 2.1 + PKCE; token refresh; secure local token store | LOCAL · SWIGGY READ | 0.7 |
| 0.9 | Implement `services/swiggy_api.py` skeleton: JSON-RPC `call_tool(name, args)` over HTTP POST — **not MCP protocol** | LOCAL | 0.8 |
| 0.10 | `place_food_order` guard module: raises `OrderDisabledError` unless `ORDER_ENABLED=true` AND `EVAL_SUITE_PASSED=true` | LOCAL | 0.6 |
| 0.11 | FastAPI `main.py` health route; CORS for `FRONTEND_URL` | LOCAL | 0.2 |
| 0.12 | structlog JSON logging bootstrap | LOCAL | 0.2 |

### Phase 0 — Verification (must pass before Phase 1)

| # | Check | Label |
|---|-------|-------|
| 0.E1 | `pytest backend/tests/test_config.py` — `ORDER_ENABLED` false by default; gate blocks order when eval not passed | LOCAL |
| 0.E2 | Manual OAuth flow completes; token persisted | SWIGGY READ |
| 0.E3 | `get_addresses` returns ≥1 address via `swiggy_api.call_tool("get_addresses", {})` | SWIGGY READ |
| 0.E4 | Confirm **no** code path calls `place_food_order` (grep CI check) | LOCAL |

**Phase 0 exit criteria:** OAuth works, `get_addresses` works, order placement **impossible**.

---

## Phase 1 — Core backend skeleton + session state

**Goal:** Session model and in-memory store; still no chat pipeline.

| # | Task | Label | Depends on |
|---|------|-------|------------|
| 1.1 | `models/state.py` — `ConversationState` (architecture §5) | LOCAL | 0.1 |
| 1.2 | `models/intent.py`, `models/responses.py` — Pydantic stubs | LOCAL | 1.1 |
| 1.3 | In-memory session store `get_session` / `create_session`; `SESSION_TIMEOUT_MINUTES` | LOCAL | 1.1 |
| 1.4 | `check_staleness()` — 30 min invalidation (architecture §5) | LOCAL | 1.1 |
| 1.5 | Wire `address_id` from first successful `get_addresses` into session | LOCAL · SWIGGY READ | 0.E3, 1.3 |

### Phase 1 — Eval

| # | Test | Label |
|---|------|-------|
| 1.E1 | `test_state.py` — staleness clears `cached_results`, `has_recommendations`, `current_restaurant_id` | LOCAL |
| 1.E2 | `test_state.py` — sliding window returns last 6 messages only | LOCAL |
| 1.E3 | `test_session.py` — new session defaults; timeout behavior | LOCAL |

**Phase 1 exit:** `pytest backend/tests/test_state.py backend/tests/test_session.py` green.

---

## Phase 2 — Orchestrator (routing only)

**Goal:** Hybrid regex + Gemini classify; route dispatch stubs (no full agents).

| # | Task | Label | Depends on |
|---|------|-------|------------|
| 2.1 | `orchestrator.py` — `Route` enum + `PATTERNS` + context guards (architecture §5) | LOCAL | 1.1 |
| 2.2 | `classify()` — priority: clarify → regex → ambiguous | LOCAL | 2.1 |
| 2.3 | `gemini_classify()` — fast JSON route label (~10 tokens) | GEMINI | 0.4, 2.2 |
| 2.4 | `run_pipeline()` stub — logs route, returns template by route | LOCAL | 2.2 |
| 2.5 | Route table wiring (architecture §5) — stub handlers per route | LOCAL | 2.4 |

### Phase 2 — Eval: routing

| # | Test | Label |
|---|------|-------|
| 2.E1 | `test_orchestrator.py` — **15+ regex cases** → expected `Route` (greeting, cancel, cart, order w/ empty cart guard, refine w/o recs, etc.) | LOCAL |
| 2.E2 | `test_orchestrator.py` — `awaiting_clarification` forces `CLARIFY_REPLY` | LOCAL |
| 2.E3 | `test_orchestrator.py` — ambiguous messages (mock Gemini) → route enum valid | LOCAL · GEMINI |
| 2.E4 | `test_orchestrator.py` — **edge:** empty message, emoji-only, mixed language | LOCAL |
| 2.E5 | `test_orchestrator.py` — **failure:** Gemini classify timeout → fallback `NEW_SEARCH` | LOCAL · GEMINI |

**Phase 2 exit:** Routing tests 100% on regex cases; ambiguous ≥90% with mocked Gemini.

---

## Phase 3 — Agent 1 (intent) + Agent 2 (validation)

**Goal:** Structured intent extraction + zero-LLM validation.

| # | Task | Label | Depends on |
|---|------|-------|------------|
| 3.1 | `agents/intent_parser.py` — `UserIntent` + Gemini `response_schema` | GEMINI | 1.2, 0.4 |
| 3.2 | `agents/validator.py` — budget cap, `NEEDS_CLARIFICATION`, signal check | LOCAL | 3.1 |
| 3.3 | Clarification response builder + `quick_replies` | LOCAL | 3.2 |
| 3.4 | Orchestrator: `NEW_SEARCH` / `CLARIFY_REPLY` call intent → validate | LOCAL | 2.5, 3.2 |

### Phase 3 — Eval: intent parsing + validation

| # | Test | Label |
|---|------|-------|
| 3.E1 | `test_intent.py` — **20+ prompts** → expected `UserIntent` fields (mock or recorded Gemini fixtures) | GEMINI |
| 3.E2 | `test_intent.py` — **edge:** invalid JSON from Gemini → retry/error message | GEMINI |
| 3.E3 | `test_intent.py` — **edge:** `budget_max: -500` rejected by Pydantic | LOCAL |
| 3.E4 | `test_validator.py` — budget >1000 → clarify | LOCAL |
| 3.E5 | `test_validator.py` — `NEEDS_CLARIFICATION` veg path | LOCAL |
| 3.E6 | `test_validator.py` — no signals → clarify question | LOCAL |
| 3.E7 | `test_validator.py` — **failure:** Agent 1 fails 3x → user-facing fallback string | LOCAL · GEMINI |

**Phase 3 exit:** Intent accuracy ≥95% on fixture suite; validator 100% on business rules.

---

## Phase 4 — Swiggy read path: search + menu + filters

**Goal:** Real restaurant data through pipeline; scoring not yet required.

| # | Task | Label | Depends on |
|---|------|-------|------------|
| 4.1 | `swiggy_api.py` — `search_restaurants`, `get_restaurant_menu`, `search_menu` | SWIGGY READ | 0.9, 1.5 |
| 4.2 | `utils/parse_eta.py` — conservative max ETA | LOCAL | 4.1 |
| 4.3 | `utils/filters.py` — hard gates: OPEN, rating, ETA, diet, budget (architecture §6) | LOCAL | 4.2 |
| 4.4 | Orchestrator `NEW_SEARCH` — address resolve → `search_restaurants` → menu fetch | SWIGGY READ | 3.4, 4.1 |
| 4.5 | Cache `state.cached_results` after search | LOCAL | 4.4 |

### Phase 4 — Eval: validation (filters) + Swiggy read

| # | Test | Label |
|---|------|-------|
| 4.E1 | `test_filters.py` — **10+ scenarios** — closed restaurant killed; veg filter; budget; ETA window | LOCAL |
| 4.E2 | `test_parse_eta.py` — `"25-30 mins"` → 30; malformed → 45 default | LOCAL |
| 4.E3 | `test_filters.py` — **edge:** empty search results → graceful empty state | LOCAL |
| 4.E4 | `test_swiggy_read.py` — integration: `search_restaurants` returns only OPEN (manual/CI skip if no token) | SWIGGY READ |
| 4.E5 | `test_filters.py` — **failure:** Swiggy timeout → retried 3x (mock httpx) | LOCAL |

**Phase 4 exit:** Filter accuracy **100%** on fixtures; live read smoke optional.

---

## Phase 5 — Agent 3 (scoring + Gemini re-rank)

**Goal:** Deterministic score + soft re-rank; top 6 dishes.

| # | Task | Label | Depends on |
|---|------|-------|------------|
| 5.1 | `utils/weights.py` — `get_weights()` lookup table | LOCAL | 3.1 |
| 5.2 | `agents/scorer.py` — weighted score formula (architecture §6) | LOCAL | 4.3, 5.1 |
| 5.3 | `gemini_rerank()` — top 10 only; invalid response → equal 50s | GEMINI | 5.2 |
| 5.4 | `final_rank()` → top 6; parallel: Swiggy task + weights (architecture §7) | LOCAL · SWIGGY READ | 4.4, 5.2 |
| 5.5 | `REFINE` route — re-score cached results, **no** new `search_restaurants` | LOCAL | 5.4, 2.5 |

### Phase 5 — Eval: scoring

| # | Test | Label |
|---|------|-------|
| 5.E1 | `test_scoring.py` — **10+ scenarios** — weight shifts (fast, budget, protein) | LOCAL |
| 5.E2 | `test_scoring.py` — top 6 ordering stable with fixed fixtures | LOCAL |
| 5.E3 | `test_scoring.py` — **failure:** Gemini rerank bad array → fallback equal scores | GEMINI |
| 5.E4 | `test_scoring.py` — **failure:** Agent 3 exception → raw results sorted by rating | LOCAL |
| 5.E5 | `test_scoring.py` — **edge:** &lt;6 survivors after filters → return fewer | LOCAL |

**Phase 5 exit:** Scoring fixtures ≥80% match human top-6 picks; rerank fallback tests green.

---

## Phase 6 — Agent 4 (persona) + templates

**Goal:** Multi-bubble JSON output; template fast paths.

| # | Task | Label | Depends on |
|---|------|-------|------------|
| 6.1 | `agents/persona.py` — locked data rules; bubble array output | GEMINI | 5.4 |
| 6.2 | `utils/templates.py` — cart/cancel/stale/swiggy_down templates | LOCAL | 2.5 |
| 6.3 | `prepare_agent4_context()` — token budget (last 6 msgs, compact dishes) | LOCAL | 1.1, 6.1 |
| 6.4 | Wire templates for `CART_ACTION`, `CANCEL`, `ORDER` (order routes to frontend only) | LOCAL | 6.2 |

### Phase 6 — Eval: persona + Gemini failure

| # | Test | Label |
|---|------|-------|
| 6.E1 | `test_persona.py` — **5+ scenarios** — no price/name/ETA fabrication vs input | GEMINI |
| 6.E2 | `test_persona.py` — ≤2 lines per bubble | LOCAL |
| 6.E3 | `test_persona.py` — **failure:** Agent 4 fails → plain format, data intact | GEMINI |
| 6.E4 | `test_templates.py` — cart/cancel/stale return zero Gemini calls (mock counter) | LOCAL |

**Phase 6 exit:** Zero fabricated fields on fixtures; template routes confirmed 0 Gemini.

---

## Phase 7 — SSE streaming + `/api/chat`

**Goal:** Streaming multi-bubble UX end-to-end (backend).

| # | Task | Label | Depends on |
|---|------|-------|------------|
| 7.1 | `POST /api/chat` — `StreamingResponse` `text/event-stream` | LOCAL | 2.5, 6.1 |
| 7.2 | `stream_response()` — staleness bubble → classify → pipeline → bubble events | LOCAL | 1.4, 7.1 |
| 7.3 | Event types: `bubble`, `cards`, `cart_update`, `[DONE]`; 80ms inter-bubble delay | LOCAL | 7.2 |
| 7.4 | Pipeline observability log — route, agents, latencies (architecture §16) | LOCAL | 7.2 |

### Phase 7 — Eval: SSE streaming

| # | Test | Label |
|---|------|-------|
| 7.E1 | `test_sse.py` — event sequence order: bubbles → cards → `[DONE]` | LOCAL |
| 7.E2 | `test_sse.py` — `CART_ACTION` emits `cart_update` | LOCAL |
| 7.E3 | `test_sse.py` — staleness first event before pipeline | LOCAL |
| 7.E4 | `test_sse.py` — **edge:** client disconnect mid-stream — no session corruption | LOCAL |
| 7.E5 | `test_sse.py` — **latency:** `cart_action` path &lt;200ms (mock Swiggy) | LOCAL |

**Phase 7 exit:** SSE contract tests green; `new_search` &lt;1200ms with mocks.

---

## Phase 8 — Frontend chat UI (no order button yet)

**Goal:** React consumes SSE; dish cards; quick replies.

| # | Task | Label | Depends on |
|---|------|-------|------------|
| 8.1 | `useSSE` / `useChat` hooks — parse SSE events | LOCAL | 7.1 |
| 8.2 | `ChatPanel`, `MessageBubble`, `TypingIndicator` | LOCAL | 8.1 |
| 8.3 | `DishCardList` — 6 cards from `cards` event | LOCAL | 8.1 |
| 8.4 | `QuickReplies` — hide on select; stale chips disabled | LOCAL | 8.2 |
| 8.5 | `ResuggestButton` — sends refine message | LOCAL | 8.1 |

### Phase 8 — Eval

| # | Test | Label |
|---|------|-------|
| 8.E1 | Manual: first bubble &lt;~300ms perceived | LOCAL |
| 8.E2 | Manual: quick reply sends as user message; chip disappears | LOCAL |
| 8.E3 | `test_staleness.py` — **30 min gap** simulation → refresh message + state cleared | LOCAL |

**Phase 8 exit:** Chat UI works against local backend; no order UI.

---

## Phase 9 — Cart (read/write) + optimistic UI + rollback

**Goal:** Cart CRUD via Swiggy; optimistic frontend; single-restaurant enforcement.

| # | Task | Label | Depends on |
|---|------|-------|------------|
| 9.1 | `swiggy_api.py` — `update_food_cart`, `get_food_cart`, `flush_food_cart` | SWIGGY WRITE | 0.9 |
| 9.2 | `fetch_food_coupons`, `apply_food_coupon` — COD-only filter | SWIGGY READ · SWIGGY WRITE | 9.1 |
| 9.3 | `/api/cart/add`, `/api/cart/remove` — background sync | LOCAL · SWIGGY WRITE | 9.1 |
| 9.4 | Orchestrator `CART_ACTION` — template ack + `cart_update` SSE | LOCAL | 7.3, 9.1 |
| 9.5 | Single-restaurant: restaurant switch → `flush_food_cart` first | SWIGGY WRITE | 9.1 |
| 9.6 | `CartSidebar` optimistic add — pending → confirmed / rollback on error | LOCAL | 8.1, 9.3 |
| 9.7 | ₹1000 cart block in chat + API | LOCAL | 9.1 |

### Phase 9 — Eval: cart + optimistic rollback

| # | Test | Label |
|---|------|-------|
| 9.E1 | `test_cart.py` — add/remove updates `cart_has_items` state | LOCAL |
| 9.E2 | `test_cart.py` — **optimistic rollback:** API 500 → item removed + error bubble | LOCAL |
| 9.E3 | `test_cart.py` — restaurant switch triggers flush | SWIGGY WRITE |
| 9.E4 | `test_cart.py` — cart &gt;₹1000 blocked | LOCAL |
| 9.E5 | `test_cart.py` — **edge:** `update_food_cart` timeout → rollback message | LOCAL |
| 9.E6 | Manual UI: item shows pending then confirmed | LOCAL |

**Phase 9 exit:** Cart tests green; **still no** `place_food_order`.

---

## Phase 10 — Retries, fallbacks, error chain

**Goal:** Full fallback chain (architecture §14).

| # | Task | Label | Depends on |
|---|------|-------|------------|
| 10.1 | httpx retry 3x exponential backoff on Swiggy calls | LOCAL | 4.1 |
| 10.2 | Orchestrator unclassified → `NEW_SEARCH` | LOCAL | 2.2 |
| 10.3 | Restaurant closed between search and cart → re-search + message | SWIGGY READ | 4.4 |
| 10.4 | Coupon online-payment → filtered out | LOCAL | 9.2 |
| 10.5 | `IN_RESTAURANT` route — `search_menu` + scorer + persona | SWIGGY READ · GEMINI | 5.4, 2.5 |

### Phase 10 — Eval: retries/fallbacks

| # | Test | Label |
|---|------|-------|
| 10.E1 | `test_retries.py` — Swiggy 503 → 3 retries then template `swiggy_down` | LOCAL |
| 10.E2 | `test_fallbacks.py` — full chain table (architecture §14) — each row | LOCAL |
| 10.E3 | `test_fallbacks.py` — **edge:** `place_food_order` 5xx → `get_food_orders` before retry (mock; order still disabled) | LOCAL |
| 10.E4 | `test_fallbacks.py` — Gemini classify failure → `NEW_SEARCH` | GEMINI |

**Phase 10 exit:** All fallback fixtures green.

---

## Phase 11 — Timing scheduler (no auto-place)

**Goal:** APScheduler computes times; pre-check jobs; **scheduled `place_food_order` stubbed**.

| # | Task | Label | Depends on |
|---|------|-------|------------|
| 11.1 | `services/scheduler.py` — `calculate_order_time()`, buffer, 4h warn | LOCAL | 4.2 |
| 11.2 | `SCHEDULE` route in orchestrator | LOCAL | 2.5, 11.1 |
| 11.3 | `POST /api/schedule` — requires `confirmed=True`; stores job | LOCAL | 11.1 |
| 11.4 | `pre_order_check` — OPEN, ETA, cart valid; cancel + notify on fail | SWIGGY READ | 11.3, 9.1 |
| 11.5 | `execute_scheduled_order` — calls **stub** `place_food_order` (blocked) | LOCAL | 0.10, 11.3 |
| 11.6 | User cancel — kill jobs + `flush_food_cart` optional per UX | LOCAL · SWIGGY WRITE | 11.3 |
| 11.7 | `ScheduleConfirm.jsx` + `useScheduler` | LOCAL | 11.3, 8.1 |

### Phase 11 — Eval: scheduler timing

| # | Test | Label |
|---|------|-------|
| 11.E1 | `test_timing.py` — **10+ scenarios** — lunch at 1 PM → order 12:25 (30 ETA + 5 buffer) | LOCAL |
| 11.E2 | `test_timing.py` — tight window → `order_now: True` | LOCAL |
| 11.E3 | `test_timing.py` — &gt;4h → warn path | LOCAL |
| 11.E4 | `test_timing.py` — pre-check: restaurant closed → schedule cancelled | LOCAL |
| 11.E5 | `test_timing.py` — pre-check: ETA spike → cancel + options | LOCAL |
| 11.E6 | `test_timing.py` — **edge:** user cancel before job fires — no stub order call | LOCAL |
| 11.E7 | `test_timing.py` — **failure:** scheduler job exception → logged, user notified | LOCAL |

**Phase 11 exit:** Timing tests 100%; confirm stub never places real order.

---

## Phase 12 — Full eval suite gate (Phase A)

**Goal:** Run **all** tests; block production order path until pass.

| # | Task | Label | Depends on |
|---|------|-------|------------|
| 12.1 | `scripts/run_eval_suite.sh` — runs all `backend/tests/` | LOCAL | Phases 1–11 |
| 12.2 | Set `EVAL_SUITE_PASSED=true` only in CI/local after 12.1 success (manual flag file or env) | LOCAL | 12.1 |
| 12.3 | **Checkpoint:** Review matrix below — all must pass | LOCAL | 12.1 |

### Phase 12 — Eval matrix (architecture §19 Phase A)

| Suite | Target | Blocking? |
|-------|--------|-------------|
| Intent (3.E*) | ≥95% | Yes |
| Routing (2.E*) | 100% regex; ≥90% ambiguous | Yes |
| Filters (4.E*) | 100% | Yes |
| Scoring (5.E*) | ≥80% human agreement | Yes |
| Timing (11.E*) | 100% | Yes |
| Persona (6.E*) | 0% fabrication | Yes |
| SSE (7.E*) | contract + latency | Yes |
| Staleness (1.E*, 8.E3) | state cleared | Yes |
| Cart rollback (9.E*) | pass | Yes |
| Retries/fallbacks (10.E*) | pass | Yes |
| Gemini failures (3.E7, 5.E3, 6.E3, 10.E4) | pass | Yes |
| **place_food_order** | **must remain blocked** | Yes |

| # | Edge / failure scenario tests (cross-cutting) | Label |
|---|-----------------------------------------------|-------|
| 12.E1 | Empty Swiggy search → friendly persona, no crash | LOCAL |
| 12.E2 | Session timeout mid-cart → staleness + refresh | LOCAL |
| 12.E3 | Concurrent cart add requests → consistent final cart | LOCAL |
| 12.E4 | Gemini rate limit → degraded path still returns data | GEMINI |
| 12.E5 | Invalid `addressId` → clarify / re-fetch addresses | SWIGGY READ |
| 12.E6 | `ORDER` route with empty cart → no order UI / clarify | LOCAL |
| 12.E7 | `ORDER_ENABLED=true` without eval flag → startup error | LOCAL |

**Phase 12 exit:** `EVAL_SUITE_PASSED=true` documented; **still** `ORDER_ENABLED=false`.

---

## Phase 13 — Order UI + enable real placement (FINAL — manual only)

**Goal:** User-button-only real orders; **last task enables writes to `place_food_order`**.

| # | Task | Label | Depends on |
|---|------|-------|------------|
| 13.1 | `OrderConfirm.jsx` — items + total + ETA; explicit confirm | LOCAL | 9.6, 12.3 |
| 13.2 | `POST /api/place-order` — `confirmed=True` only; re-validate OPEN + cart ≤₹1000 | LOCAL · SWIGGY READ | 12.3, 9.1 |
| 13.3 | **CHECKPOINT:** Human sign-off on eval matrix + Phase 12 logs | LOCAL | 12.3 |
| 13.4 | **FINAL TASK:** Remove stub; wire real `place_food_order` behind `ORDER_ENABLED` | SWIGGY WRITE | 13.1–13.3 |
| 13.5 | Set `ORDER_ENABLED=true` in **production `.env` only** — never in test CI env | LOCAL | 13.4 |
| 13.6 | `track_food_order` read path + `OrderStatus.jsx` | SWIGGY READ | 13.4 |
| 13.7 | Scheduled job `execute_scheduled_order` → real `place_food_order` when `ORDER_ENABLED` | SWIGGY WRITE | 11.5, 13.4 |

### Phase 13 — Eval: real orders (Phase B — manual, NOT in CI)

| # | Test | Label |
|---|------|-------|
| 13.E1 | CI: `test_order_blocked.py` — `place_food_order` raises when `ORDER_ENABLED=false` | LOCAL |
| 13.E2 | CI: `test_order_blocked.py` — `/api/place-order` returns 403 when disabled | LOCAL |
| 13.E3 | **Manual only:** 1–3 real COD orders with human review — **excluded from automated CI** | SWIGGY WRITE |
| 13.E4 | **Manual:** 5xx on place → `get_food_orders` dedup before retry | SWIGGY READ · SWIGGY WRITE |

**Phase 13 exit:** Real orders only via confirm button; 1–3 manual verifications in Swiggy app.

---

## Dependency graph (strict order)

```text
Phase 0 ──► Phase 1 ──► Phase 2 ──► Phase 3 ──► Phase 4 ──► Phase 5 ──► Phase 6
                                                              │
                                                              ▼
Phase 8 ◄── Phase 7 ◄─────────────────────────────────────────┘
  │
  ▼
Phase 9 ──► Phase 10 ──► Phase 11 ──► Phase 12 (eval gate) ──► Phase 13 (place_food_order LAST)
```

**Parallelizable after Phase 7:** Phase 8 (frontend) can start once SSE contract tests (7.E*) pass.

---

## API tool rollout map (HTTP JSON-RPC — not MCP)

| Tool | Phase introduced | Write? | Enabled when |
|------|------------------|--------|--------------|
| `get_addresses` | 0 | Read | Dev |
| `search_restaurants` | 4 | Read | Dev |
| `get_restaurant_menu` | 4 | Read | Dev |
| `search_menu` | 10 | Read | Dev |
| `update_food_cart` | 9 | **Write** | Dev (real cart, not orders) |
| `get_food_cart` | 9 | Read | Dev |
| `flush_food_cart` | 9 | **Write** | Dev |
| `fetch_food_coupons` | 9 | Read | Dev |
| `apply_food_coupon` | 9 | **Write** | Dev |
| `get_food_orders` | 10 (dedup), 13 | Read | Dev |
| `track_food_order` | 13 | Read | After 13.4 |
| `place_food_order` | **13.4 ONLY** | **REAL ORDER** | `ORDER_ENABLED=true` + eval passed |

---

## Environment profiles

| Profile | `ORDER_ENABLED` | `place_food_order` | Swiggy writes allowed |
|---------|-----------------|--------------------|------------------------|
| local-dev | `false` | stub | cart/coupons only |
| ci-test | `false` | mock | httpx mocks (no network) or read-only integration job |
| staging | `false` | stub | same as dev |
| production | `true` **only after Phase 12** | real | full |

**CI rule:** Add `pytest -k "not manual"` and a grep/lint rule: `place_food_order` only imported from `swiggy_api.py` + order route module.

---

## Quick reference — what NOT to build (architecture §20)

- MCP protocol wrappers (use HTTP JSON-RPC only)
- Mock restaurant data
- Auto-order without user click
- Multi-user auth
- Staging endpoints

---

*Generated from `doc/architecture.md` v4.0 — phased checklist with order safety gates.*
