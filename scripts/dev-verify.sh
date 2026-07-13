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

log "Public OSS boundary check"
cd "$ROOT_DIR"
./scripts/check-public-scope.sh

log "Backend regression tests"
cd "$BACKEND_DIR"
PYTHONPATH=src python3 -m pytest -q

log "Frontend checks (production build)"
cd "$FRONTEND_DIR"
npm run build

log "Frontend e2e tests (Playwright)"
cd "$FRONTEND_DIR"
if ls tests/e2e/*.spec.ts >/dev/null 2>&1; then
  # Intentional gap vs CI: CI runs `playwright install chromium --with-deps`,
  # which apt-installs OS packages on the GitHub-hosted runner. Locally we
  # only fetch the browser binary and leave system libraries to the
  # developer's machine, since --with-deps assumes an apt-based, root-capable
  # runner that a local dev box may not be.
  npx playwright install chromium
  npx playwright test --reporter=list
else
  echo "[dev-verify] No Playwright e2e tests found; skipping (mirrors CI frontend-e2e skip)"
fi

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
