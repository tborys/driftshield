# DriftShield Repo Map

## Contents

- Backend runtime and data flow
- Frontend runtime
- High-risk review seams
- Validation entry points

## Backend runtime and data flow

- `driftshield/src/driftshield/api/app.py`
  Wires FastAPI routes, middleware, and SPA static serving.
- `driftshield/src/driftshield/api/routes/`
  HTTP route handlers. Read alongside `driftshield/src/driftshield/api/schemas.py` for response and request contracts.
- `driftshield/src/driftshield/db/`
  SQLAlchemy models, connector services, persistence logic, engine setup, and Alembic migrations under `db/migrations/versions/`.
- `driftshield/src/driftshield/core/`
  Analysis, heuristics, graph building, recurrence, and other domain logic.
- `driftshield/src/driftshield/parsers/`
  Transcript parsers. Review here when ingest format behavior changes.
- `driftshield/src/driftshield/cli/`
  Typer commands and local workflows. Review CLI and API parity when a user-facing backend feature changes.
- `driftshield/src/driftshield/reports/`
  Report builders, models, exporters, and templates.

## Frontend runtime

- `driftshield/frontend/src/App.tsx`
  Top-level routing and page composition.
- `driftshield/frontend/src/pages/`
  Top-level user flows and query orchestration.
- `driftshield/frontend/src/api/`
  Client and React Query hooks. Read this when backend response shapes or query semantics change.
- `driftshield/frontend/src/types/`
  Frontend mirrors of backend API response shapes. Review for drift whenever `api/schemas.py` changes.
- `driftshield/frontend/src/components/`
  Shared UI and page-specific components. `@/components/ui/*` contains shared primitives; feature components sit beside pages.
- `driftshield/frontend/package.json`
  Build and lint entry points. Frontend currently relies on `build` and `lint`; browser verification is still required for UI behavior changes.

## High-risk review seams

- API schema changes without frontend type or hook updates.
- DB model changes without matching Alembic migration updates.
- Migration changes that work on Postgres but not SQLite-based tests, or vice versa.
- Persistence changes that break ingest dedupe, recurrence mapping, graph rebuilds, or provenance.
- CLI changes that drift from API semantics, status codes, env var names, or JSON output contracts.
- Timestamp serialization or parsing changes that break UTC assumptions.
- Connector and ingest changes that need updates across discovery, consent, persistence, API, CLI, and tests.
- Frontend query/filter changes that update pages but not hooks, types, or empty/error/loading states.
- Public-tree references to private sibling repos or internal planning repos.

## Validation entry points

- OSS boundary check: `./scripts/check-public-scope.sh`
- Backend full suite: `cd driftshield && uv run pytest`
- Backend lint: `cd driftshield && uv run ruff check src tests`
- Targeted backend review:
  - API: `driftshield/tests/api/`
  - DB and persistence: `driftshield/tests/db/`
  - CLI: `driftshield/tests/cli/`
  - Core logic: `driftshield/tests/core/`
  - Parsers and integration: `driftshield/tests/parsers/`, `driftshield/tests/integration/`
- Frontend checks:
  - `cd driftshield/frontend && npm run build`
  - `cd driftshield/frontend && npm run lint`
- UI behavior verification:
  Run a real browser flow when frontend behavior, routing, filters, forms, or status surfaces change.
