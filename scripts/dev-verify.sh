#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/driftshield"
FRONTEND_DIR="$BACKEND_DIR/frontend"

log() {
  printf '\n[dev-verify] %s\n' "$1"
}

cli_cmd() {
  if command -v driftshield >/dev/null 2>&1; then
    driftshield "$@"
  else
    PYTHONPATH=src python3 -m driftshield.cli.main "$@"
  fi
}

if [ -f "$BACKEND_DIR/.venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "$BACKEND_DIR/.venv/bin/activate"
else
  echo "[dev-verify] No backend venv found; using system python3 environment"
fi

log "Backend regression tests"
cd "$BACKEND_DIR"
PYTHONPATH=src python3 -m pytest -q

log "Frontend checks (production build)"
cd "$FRONTEND_DIR"
npm run build

log "Quickstart sample report smoke test"
cd "$BACKEND_DIR"
REPORT_OUTPUT="$(mktemp)"
cli_cmd report tests/fixtures/transcripts/sample_claude_code_session.jsonl \
  --type summary \
  --output "$REPORT_OUTPUT"
grep -q "Forensic Analysis Report" "$REPORT_OUTPUT"
rm -f "$REPORT_OUTPUT"

log "Ingest smoke tests"
cd "$BACKEND_DIR"
PYTHONPATH=src python3 -m pytest tests/api/test_ingest.py -q

log "Verification passed"
