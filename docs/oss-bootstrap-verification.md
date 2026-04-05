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

If Docker is unavailable, setup continues and prints the command for starting
Postgres later.

## Verify

From repository root:

```bash
./scripts/dev-verify.sh
```

This command validates:
- backend regression tests
- frontend production build
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
