# Swiggy Talk

Conversational AI food ordering — chat-first assistant on real Swiggy Food APIs.

## Code layout (phase folders)

All implementation code lives under **`phases/`** — one folder per build phase:

```
phases/
  phase_00/     # Done — OAuth, Swiggy API, logging, order guard
  phase_01/     # Done — session state, /api/session, address resolve
  phase_02/     # Done — orchestrator routing, POST /api/classify
  phase_03/     # Done — Agent 1 (Intent parser)
  phase_04/     # Done — Read tools & Filter gates
  phase_05/     # Done — Agent 3 (Scorer + Gemini Rerank)
  phase_06/     # Done — Agent 4 (Persona Formatter) & Templates
  phase_07/     # Done — SSE Streaming + /api/chat
  ...
  phase_13/     # Real orders (last)
  assembler.py  # Wires completed phases into one FastAPI app

backend/
  main.py       # Entry: uvicorn backend.main:app
  requirements.txt
```

Check each folder’s `__init__.py` for `PHASE` and `STATUS`. Implement inside that phase’s folder only.

## Phase 0 — Quick start

### 1. Backend

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example ../.env
```

### 2. Swiggy OAuth

1. [mcp.swiggy.com/access](https://mcp.swiggy.com/access)
2. Redirect URI: `http://localhost:8000/auth/callback`
3. `ORDER_ENABLED=false` in `.env`

### 3. Run API

```bash
# repo root, venv active
uvicorn backend.main:app --reload --port 8000
```

[http://localhost:8000/auth/swiggy/login](http://localhost:8000/auth/swiggy/login)

### 4. Smoke test

```bash
python scripts/swiggy_smoke.py
```

### 5. Tests

```bash
pytest phases/phase_00/tests phases/phase_01/tests -v
```

### Phase 1 — Session API

```bash
# Create session
curl -X POST http://localhost:8000/api/session

# Resolve Swiggy address (requires OAuth)
curl -X POST http://localhost:8000/api/session/{session_id}/resolve-address

# Classify a message (Phase 2)
curl -X POST http://localhost:8000/api/classify \
  -H "Content-Type: application/json" \
  -d '{"session_id":"<id>","message":"add butter chicken"}'
```

## Logs

- `logs/swiggy-talk.log` — full JSON log
- `logs/errors.log` — warnings & errors only

See [doc/logging.md](doc/logging.md) and [logs/README.md](logs/README.md).

## Design docs

- [doc/architecture.md](doc/architecture.md)
- [TODO.md](TODO.md)
