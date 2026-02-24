#!/usr/bin/env bash
set -euo pipefail

# browser-health/scripts/check.sh
# Checks OpenClaw browser health and auto-heals if unhealthy.
# Exit 0 = healthy or healed. Exit 1 = heal failed.

CDP_PORT=18800
CDP_URL="http://127.0.0.1:${CDP_PORT}/json/version"
OPENCLAW="node /app/dist/index.js"
MAX_PROCS=20
MAX_CPU=15

json_out() {
  local healthy="$1" cdp="$2" procs="$3" action="$4" reason="${5:-}" prev="${6:-}" err="${7:-}"
  printf '{\n'
  printf '  "healthy": %s,\n' "$healthy"
  printf '  "cdp_responding": %s,\n' "$cdp"
  printf '  "process_count": %s,\n' "$procs"
  printf '  "action": "%s"' "$action"
  [ -n "$reason" ] && printf ',\n  "reason": "%s"' "$reason"
  [ -n "$prev" ] && printf ',\n  "previous_process_count": %s' "$prev"
  [ -n "$err" ] && printf ',\n  "error": "%s"' "$err"
  printf '\n}\n'
}

# Count chrome-headless-shell processes
count_procs() {
  ps aux | grep '[c]hrome-headless-shell' | wc -l | tr -d ' '
}

# Check if any renderer uses more than MAX_CPU percent
check_cpu_leak() {
  ps aux | grep '[c]hrome-headless-shell' | awk -v max="$MAX_CPU" '$3 > max {found=1} END {exit !found}' 2>/dev/null
}

# Test CDP endpoint
check_cdp() {
  local resp
  resp=$(curl -s --max-time 5 "$CDP_URL" 2>/dev/null || true)
  echo "$resp" | grep -q '"Browser"'
}

# Auto-heal: stop, kill, restart, verify
do_heal() {
  $OPENCLAW browser stop >/dev/null 2>&1 || true
  sleep 1
  pkill -9 -f 'chrome-headless-shell' 2>/dev/null || true
  sleep 2
  $OPENCLAW browser start >/dev/null 2>&1 || true
  sleep 3
  check_cdp
}

# --- Main ---

proc_count=$(count_procs)
unhealthy_reason=""

# Check 1: CDP responsiveness
if ! check_cdp; then
  unhealthy_reason="cdp_timeout"
fi

# Check 2: Process leak (high CPU)
if [ -z "$unhealthy_reason" ] && check_cpu_leak; then
  unhealthy_reason="renderer_cpu_leak"
fi

# Check 3: Too many processes
if [ -z "$unhealthy_reason" ] && [ "$proc_count" -gt "$MAX_PROCS" ]; then
  unhealthy_reason="process_count_exceeded"
fi

# Check 4: Status desync (processes exist but browser reports not running)
if [ -z "$unhealthy_reason" ] && [ "$proc_count" -gt 0 ]; then
  status_running=$($OPENCLAW browser status 2>/dev/null | grep '^running:' | awk '{print $2}')
  if [ "$status_running" = "false" ]; then
    unhealthy_reason="status_desync"
  fi
fi

# Healthy path
if [ -z "$unhealthy_reason" ]; then
  json_out "true" "true" "$proc_count" "none"
  exit 0
fi

# Unhealthy: attempt auto-heal
prev_count="$proc_count"

if do_heal; then
  new_count=$(count_procs)
  json_out "true" "true" "$new_count" "auto-healed" "$unhealthy_reason" "$prev_count"
  exit 0
else
  new_count=$(count_procs)
  json_out "false" "false" "$new_count" "heal-failed" "${unhealthy_reason}_after_restart" "" "CDP did not respond after restart"
  exit 1
fi
