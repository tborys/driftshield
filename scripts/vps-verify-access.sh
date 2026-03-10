#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
APP_DIR="${APP_DIR:-$PROJECT_ROOT/driftshield}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
APP_PORT="${PORT:-8080}"
API_HEALTH_PATH="${API_HEALTH_PATH:-/api/health}"
MAX_REQUEST_BYTES="${MAX_REQUEST_BYTES:-26214400}"
ENVIRONMENT_VALUE="${ENVIRONMENT:-unknown}"

if [[ -f "$APP_DIR/.env" ]]; then
  # shellcheck disable=SC1091
  set -a && source "$APP_DIR/.env" && set +a
  APP_PORT="${PORT:-$APP_PORT}"
  MAX_REQUEST_BYTES="${MAX_REQUEST_BYTES:-26214400}"
  ENVIRONMENT_VALUE="${ENVIRONMENT:-unknown}"
fi

echo "=== DriftShield access verification ==="
echo "Environment: ${ENVIRONMENT_VALUE}"
echo "Port: ${APP_PORT}"
echo "Max request bytes: ${MAX_REQUEST_BYTES}"

echo "[1/5] Container status"
(
  cd "$APP_DIR"
  docker compose -f "$COMPOSE_FILE" ps
)

echo ""
echo "[2/4] Local health check"
LOCAL_HEALTH_URL="http://127.0.0.1:${APP_PORT}${API_HEALTH_PATH}"
curl -fsS --max-time 5 "$LOCAL_HEALTH_URL" | sed 's/^/  /'

echo ""
echo "[3/4] Tailnet endpoint check"
if command -v tailscale >/dev/null 2>&1; then
  TAIL_IP=$(tailscale ip -4 2>/dev/null | head -n1 || true)
  if [[ -n "$TAIL_IP" ]]; then
    TAIL_HEALTH_URL="http://${TAIL_IP}:${APP_PORT}${API_HEALTH_PATH}"
    curl -fsS --max-time 5 "$TAIL_HEALTH_URL" | sed 's/^/  /'
    echo "  Tailnet URL: http://${TAIL_IP}:${APP_PORT}/sessions"
  else
    echo "  Tailscale running but no IPv4 tailnet IP detected."
  fi
else
  echo "  Tailscale not installed on this host."
fi

echo ""
echo "[4/5] Public exposure check"
if command -v ufw >/dev/null 2>&1; then
  UFW_STATUS=$(ufw status 2>/dev/null || true)
  if echo "$UFW_STATUS" | grep -Eq "^${APP_PORT}(/tcp)?\s+ALLOW\s+Anywhere"; then
    echo "  WARNING: port ${APP_PORT} appears publicly allowed in UFW."
  else
    echo "  OK: no obvious UFW public allow rule for port ${APP_PORT}."
  fi
else
  echo "  UFW not available; skipped."
fi

echo ""
echo "[5/5] Listener check"
if command -v ss >/dev/null 2>&1; then
  ss -ltnp | grep -E ":${APP_PORT}\\b" | sed 's/^/  /' || echo "  No listening socket found for port ${APP_PORT}."
else
  echo "  ss not available; skipped."
fi

echo ""
echo "=== Verification complete ==="
