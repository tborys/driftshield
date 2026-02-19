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

# Seed sample data on first startup
SEED_MARKER="/app/.seeded"
if [ ! -f "$SEED_MARKER" ] && [ -d "/app/docker/fixtures" ]; then
  echo "Seeding sample data..."
  python /app/docker/seed.py
  touch "$SEED_MARKER"
fi

# Start Uvicorn
echo "Starting DriftShield on ${HOST:-0.0.0.0}:${PORT:-8080}..."
exec uvicorn driftshield.api.server:app \
  --host "${HOST:-0.0.0.0}" \
  --port "${PORT:-8080}" \
  --workers "${WORKERS:-1}" \
  --log-level "${LOG_LEVEL:-info}"
