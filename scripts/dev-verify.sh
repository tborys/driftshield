#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/driftshield"
FRONTEND_DIR="$BACKEND_DIR/frontend"

log() {
  printf '\n[dev-verify] %s\n' "$1"
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

log "Ingest smoke tests"
cd "$BACKEND_DIR"
PYTHONPATH=src python3 -m pytest tests/api/test_ingest.py -q

log "Verification passed"
