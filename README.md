# DriftShield Agentic

Local development bootstrap and verification workflow for DriftShield.

## One-command setup

From repo root:

```bash
./scripts/dev-setup.sh
```

What it does:
- creates local env files from examples (backend + frontend)
- starts Postgres via `driftshield/docker-compose.dev.yml` when Docker is available
- creates `driftshield/.venv` and installs backend deps (`-e [dev]`), exiting with guidance if `venv` support is unavailable
- installs frontend deps with `npm ci --include=dev`

## One-command verification

From repo root:

```bash
./scripts/dev-verify.sh
```

Verification covers:
- backend regression tests (`PYTHONPATH=src python3 -m pytest -q`)
- frontend checks (`npm run build`)
- ingest smoke tests (`PYTHONPATH=src python3 -m pytest tests/api/test_ingest.py -q`)

## Environment files

`./scripts/dev-setup.sh` creates these if missing:

- `driftshield/.env` (from `driftshield/.env.example`)
- `driftshield/frontend/.env` (from `driftshield/frontend/.env.example`)

Defaults are safe for local development:

Backend (`driftshield/.env`):
- `API_KEY=dev-api-key`
- `DATABASE_URL=postgresql://drift:drift@localhost:5432/driftshield`

Frontend (`driftshield/frontend/.env`):
- `VITE_API_KEY=dev-api-key`

## Transcript ingest CLI

From `driftshield/` you can upload a transcript directly to the local or remote ingest API:

```bash
DRIFTSHIELD_API_URL=http://localhost:8000 \
DRIFTSHIELD_API_KEY=dev-api-key \
PYTHONPATH=src python3 -m driftshield.cli.main ingest --path tests/fixtures/transcripts/sample_claude_code_session.jsonl
```

Discovery shortcuts reuse the Claude project session lookup already used by the CLI:

```bash
# latest session for the current Claude project
DRIFTSHIELD_API_KEY=dev-api-key PYTHONPATH=src python3 -m driftshield.cli.main ingest --project
DRIFTSHIELD_API_KEY=dev-api-key PYTHONPATH=src python3 -m driftshield.cli.main ingest --latest
```

A thin Dealer hook wrapper is available at `scripts/dealer-hook.sh`:

```bash
# local DriftShield CLI
CLAUDE_TRANSCRIPT_PATH=/path/to/session.jsonl scripts/dealer-hook.sh local

# direct VPS ingest
CLAUDE_TRANSCRIPT_PATH=/path/to/session.jsonl \
DRIFTSHIELD_API_URL=https://driftshield.example \
DRIFTSHIELD_API_KEY=prod-api-key \
scripts/dealer-hook.sh vps
```

## Local Postgres

Postgres is managed through:

```bash
docker compose -f driftshield/docker-compose.dev.yml up -d db
```

To stop it:

```bash
docker compose -f driftshield/docker-compose.dev.yml down
```
