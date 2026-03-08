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

## Local Postgres

Postgres is managed through:

```bash
docker compose -f driftshield/docker-compose.dev.yml up -d db
```

To stop it:

```bash
docker compose -f driftshield/docker-compose.dev.yml down
```
