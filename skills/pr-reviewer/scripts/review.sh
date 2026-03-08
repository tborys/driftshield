#!/usr/bin/env bash
set -euo pipefail

# PR Reviewer Script
# Usage: review.sh [pr-number]
# If pr-number is provided, reviews that PR's diff.
# If omitted, reviews the current branch diff against main/master.

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$REPO_ROOT"

CRITICAL_COUNT=0
WARN_COUNT=0
INFO_COUNT=0

report_critical() { echo "[CRITICAL] $1"; CRITICAL_COUNT=$((CRITICAL_COUNT + 1)); }
report_warn()     { echo "[WARN] $1"; WARN_COUNT=$((WARN_COUNT + 1)); }
report_info()     { echo "[INFO] $1"; INFO_COUNT=$((INFO_COUNT + 1)); }
report_pass()     { echo "[PASS] $1"; }

# Determine the base branch
BASE_BRANCH="main"
if ! git rev-parse --verify "origin/$BASE_BRANCH" &>/dev/null; then
    BASE_BRANCH="master"
    if ! git rev-parse --verify "origin/$BASE_BRANCH" &>/dev/null; then
        echo "Error: Could not find origin/main or origin/master"
        exit 1
    fi
fi

# Get the diff
if [ "${1:-}" != "" ]; then
    PR_NUMBER="$1"
    echo "== PR Review Report =="
    echo "Reviewing PR #$PR_NUMBER"
    # Fetch the PR ref if available
    git fetch origin "pull/$PR_NUMBER/head:pr-$PR_NUMBER" 2>/dev/null || true
    if git rev-parse --verify "pr-$PR_NUMBER" &>/dev/null; then
        DIFF=$(git diff "origin/$BASE_BRANCH...pr-$PR_NUMBER")
        DIFF_STAT=$(git diff --stat "origin/$BASE_BRANCH...pr-$PR_NUMBER")
        DIFF_NUMSTAT=$(git diff --numstat "origin/$BASE_BRANCH...pr-$PR_NUMBER")
    else
        # Fallback: diff current branch
        DIFF=$(git diff "origin/$BASE_BRANCH...HEAD")
        DIFF_STAT=$(git diff --stat "origin/$BASE_BRANCH...HEAD")
        DIFF_NUMSTAT=$(git diff --numstat "origin/$BASE_BRANCH...HEAD")
    fi
else
    echo "== PR Review Report =="
    echo "Reviewing current branch against $BASE_BRANCH"
    DIFF=$(git diff "origin/$BASE_BRANCH...HEAD")
    DIFF_STAT=$(git diff --stat "origin/$BASE_BRANCH...HEAD")
    DIFF_NUMSTAT=$(git diff --numstat "origin/$BASE_BRANCH...HEAD")
fi

# Count files changed
FILES_CHANGED=$(echo "$DIFF_NUMSTAT" | grep -c '.' || echo 0)
INSERTIONS=$(echo "$DIFF_NUMSTAT" | awk '{s+=$1} END {print s+0}')
DELETIONS=$(echo "$DIFF_NUMSTAT" | awk '{s+=$2} END {print s+0}')

echo "Files changed: $FILES_CHANGED"
echo "Insertions: +$INSERTIONS, Deletions: -$DELETIONS"
echo ""

if [ -z "$DIFF" ]; then
    echo "No changes detected."
    exit 0
fi

# --- Check 1: Merge conflict markers ---
# Build pattern dynamically to avoid self-matching when this script is in the diff
CONFLICT_PAT="^\\+.*($(printf '<%.0s' {1..7})|$(printf '=%.0s' {1..7})|$(printf '>%.0s' {1..7}))"
if echo "$DIFF" | grep -qE "$CONFLICT_PAT"; then
    CONFLICTS=$(echo "$DIFF" | grep -cE "$CONFLICT_PAT" || echo 0)
    report_critical "Merge conflict markers found ($CONFLICTS occurrences)"
