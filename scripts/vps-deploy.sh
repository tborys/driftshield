#!/usr/bin/env bash
set -Eeuo pipefail

# Secure deployment script for DriftShield Agentic on VPS.
# Intended to run on the target server from repository root.

BRANCH="${BRANCH:-main}"
REMOTE="${REMOTE:-origin}"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
APP_DIR="${APP_DIR:-$PROJECT_ROOT/driftshield}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_ROOT/backups/db}"
MIN_FREE_KB="${MIN_FREE_KB:-1048576}" # 1GB default
ROLLBACK_ENABLED="${ROLLBACK_ENABLED:-true}"

log() {
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    log "ERROR: required command missing: $1"
    exit 1
  fi
}

CURRENT_COMMIT=""
TARGET_COMMIT=""
APP_PORT="8080"
DB_USER_LOCAL="drift"
DB_NAME_LOCAL="driftshield"
DEPLOY_STARTED="false"

rollback() {
  if [[ "$ROLLBACK_ENABLED" != "true" ]]; then
    log "Rollback disabled."
    return
  fi

  if [[ -z "$CURRENT_COMMIT" ]]; then
    log "No previous commit recorded; skipping rollback."
    return
  fi

  log "Rolling back to commit: $CURRENT_COMMIT"
  git -C "$PROJECT_ROOT" reset --hard "$CURRENT_COMMIT"

  (
    cd "$APP_DIR"
    docker compose -f "$COMPOSE_FILE" up -d --build --remove-orphans
  )

  local health_url="http://127.0.0.1:${APP_PORT}/api/health"
  for _ in $(seq 1 20); do
    if curl -fsS --max-time 5 "$health_url" >/dev/null; then
      log "Rollback health check passed: $health_url"
      return
    fi
    sleep 2
  done

  log "WARNING: rollback completed but health check failed at $health_url"
}

on_error() {
  local exit_code="$?"
  local line_no="$1"
  log "ERROR at line ${line_no}; exit code ${exit_code}."

  if [[ "$DEPLOY_STARTED" == "true" ]]; then
    rollback
  fi

  exit "$exit_code"
}
trap 'on_error ${LINENO}' ERR

require_cmd git
require_cmd docker
require_cmd curl

is_placeholder_secret() {
  local value="${1:-}"
  [[ -z "$value" \
    || "$value" == "changeme" \
    || "$value" == "your-api-key-here" \
    || "$value" == "replace-with-a-long-random-api-key" \
    || "$value" == "replace-with-a-strong-db-password" \
    || "$value" == "dev-api-key" \
    || "$value" == "dev-key" ]]
}

validate_positive_integer() {
  local name="$1"
  local value="$2"
  if ! [[ "$value" =~ ^[0-9]+$ ]] || [[ "$value" -le 0 ]]; then
    log "ERROR: ${name} must be a positive integer (got: ${value})"
    exit 1
  fi
}

if [[ ! -d "$PROJECT_ROOT/.git" ]]; then
  log "ERROR: PROJECT_ROOT does not look like a git checkout: $PROJECT_ROOT"
  exit 1
fi

if [[ ! -f "$APP_DIR/$COMPOSE_FILE" ]]; then
  log "ERROR: compose file not found: $APP_DIR/$COMPOSE_FILE"
  exit 1
fi

log "=== DriftShield deploy start ==="
log "Project root: $PROJECT_ROOT"
log "App dir: $APP_DIR"
log "Branch: $BRANCH"

# Pre-deploy checks
AVAILABLE_KB=$(df -Pk "$PROJECT_ROOT" | awk 'NR==2 {print $4}')
if [[ -z "$AVAILABLE_KB" || "$AVAILABLE_KB" -lt "$MIN_FREE_KB" ]]; then
  log "ERROR: insufficient disk free space (available=${AVAILABLE_KB:-unknown}KB, required=${MIN_FREE_KB}KB)"
  exit 1
fi

(
  cd "$APP_DIR"
  docker compose -f "$COMPOSE_FILE" version >/dev/null
)

CURRENT_COMMIT=$(git -C "$PROJECT_ROOT" rev-parse HEAD)
git -C "$PROJECT_ROOT" fetch "$REMOTE" "$BRANCH"
TARGET_COMMIT=$(git -C "$PROJECT_ROOT" rev-parse "$REMOTE/$BRANCH")

log "Current commit: $CURRENT_COMMIT"
log "Target commit:  $TARGET_COMMIT"

if [[ ! -f "$APP_DIR/.env" ]]; then
  log "ERROR: missing server-side env file: $APP_DIR/.env"
  exit 1
