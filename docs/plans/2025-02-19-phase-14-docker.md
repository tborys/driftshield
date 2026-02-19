# Phase 14: Docker Deployment — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a Docker Compose deployment for self-hosted DriftShield with a multi-stage Dockerfile (React + FastAPI in one container) and PostgreSQL.

**Architecture:** Single app container serves both API and React static files. PostgreSQL in a separate container. Entrypoint script handles DB readiness check and Alembic migrations.

**Tech Stack:** Docker, Docker Compose, PostgreSQL 16, Uvicorn, Alembic

**Design doc:** `docs/plans/2025-02-19-phases-10-14-design.md` (Phase 14 section)

**Prerequisite:** Phases 10-13 complete

---

## Task 14.1: Multi-stage Dockerfile

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`

**Step 1: Create .dockerignore**

```
# .dockerignore
.git
.venv
__pycache__
*.pyc
node_modules
.data
docs
tests
*.md
.ruff_cache
.mypy_cache
.pytest_cache
.worktrees
sessions
.claude
```

**Step 2: Create multi-stage Dockerfile**

```dockerfile
# Dockerfile

# Stage 1: Build React frontend
FROM node:20-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python application
FROM python:3.12-slim AS production
WORKDIR /app

# Install system dependencies for psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

# Copy application code
COPY src/ ./src/
COPY alembic.ini ./

# Copy built frontend
COPY --from=frontend-build /app/frontend/dist ./static

# Copy entrypoint
COPY docker/entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

# Environment defaults
ENV HOST=0.0.0.0
ENV PORT=8080
ENV WORKERS=1
ENV LOG_LEVEL=info

EXPOSE 8080

ENTRYPOINT ["./entrypoint.sh"]
```

**Step 3: Verify Dockerfile syntax**

```bash
cd .worktrees/driftshield-v1/driftshield
docker build --check .
```

**Step 4: Commit**

```bash
git add Dockerfile .dockerignore
git commit -m "feat(docker): add multi-stage Dockerfile for React + FastAPI"
```

---

## Task 14.2: Entrypoint Script

**Files:**
- Create: `docker/entrypoint.sh`

**Step 1: Create entrypoint**

```bash
#!/bin/bash
set -e

echo "DriftShield starting..."

# Wait for PostgreSQL to be ready
echo "Waiting for database..."
until pg_isready -h "${DB_HOST:-db}" -p "${DB_PORT:-5432}" -U "${DB_USER:-drift}" -q; do
  echo "Database not ready, retrying in 2 seconds..."
  sleep 2
done
echo "Database is ready."

# Run Alembic migrations
echo "Running database migrations..."
python -m alembic upgrade head
echo "Migrations complete."

# Start Uvicorn
echo "Starting DriftShield on ${HOST:-0.0.0.0}:${PORT:-8080}..."
exec uvicorn driftshield.api.server:app \
  --host "${HOST:-0.0.0.0}" \
  --port "${PORT:-8080}" \
  --workers "${WORKERS:-1}" \
  --log-level "${LOG_LEVEL:-info}"
```

**Step 2: Commit**

```bash
mkdir -p docker
git add docker/entrypoint.sh
git commit -m "feat(docker): add entrypoint script with DB wait and migrations"
```

---

## Task 14.3: Static File Serving in FastAPI

**Files:**
- Modify: `src/driftshield/api/app.py`

**Step 1: Add static file serving**

Update `create_app()` in `src/driftshield/api/app.py` to serve React static files:

```python
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse


def create_app() -> FastAPI:
    app = FastAPI(
        title="DriftShield",
        description="AI Decision Forensics API",
        version="0.1.0",
    )

    # API routes
    app.include_router(health_router)
    app.include_router(ingest_router)
    app.include_router(sessions_router)
    app.include_router(reports_router)

    # Serve React static files in production
    static_dir = Path(__file__).parent.parent.parent.parent / "static"
    if static_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(static_dir / "assets")), name="assets")

        @app.get("/{path:path}")
        async def serve_spa(path: str):
            """Serve React SPA. All non-API routes fall through to index.html."""
            file_path = static_dir / path
            if file_path.exists() and file_path.is_file():
                return FileResponse(str(file_path))
            return FileResponse(str(static_dir / "index.html"))

    return app
