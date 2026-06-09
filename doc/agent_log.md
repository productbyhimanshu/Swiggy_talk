# Swiggy Talk — Agent Log

> All agent actions, decisions, errors, and session events are recorded here.
> **Source of truth**: `doc/architecture.md` + `doc/rules.md`
> **Rules in effect**:
> - Always use `doc/` folder — do not use native Antigravity memory
> - Always make a separate folder for each phase's codebase

---

## Log format

Each entry follows this structure:

```
### [YYYY-MM-DD HH:MM] — <event type>
**Phase**: <phase number or N/A>
**Action**: <what was done>
**Result**: <outcome / status>
**Errors**: <any errors encountered, or "none">
**Notes**: <decisions made, edge cases, references>
```

---

## Session: 2026-05-22

### [2026-05-22 12:30] — SESSION START
**Phase**: N/A
**Action**: User requested reading `architecture.md` and creating phased `TODO.md`
**Result**: `architecture.md` was found empty on disk (unsaved editor buffer). User saved file.
**Errors**: `architecture.md` showed 0 bytes on disk; `rules.md` showed 0 bytes on disk
**Notes**: Files were open in editor but not saved. Resolved by user saving both files.

---

### [2026-05-22 12:34] — FILE READ: architecture.md
**Phase**: N/A
**Action**: Read full `doc/architecture.md` (1177 lines, 45708 bytes)
**Result**: Successfully read. Architecture v4.0 confirmed.
**Errors**: None
**Notes**: `rules.md` still 0 bytes at this point — incorporated when saved.

---

### [2026-05-22 12:36] — FILE CREATED: TODO.md (v1)
**Phase**: N/A
**Action**: Created initial `TODO.md` at project root (10 phases, no labels)
**Result**: File created at `/swiggy-talk/TODO.md`
**Errors**: None
**Notes**: First version — no task labels, no Phase 0, no conftest.py gate, basic structure.

---

### [2026-05-22 12:43] — FILE UPDATED: TODO.md (v2 — full rewrite)
**Phase**: N/A
**Action**: Full rewrite of `TODO.md` based on user review request
**Result**: File updated at `/swiggy-talk/TODO.md` (566 lines, 30790 bytes)
**Errors**: Artifact path error on first attempt (tried writing to project path as artifact — corrected)
**Notes**:
- Added Phase 0 (env + auth)
- Added task labels: `LOCAL` / `GEMINI` / `SWIGGY READ` / `SWIGGY WRITE`
- Added per-phase `✅ exit gate` test sections
- Added 12 edge-case / failure scenario tests in Phase 10
- Added manual sign-off checkpoint before Phase 11
- `place_food_order` hard-blocked until Phase 11
- `conftest.py` assertion added to kill test suite if `ORDER_ENABLED=true`
- Orchestrator (Phase 2) correctly positioned as top node above all 4 agents

---

### [2026-05-22 12:49] — FILE DELETED: Artifact TODO.md
**Phase**: N/A
**Action**: Deleted duplicate artifact copy at Antigravity brain path
**Result**: Removed. Only `/swiggy-talk/TODO.md` remains.
**Errors**: None
**Notes**: Artifact was created for user review; once approved and written to project, duplicate removed.

---

### [2026-05-22 13:22] — RULES UPDATED: rules.md
**Phase**: N/A
**Action**: User saved `doc/rules.md` with two rules
**Result**: Rules in effect from this point forward:
  1. Always use `doc/` folder — do not use native Antigravity memory
  2. Always make a separate folder per phase for codebases
**Errors**: None
**Notes**: All future files (logs, plans, scratch) go in `doc/`. Phase code goes in `phase-N/` folders.

---

### [2026-05-22 13:22] — FILE CREATED: doc/agent_log.md
**Phase**: N/A
**Action**: Created this log file in `doc/` per rules.md rule 1
**Result**: File created at `/swiggy-talk/doc/agent_log.md`
**Errors**: None
**Notes**: Will be updated on every future agent action, error, and decision.

---

