# DriftShield – Claude Code Guide

@sessions/CLAUDE.sessions.md

This file provides instructions for Claude Code when working in the DriftShield codebase.

## Project Overview

DriftShield is an AI Decision Forensics & Continuous Risk Infrastructure platform. It ingests AI session transcripts, analyses them for risk signals, and presents findings via a web UI and CLI.

**Monorepo layout:**

```
driftshield/          # Core product (backend + frontend + CLI + tests)
marketing/            # Next.js marketing site
skills/               # Claude Code agent skills
docs/                 # Architecture plans, handoffs, VPS reference
scripts/              # Dev utilities (setup, verify, deploy)
.claude/commands/     # Slash commands (/issue, /ship, /browser-check)
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12+, FastAPI, SQLAlchemy 2.0 (async), Alembic, Pydantic 2.5+ |
| CLI | Typer + Rich |
| Frontend | React 19, TypeScript ~5.9, Vite, Tailwind CSS 4, TanStack React Query |
| UI Components | Radix UI / Shadcn, @xyflow/react (graph viz), Lucide icons |
| Database | PostgreSQL 16 (prod), SQLite in-memory (tests) |
| Testing | pytest + pytest-asyncio (backend), Playwright (e2e), Vitest (frontend unit) |
| Linting | Ruff (Python, line-length=100), ESLint 9 flat config (TypeScript) |
| Type checking | MyPy strict (Python), TypeScript strict (frontend) |
| Package mgmt | uv / pip (Python), npm (frontend) |
| Infra | Docker multi-stage, docker-compose, GitHub Actions CI |

## Implementation Workflow

- For issue or PR driven work, read the linked issue or PR and the relevant code paths before making changes.
- Before implementing, write a short spec and plan in your working notes or user update, then continue into implementation without waiting for extra human approval unless there is a real blocker or a risky irreversible decision.
- Prefer end-to-end execution. Do not stop at analysis, planning, or partial scaffolding when the task can reasonably be completed in one pass.
- If a change touches frontend or UI behaviour, include browser-based verification as part of completion, not just static or unit checks.
- When browser testing is needed, use the real browser tooling available in the environment and report what flow was exercised.

## Verification Commands

Run these before shipping any change. Stop on first failure.

```bash
# Backend tests
cd driftshield && uv run --extra dev pytest tests -q

# Frontend build (type-checks + bundles)
cd driftshield/frontend && npm run build

# E2E tests (if frontend files changed)
cd driftshield/frontend && npx playwright test --reporter=list

