#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
APP_DIR="${APP_DIR:-$PROJECT_ROOT/driftshield}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
APP_PORT="${PORT:-8080}"
API_HEALTH_PATH="${API_HEALTH_PATH:-/api/health}"

if [[ -f "$APP_DIR/.env" ]]; then
  # shellcheck disable=SC1091
  set -a && source "$APP_DIR/.env" && set +a
  APP_PORT="${PORT:-$APP_PORT}"
fi

echo "=== DriftShield access verification ==="

echo "[1/4] Container status"
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
echo "[4/4] Public exposure check"
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
echo "=== Verification complete ==="
