# DriftShield CLI Tool Design

**Date:** 2025-02-13
**Phase:** 9 (CLI Tool)
**Status:** Approved

---

## Overview

A command-line interface for DriftShield that enables quick analysis of AI agent sessions, batch processing, and CI/pipeline integration. Built on the existing analysis pipeline (`analyze_session`) and parser infrastructure (`TranscriptParser` protocol).

---

## Command Structure

### Commands

| Command | Purpose | Phase |
|---------|---------|-------|
| `driftshield analyze <path>` | Analyse single file or directory | 9.1, 9.2 |
| `driftshield analyze --project` | Auto-discover sessions for current repo | 9.2 |
| `driftshield inspect <session> --node <n>` | Show details for specific node | 9.3 |
| `driftshield list [--project]` | List available sessions | 9.2 |

### Global Options

| Flag | Purpose |
|------|---------|
| `--verbose / -v` | Show full event table |
| `--json` | Output JSON instead of formatted text |
| `--quiet / -q` | Minimal output (for CI) |
| `--version` | Show version and exit |
| `--help` | Show help and exit |

### CI-Specific Options (on `analyze`)

| Flag | Purpose |
|------|---------|
| `--fail-on <risk,...>` | Exit 1 if specified risks detected |
| `--fail-threshold <n>` | Exit 1 if n or more flagged events |

### Parser Selection

| Flag | Purpose |
|------|---------|
| `--parser <name>` | Parser to use: `auto` (default), `claude_code` |

Auto-detection logic:
1. If path is under `~/.claude/projects/` → `claude_code`
2. If file extension is `.jsonl` → `claude_code`
3. Future: content sniffing for other formats
4. If cannot determine → error with hint to use `--parser`

---

## Output Formats

### Default Output (Summary + Inflection)

```
DriftShield Analysis
────────────────────
Session: 45b32921-0559-400d-8930-350d66ff0221
Events:  47
Flagged: 2

Risks Detected:
  - coverage_gap: 1
  - context_contamination: 1

Inflection Point:
  Event #23 : review_indemnity
  Type      : BRANCH
  Risk      : coverage_gap, assumption_mutation
  Input     : 4 subsections
  Output    : 3 referenced (missing: c)
```

### Verbose Output (`--verbose`)

Adds full event table:

```
Events:
┏━━━━┳━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┓
┃ #  ┃ Action            ┃ Type       ┃ Flags             ┃
┡━━━━╇━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━┩
│ 0  │ receive_document  │ TOOL_CALL  │                   │
│ 1  │ extract_clauses   │ TOOL_CALL  │                   │
│ ...│ ...               │ ...        │                   │
│ 23 │ review_indemnity  │ BRANCH     │ ⚠ coverage_gap    │
└────┴───────────────────┴────────────┴───────────────────┘
```

### JSON Output (`--json`)

```json
{
  "session_id": "45b32921-...",
  "total_events": 47,
  "flagged_events": 2,
  "risks": {
    "coverage_gap": 1,
    "context_contamination": 1
  },
  "inflection": {
    "event_index": 23,
    "action": "review_indemnity",
    "flags": ["coverage_gap", "assumption_mutation"]
  },
  "events": [...]
}
```

### Quiet Output (`--quiet`)

```
⚠ 2 risks detected
```

Or for CI failures:
```
FAIL: coverage_gap detected (exit 1)
```

---

## Project Auto-Discovery

### Discovery Logic

1. Get current working directory
2. Convert to Claude Code project path format: `/Users/foo/bar/repo` → `-Users-foo-bar-repo`
3. Look in `~/.claude/projects/<project-path>/` for `*.jsonl` files
4. Return list sorted by modification time (newest first)

### Edge Cases

| Situation | Behaviour |
|-----------|-----------|
| Not in a git repo | Search based on cwd anyway |
| No sessions found | Message: "No sessions found for this project" |
| Multiple projects match | Use exact match only |
| `~/.claude` doesn't exist | Error: "Claude Code sessions directory not found" |

