Run a browser health check against the current frontend changes.

Steps:

1. Check if the FastAPI backend is running on port 8000. If not, start it:
```bash
cd driftshield && PYTHONPATH=src uvicorn driftshield.api.server:app --port 8000 &
sleep 2
```

2. Check if the Vite dev server is running on port 5173. If not, start it:
```bash
cd driftshield/frontend && npm run dev &
sleep 3
```

3. Check if Playwright is installed:
```bash
cd driftshield/frontend && npx playwright --version 2>/dev/null || echo "NOT_INSTALLED"
```

If not installed:
```bash
cd driftshield/frontend && npm install --save-dev @playwright/test && npx playwright install chromium
```

4. Check if e2e tests exist:
```bash
ls driftshield/frontend/tests/e2e/*.spec.ts 2>/dev/null || echo "NO_TESTS"
```

If no tests exist, write smoke tests for the components changed in the current issue before proceeding. Tests must cover:
- Page loads without console errors
- Key UI elements visible
- Any user action in scope for the current issue (form submit, button click, navigation)

5. Run Playwright:
```bash
cd driftshield/frontend && npx playwright test --reporter=list
```

6. If any test fails:
- Show the failure message and screenshot path
- Fix the component or the test (whichever is wrong)
- Re-run until all pass

7. Report: tests run, pass/fail count, any screenshots saved.
