# Application logs

All runtime logs are written here as **JSON lines** (one JSON object per line). Files are gitignored; only this README is committed.

## Files

| File | Contents |
|------|----------|
| `swiggy-talk.log` | **Full log** — every event (info, debug, warnings, errors) |
| `errors.log` | **Failures only** — `warning`, `error`, `critical` (fast triage) |
| `swiggy-talk.log.1` … | Rotated backups when the active file exceeds `LOG_MAX_BYTES` (default 10 MB) |

Configure paths via `.env`:

```env
LOG_DIR=logs
LOG_FILE_NAME=swiggy-talk.log
LOG_ERRORS_FILE_NAME=errors.log
```

## Quick commands

```bash
# Live tail (all events)
./scripts/logs_tail.sh

# Failures only
./scripts/logs_errors.sh

# Search Swiggy API failures
grep swiggy_tool_call logs/swiggy-talk.log | grep error

# Search HTTP 5xx
grep http_request_error logs/errors.log

# Pretty-print one line (requires jq)
tail -1 logs/swiggy-talk.log | jq .
```

## When debugging

1. Reproduce the issue with the API running (`uvicorn backend.main:app --reload`).
2. Open `logs/errors.log` first — warnings and errors land here automatically.
3. Use `logs/swiggy-talk.log` for full context (latency, route, tool name).
4. See [doc/logging.md](../doc/logging.md) for event names by phase.

## Privacy

Logs may contain session IDs, tool names, and error messages. **Do not commit** log files or share them without redacting tokens.
