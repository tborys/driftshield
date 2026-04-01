#!/usr/bin/env bash
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: ./scripts/issue-pickup.sh <issue-number-or-url> [owner/repo]" >&2
  exit 1
fi

ISSUE_INPUT="$1"
REPO_INPUT="${2:-}"

if ! command -v gh >/dev/null 2>&1; then
  echo "[issue-pickup] Missing required command: gh" >&2
  exit 1
fi

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$REPO_ROOT" ]; then
  echo "[issue-pickup] Must be run from inside a git repository" >&2
  exit 1
fi
cd "$REPO_ROOT"

REPO_NAME="${REPO_INPUT:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"
ISSUE_NUMBER="$ISSUE_INPUT"

if [[ "$ISSUE_INPUT" == https://github.com/*/issues/* ]]; then
  REPO_NAME="$(printf '%s' "$ISSUE_INPUT" | sed -E 's#https://github.com/([^/]+/[^/]+)/issues/([0-9]+).*#\1#')"
  ISSUE_NUMBER="$(printf '%s' "$ISSUE_INPUT" | sed -E 's#https://github.com/[^/]+/[^/]+/issues/([0-9]+).*#\1#')"
fi

CURRENT_TOKEN="$(gh auth token)"
PROJECT_OWNER="demouser"
PROJECT_NUMBER="4"

CURRENT_TOKEN="$CURRENT_TOKEN" \
AUTOMATION_TOKEN="$CURRENT_TOKEN" \
REPO="$REPO_NAME" \
EVENT_NAME="workflow_dispatch" \
ISSUE_NUMBER="$ISSUE_NUMBER" \
ISSUE_REPO="$REPO_NAME" \
PROJECT_OWNER="$PROJECT_OWNER" \
PROJECT_NUMBER="$PROJECT_NUMBER" \
python3 .github/scripts/issue_start_sync.py

echo "[issue-pickup] Moved $REPO_NAME#$ISSUE_NUMBER to In Progress (if a project item exists)."
