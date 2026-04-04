# OpenClaw VPS Reference for DriftShield Dogfood

## Purpose
Reference runbook for the always-on private DriftShield dogfood deployment on the Cloud VPS. This path stays private behind Tailscale and is deployed with the existing VPS script rather than a separate production system.

## Deployment shape
- Host: Cloud VPS
- Access model: Tailscale tailnet + localhost only
- App stack: `driftshield/docker-compose.yml`
- Deploy entrypoint: `scripts/vps-deploy.sh`
- Verification entrypoint: `scripts/vps-verify-access.sh`
- Expected branch: `main`
- Default app port: `8080`

## Server-side env file
Create and maintain `driftshield/.env` on the VPS. Do not commit this file.

Start from:
- `driftshield/.env.production.example`
- `driftshield/docker/.env.example`

Minimum production values:

```env
ENVIRONMENT=production
API_KEY=<long random secret>
DB_USER=drift
DB_PASSWORD=<strong password>
DB_NAME=driftshield
DATABASE_URL=postgresql://drift:<strong password>@db:5432/driftshield
PORT=8080
LOG_LEVEL=info
WORKERS=1
MAX_REQUEST_BYTES=26214400
```

## What the deploy script enforces
`scripts/vps-deploy.sh` fails fast unless all of the following are true:
- `driftshield/.env` exists on the server
- `ENVIRONMENT=production`
- `PORT` is a positive integer
- `MAX_REQUEST_BYTES` is a positive integer
- `API_KEY` is not empty and not a placeholder/dev value
- `DB_PASSWORD` is not the default `drift`
- the app port is not publicly allowed via UFW

This is deliberate. Dogfood should fail closed, not quietly drift into an unsafe state.

## Request-size and auth hardening
API hardening for the dogfood target now includes:
- startup rejection of missing or placeholder API keys in production
- middleware-level `Content-Length` enforcement via `MAX_REQUEST_BYTES`
- route-level uploaded file size validation on ingest

Operational defaults:
- `MAX_REQUEST_BYTES=26214400` (25 MiB)
- `X-API-Key` must match the configured server key

## Deploy procedure
From GitHub Actions or over SSH on the server:

```bash
cd <repo>
BRANCH=main bash scripts/vps-deploy.sh
```

The script performs:
1. host/tooling checks
2. disk-space check
3. env validation
4. predeploy PostgreSQL backup when the DB container is running
5. fetch/reset to target commit
6. compose pull/build/up
7. localhost health check
8. Tailscale health check when a tailnet IP exists
9. public exposure guard via UFW
10. automatic rollback on failure

## Backup and restore
### Backup location
Backups are written to:

```text
backups/db/predeploy-<timestamp>.sql.gz
```

### Create an additional manual backup
```bash
cd <repo>/driftshield
docker compose exec -T db sh -c "pg_dump -U '$DB_USER' '$DB_NAME'" | gzip > ../backups/db/manual-$(date -u +%Y%m%dT%H%M%SZ).sql.gz
```

### Restore procedure
Stop the app before restore if you want a clean rollback window.

```bash
cd <repo>/driftshield
gunzip -c ../backups/db/predeploy-<timestamp>.sql.gz | docker compose exec -T db sh -c "psql -U '$DB_USER' '$DB_NAME'"
```

Then verify:

```bash
bash ../scripts/vps-verify-access.sh
```

## Tailscale verification
Run on the VPS:

```bash
bash scripts/vps-verify-access.sh
```

Expected outcome:
- localhost `/api/health` returns success
- tailnet `/api/health` returns success when Tailscale is up
- no UFW rule exposes `${PORT}` to `Anywhere`
- listener is visible only on the intended interface/path

Manual device checks:
- Laptop on tailnet: `http://<tailscale-ip>:8080/api/health`
- Laptop/phone UI: `http://<tailscale-ip>:8080/sessions`

## Non-goals
- No public internet exposure
- No separate packaging flow
- No Helm/Kubernetes path for this dogfood target

## Related docs
- `docs/vps-security-report-2026-02-25.md`
- `scripts/vps-deploy.sh`
- `scripts/vps-verify-access.sh`