else
    report_pass "No merge conflict markers found"
fi

# --- Check 2: Security - hardcoded secrets ---
SECRET_PATTERNS='(api[_-]?key|api[_-]?secret|password|passwd|secret[_-]?key|access[_-]?token|auth[_-]?token|private[_-]?key)\s*[=:]\s*["\x27][A-Za-z0-9+/=_-]{8,}'
SECRET_HITS=$(echo "$DIFF" | grep -nE "^\+.*$SECRET_PATTERNS" | grep -v '^\+\+\+' | head -10 || true)
if [ -n "$SECRET_HITS" ]; then
    while IFS= read -r line; do
        report_warn "Security: possible hardcoded secret - ${line:0:120}"
    done <<< "$SECRET_HITS"
else
    report_pass "No obvious hardcoded secrets detected"
fi

# --- Check 3: Debug statements ---
DEBUG_PATTERNS='console\.(log|debug|warn|error)\(|print\(|debugger;|binding\.pry|import pdb|pdb\.set_trace'
DEBUG_HITS=$(echo "$DIFF" | grep -nE "^\+.*($DEBUG_PATTERNS)" | grep -v '^\+\+\+' | grep -v '#.*noqa' | head -10 || true)
if [ -n "$DEBUG_HITS" ]; then
    COUNT=$(echo "$DEBUG_HITS" | wc -l)
    report_warn "Debug statements found ($COUNT occurrences)"
else
    report_pass "No debug statements detected"
fi

# --- Check 4: Large file additions ---
LARGE_FILES=$(echo "$DIFF_NUMSTAT" | awk '$1 > 500 {print $3 " (+" $1 " lines)"}' || true)
if [ -n "$LARGE_FILES" ]; then
    while IFS= read -r line; do
        report_warn "Large file addition: $line"
    done <<< "$LARGE_FILES"
else
    report_pass "No excessively large files added"
fi

# --- Check 5: Test coverage signal ---
CHANGED_FILES=$(echo "$DIFF_NUMSTAT" | awk '{print $3}')
SRC_CHANGED=$(echo "$CHANGED_FILES" | { grep -E '\.(py|ts|tsx|js|jsx)$' || true; } | { grep -vcE '(test_|_test\.|\.test\.|\.spec\.|/tests/)' || echo 0; } | tail -1)
TEST_CHANGED=$(echo "$CHANGED_FILES" | { grep -ciE '(test_|_test\.|\.test\.|\.spec\.|/tests/)' || echo 0; } | tail -1)
if [ "$SRC_CHANGED" -gt 0 ] && [ "$TEST_CHANGED" -eq 0 ]; then
    report_info "No test files modified (source files changed: $SRC_CHANGED)"
elif [ "$TEST_CHANGED" -gt 0 ]; then
    report_pass "Test files included in changes ($TEST_CHANGED test files)"
fi

# --- Check 6: Dependency changes ---
DEP_FILES=$(echo "$CHANGED_FILES" | grep -E '(package\.json|package-lock\.json|pyproject\.toml|requirements.*\.txt|Cargo\.toml|go\.mod|Gemfile)' || true)
if [ -n "$DEP_FILES" ]; then
    while IFS= read -r line; do
        report_info "Dependency file changed: $line"
    done <<< "$DEP_FILES"
fi

# --- Check 7: TODO/FIXME markers ---
TODO_HITS=$(echo "$DIFF" | grep -nE '^\+.*(TODO|FIXME|HACK|XXX)' | grep -v '^\+\+\+' | head -5 || true)
if [ -n "$TODO_HITS" ]; then
    COUNT=$(echo "$TODO_HITS" | wc -l)
    report_info "New TODO/FIXME markers added ($COUNT)"
fi

# --- Summary ---
echo ""
echo "Summary: $CRITICAL_COUNT critical, $WARN_COUNT warnings, $INFO_COUNT info"

if [ "$CRITICAL_COUNT" -gt 0 ]; then
    exit 1
fi
exit 0