# Full regression script
./scripts/dev-verify.sh
```

## Backend Patterns

### Project structure

```
driftshield/src/driftshield/
├── api/            # FastAPI routes, schemas, auth, middleware
│   ├── routes/     # One module per resource (health, ingest, sessions, reports, connectors)
│   ├── app.py      # App factory – mounts routes + static SPA
│   ├── auth.py     # X-API-Key security dependency
│   ├── security.py # RequestSizeLimitMiddleware
│   └── schemas.py  # Pydantic response models
├── cli/            # Typer commands
│   ├── main.py     # Entry point, command registration
│   └── commands/   # One module per subcommand
├── db/             # Database layer
│   ├── models.py   # SQLAlchemy ORM (UUID PKs, timezone-aware DateTime)
│   ├── persistence.py  # Data access functions
│   ├── engine.py   # Engine/session factory
│   └── migrations/ # Alembic versions
├── core/           # Domain logic
│   ├── models.py   # Domain dataclasses
│   ├── graph/      # Graph analysis
│   ├── signatures/ # Risk signature detection
│   └── analysis/   # Analysis engine
├── parsers/        # Transcript format parsers (protocol.py defines interface)
└── reports/        # Jinja2 report templates
```

### Conventions

- **Naming**: `snake_case` for files, functions, variables. `PascalCase` for classes.
- **Routes**: Group under `APIRouter`, register in `app.py`. Prefix with `/api/`.
- **Auth**: Use `Depends(require_api_key)` on protected routes. Unsafe default keys are rejected in production.
- **Models**: SQLAlchemy declarative base. UUID primary keys. All timestamps are timezone-aware (`DateTime(timezone=True)`).
- **Schemas**: Pydantic `BaseModel` for request/response. Use `Field()` with defaults and descriptions.
- **Error handling**: Raise `HTTPException` with specific status codes and descriptive `detail`. Handle `IntegrityError` for duplicate detection.
- **Config**: Environment variables via `os.environ` or `pydantic-settings`. See `.env.example` for required vars.
- **DB sessions**: Injected via FastAPI dependency injection. Explicit `commit()` / `rollback()` in route handlers.
- **Line length**: 100 characters (enforced by Ruff).
- **Type checking**: MyPy strict mode. Add type annotations to all new code.

### Adding a new API endpoint

1. Create or extend route module in `api/routes/`.
2. Add Pydantic schemas in `api/schemas.py` (or a colocated file for large schemas).
3. Register the router in `api/app.py`.
4. Write tests in `tests/api/test_<resource>.py` using the existing `client` / `db_session` fixtures.
5. If schema changes are needed, create an Alembic migration: `cd driftshield && alembic revision --autogenerate -m "description"`.

### Testing (backend)

- Framework: `pytest` with `pytest-asyncio` (auto mode).
- Location: `driftshield/tests/` mirroring `src/` structure.
- DB fixture: In-memory SQLite with `StaticPool`. Use `monkeypatch` for env vars.
- Run: `cd driftshield && uv run --extra dev pytest tests -q`
- Dogfood corpus: Golden-test expectations live in `tests/parsers/dogfood_corpus_expectations.json`.

## Frontend Patterns

### Project structure

```
driftshield/frontend/src/
├── pages/          # Page-level components (one per route)
├── components/
│   ├── layout/     # AppShell, Header
│   ├── investigation/  # Graph viz (LineageGraph, NodeInspector)
│   ├── sessions/   # Session list, filters
│   ├── reports/    # Report display
│   ├── validation/ # Analyst feedback UI
│   └── ui/         # Shadcn primitives (button, card, dialog, etc.)
├── api/            # React Query hooks + typed fetch client
│   ├── client.ts   # apiFetch() with API key injection
│   └── sessions.ts # useSessions, useSession, useSessionGraph, etc.
├── types/          # TypeScript interfaces (session.ts, graph.ts, validation.ts)
├── lib/            # Utility functions
├── App.tsx         # Router + QueryClientProvider
└── main.tsx        # React root
```

### Conventions

- **Naming**: `camelCase` for files, functions, variables. `PascalCase` for components and types/interfaces.
- **State**: TanStack React Query for all server state. No Redux/Zustand.
- **Query keys**: Array format – `['sessions', page, filters]`, `['session', id]`.
- **API calls**: Always go through `apiFetch()` in `api/client.ts` (injects `X-API-Key` header).
- **Styling**: Tailwind utility classes. Use `cn()` (clsx + tailwind-merge) for conditional classes.
- **Components**: Functional components only. Use TypeScript interfaces for props.
- **Routing**: React Router v7 with `<Outlet>` for nested layouts.
- **Icons**: Lucide React. Do not introduce other icon libraries.
- **Path aliases**: `@/*` maps to `./src/*` (configured in tsconfig).
- **Strict mode**: TypeScript strict enabled. No `any` types.

### Adding a new page

1. Create page component in `pages/`.
2. Add route in `App.tsx`.
3. Create React Query hooks in `api/` with typed response interfaces in `types/`.
4. Use existing Shadcn components from `components/ui/` for layout and controls.

## Database & Migrations

- **ORM**: SQLAlchemy 2.0 declarative. Models in `db/models.py`.
- **Migrations**: Alembic in `driftshield/db/migrations/`.
- **Unique constraints**: `transcript_hash + parser_version` on ingest for idempotency.
- **Creating migrations**: `cd driftshield && alembic revision --autogenerate -m "description"` then review the generated file.
- **Running migrations**: `cd driftshield && alembic upgrade head`.

## Docker & Deployment

- **Dockerfile**: Multi-stage (Node.js builds frontend → Python 3.12-slim serves app).
- **Production**: `docker-compose.yml` – app on port 8080, PostgreSQL 16 with health checks.
- **Development**: `docker-compose.dev.yml` – Postgres only, app runs locally with `uvicorn --reload`.
- **Deploy**: `scripts/vps-deploy.sh` with rollback support. CI via `.github/workflows/deploy-vps.yml` (manual, main only).

## CI/CD

GitHub Actions (`.github/workflows/ci.yml`):
1. **Backend tests** – Python 3.12, `pytest tests -q`
2. **Frontend build** – Node 20, `npm run build`
3. **Frontend e2e** – Playwright (conditional, skips if no test files)

Triggered on: PR and push to `main`.

## Environment Variables

Key variables (see `driftshield/.env.example`):

| Variable | Purpose |
|----------|---------|
| `ENVIRONMENT` | `development` or `production` |
| `API_KEY` | Backend auth key (unsafe defaults rejected in prod) |
| `DATABASE_URL` | PostgreSQL connection string |
| `MAX_REQUEST_BYTES` | Request size limit (default 25MB) |
| `VITE_API_KEY` | Frontend API key (injected at build time) |

## Handoffs

- When preparing a prompt for another agent, make it autonomous by default.
- Tell the agent to inspect the issue and codebase first, produce a concrete spec and plan, then implement, verify, and summarise the result without waiting for a human in the loop.

## OpenClaw / Contributor VPS

When working with the Contributor Telegram bot or the Cloud VPS, read `docs/openclaw-vps-reference.md` for SSH access, server layout, Docker commands, and current configuration state.

## Slash Commands

- `/issue <number>` – Fetch a GitHub issue, read relevant code, propose a TDD implementation plan.
- `/ship` – Run backend tests → frontend build → e2e tests → generate PR description.
- `/browser-check` – Run Playwright health check against current frontend changes.

## Automated PR Review

Claude reviews every PR via `.github/workflows/claude-review.yml`. The review runs on `opened`, `synchronize` and `reopened` events. You can also tag `@claude` in a PR comment to trigger a review.

### Review Priorities (ordered)

1. **Hardcoded secrets** or credentials in source, config or test files
2. **Missing error handling** on async operations, API calls or DB queries
3. **Client vs server component misuse** (marketing site uses Next.js 15 App Router)
4. **Missing loading/error states** in React components that fetch data
5. **Type safety regressions**: `any` usage, missing return types, untyped props
6. **Accessibility**: missing alt text, unlabelled form controls, keyboard nav gaps
7. **Test coverage**: new functions without tests, untested edge cases
8. **Bundle size**: unnecessary imports, missing tree shaking, large dependencies added without justification

### Code Style Rules (for reviewers)

- TypeScript strict mode, no `any` types
- Named exports preferred over default exports
- Server components by default in the marketing site, `'use client'` only when needed
- Tailwind for styling, no inline style objects
- Max 150 lines per component file (split if larger)
- Conventional commits (`feat:`, `fix:`, `chore:`, `docs:`, `test:`)
- One logical change per PR

## Common Pitfalls

- **Timezone**: All DB timestamps must be timezone-aware. Use `DateTime(timezone=True)` in models and `datetime.now(timezone.utc)` in Python code.
- **Ingest idempotency**: Transcripts are deduplicated by `(transcript_hash, parser_version)`. Don't bypass this constraint.
- **API key in tests**: Use `monkeypatch.setenv("API_KEY", ...)` in test fixtures, not hardcoded values.
- **Frontend env vars**: Vite inlines `VITE_*` vars at build time. Changing them requires a rebuild.
- **Static file serving**: The FastAPI app serves the built frontend as a SPA with catch-all routing. API routes must be registered before the SPA fallback.
