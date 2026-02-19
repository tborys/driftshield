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
    libpq-dev postgresql-client curl \
    && rm -rf /var/lib/apt/lists/*

# Copy source and install Python package
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

# Copy Alembic config
COPY alembic.ini ./

# Copy built frontend
COPY --from=frontend-build /app/frontend/dist ./static

# Copy entrypoint
COPY docker/entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

# Environment defaults
ENV STATIC_DIR=/app/static
ENV HOST=0.0.0.0
ENV PORT=8080
ENV WORKERS=1
ENV LOG_LEVEL=info

EXPOSE 8080

ENTRYPOINT ["./entrypoint.sh"]
