# Logging & failure investigation

Swiggy Talk uses **structlog** with JSON output to **stdout** and **persistent files** under `logs/`.

## Architecture

```
Application code
       │
       ▼
  structlog (JSON processors)
       │
       ├──► stdout          (dev console)
       ├──► logs/swiggy-talk.log   (everything)
       └──► logs/errors.log        (warning+ only)
```

Implementation: [`backend/logging_setup.py`](../backend/logging_setup.py)

## Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `LOG_LEVEL` | `debug` | Minimum level (debug, info, warning, error) |
| `LOG_DIR` | `logs` | Directory for log files |
| `LOG_FILE_NAME` | `swiggy-talk.log` | Full audit trail |
| `LOG_ERRORS_FILE_NAME` | `errors.log` | Failure-focused file |
| `LOG_MAX_BYTES` | `10485760` | Rotate at 10 MB |
| `LOG_BACKUP_COUNT` | `5` | Keep 5 rotated backups |

`GET /health` returns resolved log paths under `"logs"`.

## Log format

Each line is a single JSON object:

```json
{
  "event": "swiggy_tool_call",
  "level": "info",
  "timestamp": "2026-05-22T10:15:30.123456Z",
  "tool": "get_addresses",
  "write": false
}
```

Common fields:

| Field | Meaning |
|-------|---------|
| `event` | Stable identifier for filtering (grep-friendly) |
| `level` | debug / info / warning / error |
| `timestamp` | ISO-8601 UTC |
| `latency_ms` | HTTP or pipeline duration |
| `exc_info` | Present on exceptions (stack trace) |

## Event catalogue (by area)

### Infrastructure (Phase 0+)

| Event | Level | When |
|-------|-------|------|
| `logging_configured` | info | App logging initialized |
| `app_start` | info | FastAPI lifespan start |
| `app_shutdown` | info | FastAPI shutdown |
| `http_request` | info | Successful HTTP request |
| `http_request_client_error` | warning | HTTP 4xx |
| `http_request_error` | error | HTTP 5xx |
| `http_request_failed` | error | Unhandled exception in handler |

### OAuth (Phase 0+)

| Event | Level | When |
|-------|-------|------|
| `oauth_authorize_url_built` | info | Login redirect prepared |
| `oauth_token_obtained` | info | Token exchange succeeded |
| `oauth_token_expired` | warning | Stored token past expiry |
| `oauth_login_failed` | warning | Missing client_id, etc. |
| `oauth_callback_error` | warning | Swiggy returned OAuth error |
| `oauth_token_exchange_failed` | warning | Code exchange failed |
| `oauth_callback_success` | info | OAuth complete |

### Swiggy API (Phase 0+)

| Event | Level | When |
|-------|-------|------|
| `swiggy_tool_call` | info | JSON-RPC tool invoked |

### Pipeline (Phase 2+)

| Event | Level | When |
|-------|-------|------|
| `pipeline_complete` | info | Full chat pipeline finished (route, latencies) |

*Future phases will extend this table in the corresponding phase doc.*

## Investigating failures

### Workflow

1. Note the time and endpoint (or user action).
2. `grep` `errors.log` around that window.
3. Pull surrounding lines from `swiggy-talk.log` for context.
4. Open the matching `phases/phase_XX/` module for that pipeline stage.

### Examples

```bash
# All errors today
grep '"level": "error"' logs/swiggy-talk.log

# OAuth problems
grep oauth_ logs/errors.log

# Slow HTTP (>500ms) — adjust threshold as needed
grep http_request logs/swiggy-talk.log | grep -E 'latency_ms": [5-9][0-9]{2,}'

# Order gate blocked (Phase 0+)
grep OrderDisabledError logs/errors.log
```

### pytest

Tests use a temporary log directory — see `backend/tests/test_logging.py`.
