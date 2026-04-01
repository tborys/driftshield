#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/driftshield"
FRONTEND_DIR="$BACKEND_DIR/frontend"

log() {
  printf '\n[dev-setup] %s\n' "$1"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "[dev-setup] Missing required command: $1" >&2
    exit 1
  fi
}

require_cmd python3
require_cmd npm

PYTHON_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)'; then
  :
else
  echo "[dev-setup] Python 3.12+ required by driftshield/pyproject.toml (found $PYTHON_VERSION)" >&2
  exit 1
fi

log "Preparing environment files"
[ -f "$BACKEND_DIR/.env" ] || cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
[ -f "$FRONTEND_DIR/.env" ] || cp "$FRONTEND_DIR/.env.example" "$FRONTEND_DIR/.env"

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  log "Starting local Postgres"
  docker compose -f "$BACKEND_DIR/docker-compose.dev.yml" up -d db
else
  log "Docker unavailable - skipping Postgres start"
  echo "Run this later when Docker is available:"
  echo "  docker compose -f driftshield/docker-compose.dev.yml up -d db"
fi

log "Setting up Python environment and backend dependencies"
if [ ! -f "$BACKEND_DIR/.venv/bin/activate" ]; then
  rm -rf "$BACKEND_DIR/.venv"
  if ! python3 -m venv "$BACKEND_DIR/.venv"; then
    echo "[dev-setup] Failed to create virtual environment at $BACKEND_DIR/.venv" >&2
    echo "[dev-setup] Ensure your Python installation includes venv support, then rerun ./scripts/dev-setup.sh" >&2
    exit 1
  fi
fi

if [ -f "$BACKEND_DIR/.venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "$BACKEND_DIR/.venv/bin/activate"
  if ! python -m pip --version >/dev/null 2>&1; then
    log "Bootstrapping pip inside virtualenv"
    if ! python -m ensurepip --upgrade >/dev/null 2>&1; then
      echo "[dev-setup] Failed to bootstrap pip inside $BACKEND_DIR/.venv" >&2
      echo "[dev-setup] Ensure your Python installation includes ensurepip support, then rerun ./scripts/dev-setup.sh" >&2
      exit 1
    fi
  fi
  python -m pip install --upgrade pip
  python -m pip install -e "$BACKEND_DIR[dev]"
fi

log "Installing frontend dependencies"
cd "$FRONTEND_DIR"
npm ci --include=dev

log "Setup complete"
echo "Run verification: ./scripts/dev-verify.sh"
