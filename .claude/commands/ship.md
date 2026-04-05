Prepare the current work for PR. Run in order and stop if anything fails.

1. Run backend tests:
```bash
cd driftshield && uv run --extra dev pytest tests -q
```

2. Run frontend build:
```bash
cd driftshield/frontend && npm run build
```

3. If any frontend files were changed, run browser check:
```bash
cd driftshield/frontend && npx playwright test --reporter=list 2>/dev/null || echo "No e2e tests yet"
```

4. If all pass, show a PR description draft using this format:
```
## Summary
<one paragraph of what this PR does>

## Changes
- <file or area>: <what changed>

## Testing
- Backend: uv run --extra dev pytest tests -q (all pass)
- Frontend: npm run build (success)
- Browser: <playwright results or "no e2e tests">

## Closes
#<issue number>
```

5. Do not commit or push — leave that to the developer.
