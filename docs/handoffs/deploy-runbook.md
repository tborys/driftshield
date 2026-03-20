# DriftShield Deploy Runbook (Cloud VPS, private access)

## Scope
Secure, repeatable production deployment for DriftShield Agentic on Cloud VPS using GitHub Actions + SSH.

Deployment target: `driftshield/docker-compose.yml`

Security target:
- private/tailnet access only
- no public app exposure by default
- secrets stay in GitHub encrypted secrets and server-side `.env`

---

## 1) Deployment model

### Chosen mechanism
**GitHub Actions SSH deploy** (no self-hosted runner required).

Why:
- simple and low ops overhead
- least moving parts
- straightforward secret/control boundary

### Promotion strategy
- `main` is the only production deploy ref.
- deployment trigger is **manual** (`workflow_dispatch`) for controlled releases.
- optional GitHub Environment approvals should gate production runs.

---

## 2) Files added

- `.github/workflows/ci.yml`
  - backend tests + frontend build on PR/push
- `.github/workflows/deploy-vps.yml`
  - manual production deploy + optional access verification
- `scripts/vps-deploy.sh`
  - prechecks, backup, deploy, health verification, auto-rollback on failure
- `scripts/vps-verify-access.sh`
  - verifies local + tailnet health endpoint and basic exposure checks
- `docs/openclaw-vps-reference.md`
  - canonical dogfood VPS env/deploy/backup/restore reference
- `docs/vps-security-report-2026-02-25.md`
  - security baseline and residual risk summary

---

## 3) GitHub secrets required

Set these in repo settings (`Settings` → `Secrets and variables` → `Actions`):

- `VPS_HOST` — VPS DNS/IP
- `VPS_USER` — deploy SSH user
- `VPS_SSH_PORT` — usually `22`
- `VPS_SSH_KEY` — private key (deploy key/user key, least privilege)
- `VPS_REPO_PATH` — absolute path to this repo checkout on VPS

Optional:
- `VPS_KNOWN_HOSTS` — pinned host key entry (recommended)
- `DEPLOY_ALERT_WEBHOOK` — webhook for failure notifications

---

## 4) VPS prerequisites

- Repo cloned on VPS at `VPS_REPO_PATH`
- Docker + Compose v2 available
- `.env` exists at `driftshield/.env` (server-side only)
- UFW active and **no public allow rule** for app port (default 8080)
- Tailscale active for device access

---

## 5) Deployment workflow

### Trigger
Run **Deploy to Cloud VPS** workflow manually.

Inputs:
- `deploy_ref`: must be `main`
- `run_access_check`: usually `true`

### What deploy script does
1. Prechecks:
   - command availability (git/docker/curl)
   - disk free space threshold
   - compose config validation
2. Backup:
   - creates `pg_dump` snapshot (`backups/db/predeploy-<timestamp>.sql.gz`) if DB container is running
3. Deploy:
   - fetch + hard reset to target commit
   - compose pull/build/up
4. Verify:
   - container state
   - `http://127.0.0.1:<PORT>/api/health`
   - tailnet health via `http://<tailscale-ip>:<PORT>/api/health` when available
5. Rollback (automatic on failure):
   - reset to previous commit
   - compose up with previous state
   - health check

---

## 6) Device access validation (laptop + phone)

After successful deploy, validate from real devices on tailnet.

### Laptop check
1. Ensure Tailscale connected to same tailnet
2. Open:
   - `http://<VPS_TAILSCALE_IP>:8080/sessions`
3. API check:
   - `curl http://<VPS_TAILSCALE_IP>:8080/api/health`

### Phone check
1. Open Tailscale app and confirm connected
2. In mobile browser open:
   - `http://<VPS_TAILSCALE_IP>:8080/sessions`
3. Confirm UI loads and list page is reachable

If these pass, private access path is validated end-to-end.

---

## 7) Security guardrails

- Never commit `.env` or secrets to repo
- Keep production deploy limited to `main`
- Prefer pinned `VPS_KNOWN_HOSTS` over dynamic keyscan
- Keep app private behind UFW + Tailscale (no public app allow rule)
- Rotate deploy SSH key periodically

---

## 8) Rollback procedure (manual)

If needed outside automated rollback:

```bash
cd <VPS_REPO_PATH>
PREV_COMMIT=<known-good-commit>
git reset --hard "$PREV_COMMIT"
cd driftshield
docker compose up -d --build --remove-orphans
bash ../scripts/vps-verify-access.sh
```

---

## 9) Recommended next hardening

- Add required reviewers on GitHub `production` environment
- Add signed commit/tag requirement for production deploy
- Add nightly backup retention policy + restore drill
- Add SLO reporting for deploy success/failure and post-deploy health latency
