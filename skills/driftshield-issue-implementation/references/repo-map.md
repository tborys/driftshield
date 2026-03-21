# DriftShield Repo Map

## Contents

- Project-level entry points
- Backend runtime and data flow
- Frontend runtime
- Cross-layer seams to inspect
- Validation entry points

## Project-level entry points

- `AGENTS.md`
  Repo-specific workflow rules. Read this first for issue-driven work.
- `README.md`
  Local setup and verification shortcuts, including `./scripts/dev-setup.sh` and `./scripts/dev-verify.sh`.
- `driftshield/pyproject.toml`
  Backend packaging, pytest, and ruff configuration.
- `driftshield/frontend/package.json`
  Frontend build and lint commands.

## Backend runtime and data flow

- `driftshield/src/driftshield/api/app.py`
  FastAPI app wiring, middleware, and SPA static serving.
- `driftshield/src/driftshield/api/routes/`
  Route handlers. Read with `driftshield/src/driftshield/api/schemas.py` so contracts stay aligned.
- `driftshield/src/driftshield/db/`
  SQLAlchemy models, services, persistence, engine setup, and Alembic migrations.
- `driftshield/src/driftshield/core/`
  Analysis pipeline, heuristics, graph building, recurrence, and other domain logic.
- `driftshield/src/driftshield/parsers/`
  Transcript parsers for ingest sources.
- `driftshield/src/driftshield/cli/`
  Typer commands and local workflows.
- `driftshield/src/driftshield/connectors/`
  Connector discovery and local source handling.
- `driftshield/src/driftshield/reports/`
  Report builders, exporters, models, and templates.

## Frontend runtime

- `driftshield/frontend/src/App.tsx`
  Route composition and app shell.
- `driftshield/frontend/src/pages/`
  Page-level workflows and query orchestration.
- `driftshield/frontend/src/api/`
  API client and React Query hooks.
- `driftshield/frontend/src/types/`
  Frontend mirrors of backend API shapes.
- `driftshield/frontend/src/components/`
  Shared UI primitives and feature components.

## Cross-layer seams to inspect

- DB model changes often require migration, service, API schema, and test updates.
- API schema changes often require route, frontend type, hook, and page updates.
- Ingest and connector changes often require updates across parser, persistence, API, CLI, and tests.
- Frontend behavior changes often require backend contract checks plus browser verification.
- CLI changes should stay semantically aligned with API behavior and env var names.

## Validation entry points

- Full backend suite:
  `cd driftshield && uv run pytest`
- Backend lint:
  `cd driftshield && uv run ruff check src tests`
- Frontend build:
  `cd driftshield/frontend && npm run build`
- Frontend lint:
  `cd driftshield/frontend && npm run lint`
- Repo-level shortcut:
  `./scripts/dev-verify.sh`
- UI behavior check:
  Run a real browser flow whenever frontend behavior, filters, forms, routing, or status surfaces change.
