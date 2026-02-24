---
name: browser-health
description: Check and auto-heal the OpenClaw browser (CDP on 18800). Use on heartbeat or on demand when browser feels slow, pages fail to load, or CDP is unreachable.
---

# Browser Health

Self-check and auto-heal for the OpenClaw headless browser.

## When to use

- Every heartbeat cycle (automatic)
- When a browser command fails or times out
- When asked to check browser health
- After a gateway restart

## How to run

Execute the health check script:

```bash
bash ~/.openclaw/workspace/skills/browser-health/scripts/check.sh
```

The script prints a JSON status object and exits with:
- **0** if healthy (no action taken)
- **0** if was unhealthy but auto-healed successfully
- **1** if auto-heal failed (needs manual intervention)

## What it checks

1. **Status desync**: browser reports not running but Chromium processes exist (orphan detection)
2. **CDP responsiveness**: curl to `http://127.0.0.1:18800/json/version` must return valid JSON within 5 seconds
3. **Process leak**: any single renderer process using >15% CPU (sign of a tab or page gone rogue)
4. **Process count**: more than 20 chrome-headless-shell processes suggests a leak

## Auto-heal actions

When any check fails, the script:
1. Stops the browser via `openclaw browser stop`
2. Kills all remaining chrome-headless-shell processes
3. Waits 2 seconds
4. Starts the browser via `openclaw browser start`
5. Verifies CDP responds
6. Reports what it found and what it did

## Interpreting output

```json
{
  "healthy": true,
  "cdp_responding": true,
  "process_count": 6,
  "action": "none"
}
```

```json
{
  "healthy": true,
  "cdp_responding": true,
  "process_count": 5,
  "action": "auto-healed",
  "reason": "cdp_timeout",
  "previous_process_count": 14
}
```

```json
{
  "healthy": false,
  "cdp_responding": false,
  "action": "heal-failed",
  "reason": "cdp_timeout_after_restart",
  "error": "CDP did not respond after restart"
}
```

## Heartbeat integration

Add to HEARTBEAT.md:

```
- Run browser health check: `bash ~/.openclaw/workspace/skills/browser-health/scripts/check.sh`
  If the output shows action: auto-healed, note what was wrong in today's memory log.
  If the output shows healthy: false, alert Demo.
```