### List Command Output

```
Sessions for: drift-shield-agentic
──────────────────────────────────
  1. 45b32921-0559-400d-8930-350d66ff0221  (2 hours ago, 47 events)
  2. c5bd21f2-e300-4b75-a217-85732dd5a14c  (yesterday, 123 events)
  3. 093ea201-56a4-419f-a7d2-500b3ddca024  (3 days ago, 89 events)

Use: driftshield analyze <session-id>
```

---

## Inspect Command

### Usage

```bash
driftshield inspect <session> --node <n>
driftshield inspect <session> --node <n> --path-to-root
```

### Session Resolution

`<session>` can be:
- Full path: `~/.claude/projects/.../abc123.jsonl`
- Session ID: `abc123` (resolved via project discovery)
- Index from list: `1` (most recent session)

### Default Output

```
Node #23: review_indemnity
──────────────────────────
Type:      BRANCH
Timestamp: 2025-02-13 10:03:42 UTC
Agent:     claude-3-opus

Inputs:
  clause: indemnification
  subsections: [a, b, c, d]
  full_text: "Supplier shall indemnify...(c) except where..."

Outputs:
  assessment: "Standard indemnification structure"
  referenced_subsections: [a, b, d]
  flag: false

Risk Flags:
  ⚠ coverage_gap
  ⚠ assumption_mutation

Parent: #22 (review_liability)
Children: #24 (generate_summary)
```

### Path to Root (`--path-to-root`)

```
Path to Root from Node #23
──────────────────────────
#23 review_indemnity   ⚠ coverage_gap
 ↑
#22 review_liability
 ↑
#21 extract_clauses
 ↑
#20 receive_document   (root)
```

---

## Module Structure

### New Files

```
src/driftshield/
├── cli/
│   ├── __init__.py
│   ├── main.py          # Typer app, entry point
│   ├── commands/
│   │   ├── __init__.py
│   │   ├── analyze.py   # analyze command
│   │   ├── inspect.py   # inspect command
│   │   └── list.py      # list command
│   ├── output.py        # Formatters (table, summary, JSON)
│   ├── discovery.py     # Project/session discovery logic
│   └── parsers.py       # Parser registry and auto-detection
```

### Dependencies

```toml
# pyproject.toml additions
dependencies = [
    # ... existing ...
    "typer>=0.9.0",
    "rich>=13.0.0",
]
```

### Entry Point

```toml
[project.scripts]
driftshield = "driftshield.cli.main:app"
```

---

## Phase Breakdown

| Phase | Scope | Deliverables |
|-------|-------|--------------|
| 9.1 | Single file analysis | `analyze <path>`, default + verbose + JSON output |
| 9.2 | Batch + discovery | `analyze --project`, `list`, session resolution |
| 9.3 | Inspection | `inspect` command with `--path-to-root` |
| 9.4 | CI integration | `--fail-on`, `--fail-threshold`, exit codes, `--quiet` |

Each phase builds on the previous, with TDD throughout.

---

## Example Usage

```bash
# Quick analysis of a session
driftshield analyze ~/.claude/projects/.../session.jsonl

# Verbose output with full event table
driftshield analyze session.jsonl --verbose

# Analyse all sessions in current project
driftshield analyze --project

# List available sessions
driftshield list --project

# CI mode: fail on coverage gaps
driftshield analyze session.jsonl --fail-on coverage_gap --json --quiet

# Drill into a specific node
driftshield inspect 45b32921 --node 23

# Show path from node to root
driftshield inspect 45b32921 --node 23 --path-to-root
```

---

## Help System

Typer provides automatic `--help` on all commands:

```bash
$ driftshield --help
$ driftshield analyze --help
$ driftshield inspect --help
```

Shell completion available via `driftshield --install-completion`.
