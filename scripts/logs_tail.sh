#!/usr/bin/env bash
# Tail full application log (JSON lines)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="${LOG_DIR:-$ROOT/logs}"
LOG_FILE="${LOG_FILE_NAME:-swiggy-talk.log}"
PATH_TO="$LOG_DIR/$LOG_FILE"

if [[ ! -f "$PATH_TO" ]]; then
  echo "Log file not found: $PATH_TO"
  echo "Start the API first: uvicorn backend.main:app --reload"
  exit 1
fi

tail -f "$PATH_TO"