fi

# shellcheck disable=SC1091
set -a && source "$APP_DIR/.env" && set +a

APP_PORT="${PORT:-8080}"
DB_USER_LOCAL="${DB_USER:-drift}"
DB_NAME_LOCAL="${DB_NAME:-driftshield}"
ENVIRONMENT_VALUE="${ENVIRONMENT:-production}"
MAX_REQUEST_BYTES_VALUE="${MAX_REQUEST_BYTES:-26214400}"

validate_positive_integer "PORT" "$APP_PORT"
validate_positive_integer "MAX_REQUEST_BYTES" "$MAX_REQUEST_BYTES_VALUE"

if [[ "$ENVIRONMENT_VALUE" != "production" ]]; then
  log "ERROR: ENVIRONMENT must be set to production on the dogfood VPS (got: ${ENVIRONMENT_VALUE})"
  exit 1
fi

if is_placeholder_secret "${API_KEY:-}"; then
  log "ERROR: API_KEY is missing or still using a placeholder/dev value."
  exit 1
fi

if [[ "${DB_PASSWORD:-}" == "drift" ]]; then
  log "ERROR: DB_PASSWORD must not use the default value on the dogfood VPS."
  exit 1
fi

if is_placeholder_secret "${DB_PASSWORD:-}"; then
  log "ERROR: DB_PASSWORD is missing or still using a placeholder/dev value."
  exit 1
fi

log "Environment checks OK: ENVIRONMENT=${ENVIRONMENT_VALUE}, PORT=${APP_PORT}, MAX_REQUEST_BYTES=${MAX_REQUEST_BYTES_VALUE}"

# Snapshot/backup step
mkdir -p "$BACKUP_DIR"
if (
  cd "$APP_DIR"
  docker compose -f "$COMPOSE_FILE" ps --services --filter status=running | grep -q '^db$'
); then
  TS=$(date -u +%Y%m%dT%H%M%SZ)
  BACKUP_FILE="$BACKUP_DIR/predeploy-${TS}.sql.gz"
  log "Creating DB backup: $BACKUP_FILE"
  (
    cd "$APP_DIR"
    docker compose -f "$COMPOSE_FILE" exec -T db \
      sh -c "pg_dump -U '$DB_USER_LOCAL' '$DB_NAME_LOCAL'" | gzip > "$BACKUP_FILE"
  )
else
  log "DB container not running; skipping pg_dump backup step."
fi

(
  cd "$APP_DIR"
  docker compose -f "$COMPOSE_FILE" config -q
)

# Deploy
DEPLOY_STARTED="true"

git -C "$PROJECT_ROOT" checkout -q "$BRANCH"
git -C "$PROJECT_ROOT" reset --hard "$TARGET_COMMIT"

(
  cd "$APP_DIR"
  docker compose -f "$COMPOSE_FILE" pull --ignore-pull-failures
  docker compose -f "$COMPOSE_FILE" build --pull
  docker compose -f "$COMPOSE_FILE" up -d --remove-orphans
)

# Post-deploy verification
(
  cd "$APP_DIR"
  docker compose -f "$COMPOSE_FILE" ps
)

HEALTH_URL="http://127.0.0.1:${APP_PORT}/api/health"
for _ in $(seq 1 30); do
  if curl -fsS --max-time 5 "$HEALTH_URL" >/dev/null; then
    break
  fi
  sleep 2
done
curl -fsS --max-time 5 "$HEALTH_URL" >/dev/null
log "Health endpoint OK: $HEALTH_URL"

if command -v tailscale >/dev/null 2>&1; then
  TAIL_IP=$(tailscale ip -4 2>/dev/null | head -n1 || true)
  if [[ -n "$TAIL_IP" ]]; then
    TAIL_HEALTH_URL="http://${TAIL_IP}:${APP_PORT}/api/health"
    curl -fsS --max-time 5 "$TAIL_HEALTH_URL" >/dev/null
    log "Tailnet health URL OK: $TAIL_HEALTH_URL"
  else
    log "WARNING: Tailscale present but no IPv4 tailnet address found."
  fi
fi

if command -v ufw >/dev/null 2>&1; then
  UFW_STATUS=$(ufw status 2>/dev/null || true)
  if echo "$UFW_STATUS" | grep -Eq "^${APP_PORT}(/tcp)?\s+ALLOW\s+Anywhere"; then
    log "ERROR: UFW exposes app port ${APP_PORT} publicly (Anywhere)."
    exit 1
  fi
fi

log "=== DriftShield deploy finished successfully ==="
log "Deployed commit: $TARGET_COMMIT"