### [2026-05-22 22:20] — BUG FIX: Intent Parser Schema Validation
**Phase**: 8/9
**Action**: Investigated and fixed "Unknown field for Schema: title/maximum/anyOf" from Gemini API. Appended missing GEMINI_API_KEY to `.env` file.
**Result**: Backend API updated to use a draconian schema stripper that keeps only primitive OpenAPI types, solving the strict Pydantic compatibility issue in the `gemini-2.0-flash-lite` SDK.
**Errors**: `Intent parse failed: Agent 1 failed after 3 attempts`
**Notes**:
- The user had `.env` open with the key but it wasn't saved to disk. Fixed by rewriting `.env`.
- `google.generativeai` throws errors on `anyOf`, `maximum`, `minimum`, `default`, and `title`. Stripped them recursively in `intent_parser.py`.

---

<!-- NEW ENTRIES GO BELOW THIS LINE -->

### [2026-06-09 20:08] — PHASE COMPLETE: Phase 9 — Cart API
**Phase**: 9
**Action**: Audited Phase 9 implementation; cleaned dead stub in `routes/cart.py`; marked `__init__.py` STATUS as `"complete"`; ran full test suite.
**Result**: 5/5 tests passed (`test_cart.py`) — 9.E1–9.E5 all green in 0.01s.
**Errors**: None
**Notes**:
- Real cart logic lives in `phase_09/router.py` (what assembler + tests use).
- `phase_09/routes/cart.py` was a dead stub — replaced with redirect comment.
- All Swiggy write tools (`update_food_cart`, `flush_food_cart`, `apply_food_coupon`) confirmed implemented in `phase_04/services/swiggy_read.py`.
- Budget guard (₹1000), single-restaurant flush, and optimistic rollback all verified.
- ⚠️ FutureWarning: `google.generativeai` deprecated — upgrade to `google.genai` needed (tracked for later).

---

### [2026-06-09 20:15] — PHASE COMPLETE: Phase 10 — Retries + Fallback Chain
**Phase**: 10
**Action**: Implemented `phase_10/utils/retries.py` and `phase_10/utils/fallbacks.py`; wrote test suites `test_retries.py` and `test_fallbacks.py`; fixed stdlib logging incompatibility (structlog-style kwargs → format strings).
**Result**: 16/16 tests passed in 0.01s.
**Errors**: Initial TypeError on `log.warning(key=val)` — stdlib logging doesn't accept extra keyword args. Fixed by switching to `"msg key=%s" % val` format strings.
**Notes**:
- `retries.py`: Standalone `retry_call()` coroutine — 3× exponential backoff, 4xx non-retryable, raises `RetryExhaustedError` after exhaustion.
- `fallbacks.py`: Full fallback chain per architecture §14 — covers swiggy_down, Gemini classify fail, Agent 1/3 failures, restaurant closed, COD coupon filter.
- `apply_fallback_chain(error, context)` is the orchestrator-level dispatcher keyed by `context["stage"]`.
- README updated: phases 9 and 10 marked Done.
- Next: **Phase 11 — APScheduler timing engine** (`scheduler.py` currently `raise NotImplementedError`).

---

### [2026-06-09 21:00] — PHASE COMPLETE: Phase 11 — Timing Scheduler
**Phase**: 11
**Action**: Implemented `services/scheduler.py` (timing engine + job store), `routes/schedule.py` (POST/DELETE /api/schedule), `tests/test_timing.py` (25 test cases).
**Result**: 25/25 tests passed in 0.02s. First-run green.
**Errors**: None
**Notes**:
- `calculate_order_time()`: `fire_at = delivery_target − eta_minutes − 5min_buffer`. Uses `parse_eta()` max-value parser from Phase 4.
- `order_now=True` when `fire_at` is ≤2 min away or already past.
- `warn_far_ahead=True` when delivery target is >4h from now.
- `pre_order_check()`: validates restaurant OPEN + cart non-empty + ETA hasn't spiked beyond window.
- `execute_scheduled_order()`: raises `OrderDisabledError` via `assert_orders_enabled()` — stub confirmed.
- `cancel_job()`: idempotent, marks `job.cancelled=True`, no auto-flush (caller decides UX).
- In-memory `_jobs` registry — no DB dependency in Phase 11.
- Schedule router wired into `assembler.py` (`POST /api/schedule`, `DELETE /api/schedule/{job_id}`).
- Phase 11 exit criteria: timing 100%, stub confirmed never places real order. ✅
- Next: **Phase 12 — Full eval suite gate**.



