#!/bin/sh
set -eu

MODE="${1:-local}"
TRANSCRIPT_PATH="${CLAUDE_TRANSCRIPT_PATH:-${TRANSCRIPT_PATH:-}}"

if [ -z "$TRANSCRIPT_PATH" ]; then
  echo "CLAUDE_TRANSCRIPT_PATH (or TRANSCRIPT_PATH) is required" >&2
  exit 1
fi

case "$MODE" in
  local)
    exec driftshield ingest --path "$TRANSCRIPT_PATH"
    ;;
  vps)
    API_URL="${DRIFTSHIELD_API_URL:-}"
    API_KEY="${DRIFTSHIELD_API_KEY:-${API_KEY:-}}"

    if [ -z "$API_URL" ]; then
      echo "DRIFTSHIELD_API_URL is required for vps mode" >&2
      exit 1
    fi

    if [ -z "$API_KEY" ]; then
      echo "DRIFTSHIELD_API_KEY (or API_KEY) is required for vps mode" >&2
      exit 1
    fi

    exec curl -sS -X POST \
      -H "X-API-Key: $API_KEY" \
      -F "format=claude_code" \
      -F "file=@$TRANSCRIPT_PATH;type=application/jsonl" \
      "${API_URL%/}/api/ingest"
    ;;
  *)
    echo "Usage: $0 [local|vps]" >&2
    exit 1
    ;;
esac
