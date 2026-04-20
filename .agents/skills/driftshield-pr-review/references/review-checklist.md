# DriftShield Review Checklist

## Contents

- Review output expectations
- Cross-layer invariants
- Backend and data checks
- Frontend checks
- OSS boundary checks
- Verification matrix

## Review output expectations

- Lead with findings, not summaries.
- Order findings by severity and user impact.
- Include precise file references.
- Prefer bugs, regressions, missing verification, and boundary leaks over style commentary.
- Treat missing verification in the PR body as relevant when the changed area clearly required it.
- If no findings are found, say so explicitly and call out residual risks or coverage gaps.

## Cross-layer invariants

- Confirm the implementation matches the linked issue, PR description, and acceptance criteria.
- Confirm the PR workflow state still matches repo rules: linked issue remains `In Progress` until merge, and project/checklist state is not advanced early.
- Confirm backend schema changes are reflected in:
  - `api/schemas.py`
  - route handlers
  - frontend `src/types/*`
  - frontend query hooks in `src/api/*`
  - UI consumers in `src/pages/*` or `src/components/*`
- Confirm DB changes are reflected in:
  - SQLAlchemy models
  - Alembic migrations
  - persistence or service logic
  - tests
- Confirm user-facing backend features remain aligned across API and CLI if both expose the same concept.
- Confirm timestamps stay timezone-aware and serialized consistently in UTC-sensitive flows.

## Backend and data checks

### FastAPI and schemas

- Check auth, dependency usage, status codes, and error handling.
- Check request and response fields for backward-compatibility or expected breakage.
- Check for missing schema updates when a route payload changes.

### SQLAlchemy and migrations

- Check nullability, defaults, indexes, uniqueness, and foreign keys.
- Check that every persistent model change has a migration when required.
- Check migration safety and compatibility with test environments using SQLite.
- Check downgrade paths if the repo expects them to remain usable.

### Persistence, ingest, and connectors

- Check dedupe and idempotency when transcript, connector, or persistence code changes.
- Check upsert and rebuild behavior when existing sessions or nodes can be rewritten.
- Check provenance fields, source paths, session identifiers, and parser version handling.
- Check transaction boundaries, rollback paths, and duplicate-write race handling.
- Check connector status surfaces for API, CLI, and persistence consistency.

### CLI

- Check exit codes, JSON output stability, env var names, and option semantics.
- Check that CLI messaging does not silently drift from backend behavior.

## Frontend checks

- Check `src/types/*` whenever backend response shapes or enum-like strings change.
- Check React Query hooks and cache keys when route params, filters, or fetch shapes change.
- Check loading, error, and empty states for pages that changed.
- Check navigation and routing when `App.tsx`, route params, or page composition changes.
- Check filter and status pages for hidden coupling between frontend defaults and backend query behavior.
- Check that UI changes preserve existing design system patterns unless the PR intentionally changes them.
- Require real browser verification for UI behavior changes, especially for routing, filters, forms, and async status surfaces.

## OSS boundary checks

- The public repo should not reference private sibling repos in tracked public files.
- The public repo should not link to internal cross-repo planning docs or private sibling paths.
- Treat any such reference as a boundary leak unless it is a clearly isolated local-only developer artifact that is not intended to ship or publish.

## Verification matrix

- Boundary-only change:
  Run `./scripts/check-public-scope.sh`.
- API route or schema only:
  Run targeted API tests plus any adjacent DB tests.
- Model, migration, or persistence changes:
  Run targeted DB and API tests; widen to full `uv run pytest` if the change touches shared persistence paths.
- CLI changes:
  Run targeted CLI tests and the backend tests that exercise the same feature.
- Parser, ingest, or connector changes:
  Run parser, DB, API, and CLI tests around ingest and connector flows.
- Frontend-only structural change:
  Run `npm run build`, `npm run lint`, and a browser flow for the affected page.
- Full-stack change:
  Run `./scripts/check-public-scope.sh`, targeted backend tests, frontend build/lint, and a browser flow covering the changed UX.
