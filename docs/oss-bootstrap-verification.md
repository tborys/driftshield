# OSS Bootstrap and Verification

This document defines the public-safe bootstrap path for contributors using a
clean clone of this repository.

All public documentation refers to the product/package as `DriftShield`.

## Prerequisites

- Python 3.12+
- Node.js + npm
- Optional: Docker (for local Postgres)

## Setup

From repository root:

```bash
./scripts/dev-setup.sh
```

Expected outcomes:
- `driftshield/.env` exists
- `driftshield/frontend/.env` exists
- backend virtualenv exists at `driftshield/.venv`
- backend dependencies installed
- frontend dependencies installed
- bundled sample transcript can be analyzed locally with the installed `driftshield` CLI

If Docker is unavailable, setup continues and prints the command for starting
Postgres later. The no-Docker path is still useful for local sample analysis and
report generation, but API ingest and the dashboard require the local Postgres
service plus the backend environment exported from `driftshield/.env`.

## First Useful Result

From `driftshield/` after setup:

```bash
source .venv/bin/activate
driftshield report tests/fixtures/transcripts/sample_claude_code_session.jsonl --type summary
```

This is the shortest supported path from clean clone to an investigation-grade
result in the OSS repo.

## Verify

From repository root:

```bash
./scripts/dev-verify.sh
```

This command validates:
- backend regression tests
- frontend production build
- bundled sample report generation
- ingest API smoke tests

## OSS boundary checks

When updating docs or workflows, avoid presenting these as bundled OSS
capabilities:
- recurrence
- signatures
- graveyard
- enterprise/governance capabilities

For commercial or internal planning materials, keep them out of this public OSS
surface.
