#!/usr/bin/env bash
# Tail failures-only log (warnings and errors)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="${LOG_DIR:-$ROOT/logs}"
LOG_FILE="${LOG_ERRORS_FILE_NAME:-errors.log}"
PATH_TO="$LOG_DIR/$LOG_FILE"

if [[ ! -f "$PATH_TO" ]]; then
  echo "Errors log not found: $PATH_TO"
  echo "Start the API first: uvicorn backend.main:app --reload"
  exit 1
fi

tail -f "$PATH_TO"
