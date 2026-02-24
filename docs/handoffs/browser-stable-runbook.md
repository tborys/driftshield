# Browser Control + Dev Ports Runbook

Stabilising OpenClaw browser control (CDP on 18800) and DriftShield local dev ports (8080, 4173).

## Architecture

- **OpenClaw gateway**: runs on Cloud VPS inside Docker (`openclaw-openclaw-gateway-1`)
- **Browser control**: headless Chromium inside the container, CDP on `127.0.0.1:18800`
- **browser-health skill**: self-healing skill on the VPS, runs every heartbeat (30m) and auto-restarts on any unhealthy signal
- **DriftShield API**: local Mac, port 8080
- **DriftShield frontend** (Vite): local Mac, port 4173

## Quick Reset (from Mac)

```bash
./scripts/dev-reset.sh
```

Kills local port conflicts, runs browser-health check on VPS (auto-heals if needed), prints status.

## Manual Clean Start

```bash
# 1. Kill any local conflicting processes
lsof -ti :8080 | xargs kill -9 2>/dev/null
lsof -ti :4173 | xargs kill -9 2>/dev/null

# 2. Run browser health check on VPS (auto-heals if needed)
ssh cloud "docker exec openclaw-openclaw-gateway-1 bash /home/node/.openclaw/workspace/skills/browser-health/scripts/check.sh"

# 3. Start DriftShield API (from repo root)
cd ~/github/drift-shield-agentic
# npm start or docker compose up -d

# 4. Start DriftShield frontend
# npm run preview  (Vite on 4173)
```

## Status Checks

```bash
# Automated health check (preferred)
ssh cloud "docker exec openclaw-openclaw-gateway-1 bash /home/node/.openclaw/workspace/skills/browser-health/scripts/check.sh"

# Manual browser status
ssh cloud "docker exec openclaw-openclaw-gateway-1 node dist/index.js browser status"

# CDP endpoint (should return JSON with Browser version)
ssh cloud "docker exec openclaw-openclaw-gateway-1 curl -s http://127.0.0.1:18800/json/version"

# Local ports
lsof -i :8080 -i :4173
```

## Conflict Recovery

Most conflicts are now handled automatically by the browser-health skill. It detects and fixes:
- Status desync (`running: false` but processes alive)
- CDP not responding
- Renderer CPU leaks (>15% CPU)
- Too many processes (>20)

### Manual recovery (if auto-heal fails)

```bash
# Nuclear option: kill everything, restart gateway, start browser
ssh cloud "docker exec openclaw-openclaw-gateway-1 bash -c 'pkill -9 -f chrome-headless-shell'"
ssh cloud "cd /root/openclaw && docker compose restart openclaw-gateway"
sleep 5
ssh cloud "docker exec openclaw-openclaw-gateway-1 node dist/index.js browser start"
```

### Local port conflict (8080 or 4173)

```bash
lsof -i :8080
lsof -i :4173
kill -9 <PID>

# Or just run the reset script
./scripts/dev-reset.sh
```

## Heartbeat Integration

The browser-health skill runs as the first item in the OpenClaw heartbeat checklist (every 30 minutes). If it auto-heals, Contributor logs the event. If healing fails, Contributor alerts Demo.

## Known Risks

- Browser is not auto-started on gateway restart. The heartbeat will catch this within 30 minutes, or you can trigger it manually.
- Long-running sessions (days) cause renderer memory/CPU leak. The skill detects this at >15% CPU and auto-restarts.
- The `running: false` desync can recur if the gateway crashes without cleanly stopping the browser. The skill detects and fixes this.