```

Note: The `/assets` mount must come before the catch-all SPA route. API routes registered with `include_router` take precedence over the catch-all because they're matched first.

**Step 2: Verify existing tests still pass**

```bash
cd .worktrees/driftshield-v1/driftshield
python -m pytest tests/api/ -v
```

Expected: All API tests pass (static dir doesn't exist in test environment, so SPA route is not mounted).

**Step 3: Commit**

```bash
git add src/driftshield/api/app.py
git commit -m "feat(api): add static file serving for React SPA in production"
```

---

## Task 14.4: Docker Compose

**Files:**
- Create: `docker-compose.yml`
- Create: `docker/.env.example`

**Step 1: Create docker-compose.yml**

```yaml
# docker-compose.yml
services:
  app:
    build: .
    ports:
      - "${PORT:-8080}:8080"
    environment:
      DATABASE_URL: postgresql://${DB_USER:-drift}:${DB_PASSWORD:-drift}@db:5432/${DB_NAME:-driftshield}
      DB_HOST: db
      DB_PORT: 5432
      DB_USER: ${DB_USER:-drift}
      API_KEY: ${API_KEY:?API_KEY is required}
      LOG_LEVEL: ${LOG_LEVEL:-info}
      WORKERS: ${WORKERS:-1}
    depends_on:
      db:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/api/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: ${DB_USER:-drift}
      POSTGRES_PASSWORD: ${DB_PASSWORD:-drift}
      POSTGRES_DB: ${DB_NAME:-driftshield}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER:-drift}"]
      interval: 10s
      timeout: 5s
      retries: 5
    profiles:
      - ""
      - dev

volumes:
  postgres_data:
```

**Step 2: Create .env.example**

```bash
# docker/.env.example

# Required
API_KEY=your-api-key-here

# Database (defaults work with bundled PostgreSQL)
DB_USER=drift
DB_PASSWORD=drift
DB_NAME=driftshield

# Application
PORT=8080
LOG_LEVEL=info
WORKERS=1
```

**Step 3: Commit**

```bash
git add docker-compose.yml docker/.env.example
git commit -m "feat(docker): add Docker Compose with app and PostgreSQL services"
```

---

## Task 14.5: Dev Profile

**Files:**
- Modify: `docker-compose.yml`

**Step 1: Add dev override to docker-compose.yml**

Add a dev service that overrides the app service for development:

```yaml
  # Add after the db service, before volumes:
  app-dev:
    build: .
    ports:
      - "${PORT:-8080}:8080"
    environment:
      DATABASE_URL: postgresql://${DB_USER:-drift}:${DB_PASSWORD:-drift}@db:5432/${DB_NAME:-driftshield}
      DB_HOST: db
      DB_PORT: 5432
      DB_USER: ${DB_USER:-drift}
      API_KEY: ${API_KEY:-dev-key}
      LOG_LEVEL: debug
    volumes:
      - ./src:/app/src
    command: >
      uvicorn driftshield.api.server:app
      --host 0.0.0.0 --port 8080
      --reload --log-level debug
    depends_on:
      db:
        condition: service_healthy
    profiles:
      - dev
```

**Step 2: Test dev profile**

```bash
cd .worktrees/driftshield-v1/driftshield
API_KEY=dev-key docker compose --profile dev up app-dev db
```

Expected: App starts with hot reload enabled, connected to PostgreSQL.

**Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(docker): add dev profile with hot reload and debug logging"
```

---

## Task 14.6: Full Build and Smoke Test

**Step 1: Build the Docker image**

```bash
cd .worktrees/driftshield-v1/driftshield
docker compose build
```

Expected: Multi-stage build completes. Frontend builds, Python deps install, static files copied.

**Step 2: Start the stack**

```bash
API_KEY=test-key-123 docker compose up -d
```

**Step 3: Wait for healthy**

```bash
docker compose ps
# Both services should be "healthy" or "running"
```

**Step 4: Smoke test the API**

```bash
# Health check
curl -s http://localhost:8080/api/health | python -m json.tool
# Expected: {"status": "ok", "version": "0.1.0"}

# Auth check
curl -s -H "X-API-Key: test-key-123" http://localhost:8080/api/sessions | python -m json.tool
# Expected: {"items": [], "total": 0, ...}

# SPA check
curl -s http://localhost:8080/ | head -5
# Expected: HTML with React app
```

**Step 5: Ingest a sample transcript**

```bash
curl -s -X POST http://localhost:8080/api/ingest \
  -H "X-API-Key: test-key-123" \
  -F "file=@tests/fixtures/sample-transcript.jsonl" \
  -F "format=claude-code" | python -m json.tool
# Expected: {"session_id": "...", "total_events": N, ...}
```

**Step 6: Tear down**

```bash
docker compose down
```

**Step 7: Commit (if any fixes were needed)**

```bash
git add -A
git commit -m "fix(docker): adjustments from smoke test"
```

---

## Task 14.7: Update pyproject.toml Dependencies

**Files:**
- Modify: `pyproject.toml`

Ensure all dependencies used across Phases 10-14 are listed:

```toml
dependencies = [
    "fastapi>=0.109.0",
    "uvicorn[standard]>=0.27.0",
    "sqlalchemy>=2.0.0",
    "alembic>=1.13.0",
    "psycopg2-binary>=2.9.9",
    "pydantic>=2.5.0",
    "pydantic-settings>=2.1.0",
    "typer>=0.9.0",
    "rich>=13.0.0",
    "jinja2>=3.1.0",
    "python-multipart>=0.0.6",
]
```

Add `python-multipart` (required for FastAPI file uploads).

```bash
git add pyproject.toml
git commit -m "chore: ensure all Phase 10-14 dependencies are listed"
```
