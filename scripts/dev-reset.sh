#!/usr/bin/env bash
set -euo pipefail

# dev-reset.sh — Stop conflicting local dev processes, restart OpenClaw
# browser on VPS via the browser-health skill, and print port status.
# Run from your Mac. Requires SSH access to cloud.

PORTS="8080 4173"
VPS="cloud"
CONTAINER="openclaw-openclaw-gateway-1"
HEALTH_SCRIPT="bash /home/node/.openclaw/workspace/skills/browser-health/scripts/check.sh"

echo "=== DriftShield Dev Reset ==="
echo ""

# 1. Kill local conflicting processes
echo "[1/3] Killing local processes on ports $PORTS..."
for port in $PORTS; do
  pids=$(lsof -ti ":$port" 2>/dev/null || true)
  if [ -n "$pids" ]; then
    echo "  Port $port: killing PIDs $pids"
    echo "$pids" | xargs kill -9 2>/dev/null || true
  else
    echo "  Port $port: clear"
  fi
done
echo ""

# 2. Run browser health check on VPS (auto-heals if needed)
echo "[2/3] Running browser health check on VPS..."
health_output=$(ssh "$VPS" "docker exec $CONTAINER $HEALTH_SCRIPT" 2>&1) || true
echo "$health_output"
echo ""

# 3. Print status
echo "[3/3] Status"
echo ""

echo "--- Local Ports ---"
for port in $PORTS; do
  proc=$(lsof -i ":$port" 2>/dev/null | tail -1 || true)
  if [ -n "$proc" ]; then
    echo "  Port $port: IN USE — $proc"
  else
    echo "  Port $port: free (ready)"
  fi
done
echo ""

echo "=== Reset complete ==="
