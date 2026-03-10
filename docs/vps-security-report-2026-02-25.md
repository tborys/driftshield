# VPS Security Report — 2026-02-25

## Summary
The DriftShield dogfood deployment on the Cloud VPS is intended to remain private. The security posture is:
- private access over Tailscale
- localhost health verification
- UFW used to avoid public app exposure
- SSH locked to key-based auth
- application secrets stored server-side in `driftshield/.env`

## Current baseline
### Network exposure
- Application port: `8080`
- Expected exposure: localhost + tailnet only
- Public internet exposure of the app is out of policy

### Access controls
- Tailscale is the private access layer
- UFW should not contain `8080 ALLOW Anywhere`
- SSH uses hardened settings outside this repo baseline

### Application controls
The dogfood deployment now expects:
- `ENVIRONMENT=production`
- non-placeholder `API_KEY`
- non-default `DB_PASSWORD`
- positive `MAX_REQUEST_BYTES`

## Controls implemented in repo
### Deploy-time guardrails
`scripts/vps-deploy.sh` now blocks deployment when:
- the server-side `.env` file is missing
- production mode is not set
- API key is empty or placeholder/dev-like
- DB password is still the default
- request-size limit is invalid
- the app port is publicly allowed via UFW

### Runtime API guardrails
The API now rejects unsafe configurations by:
- returning `503` when no API key is configured
- returning `503` when production still uses a placeholder API key
- returning `413` for requests above `MAX_REQUEST_BYTES`
- returning `400` for malformed `Content-Length`

## Backup and restore posture
- Predeploy database snapshots are created where practical
- Backups are gzip-compressed SQL dumps under `backups/db/`
- Restore is documented in `docs/openclaw-vps-reference.md`

## Verification path
Run after each deploy:

```bash
bash scripts/vps-verify-access.sh
```

Check all of the following:
- container health
- localhost `/api/health`
- tailnet `/api/health`
- no public UFW allow rule for the app port
- active listener state on the host

## Residual risks
- Secrets are still file-based on the host rather than centrally managed
- Backup restore drills should be run on a schedule, not only documented
- UFW checks are host-specific and assume UFW is the active firewall layer
- Tailscale connectivity is a dependency for remote private access testing

## Recommended next steps
1. Run a restore drill using the documented SQL backup path.
2. Add periodic pruning/retention for `backups/db/`.
3. Consider fail2ban/UFW verification as part of a broader host audit outside this repo.
4. Keep the dogfood target private; do not add a public ingress rule for `8080`.
