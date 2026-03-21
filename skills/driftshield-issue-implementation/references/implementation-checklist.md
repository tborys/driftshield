# DriftShield Implementation Checklist

## Contents

- Issue intake
- Spec and plan
- Test-first implementation
- Verification rules
- Finish checklist

## Issue intake

1. Read the issue body before editing.
2. Extract:
- goal
- acceptance criteria
- verification guidance
- relevant starting files
- dependencies or parent issues
3. Read the current implementation in the affected code paths before designing the change.
4. If the issue touches frontend behavior, plan browser verification from the start.

Useful commands:

- `gh issue view <issue> --json number,title,body,url,labels,state`
- `gh pr view <pr> --json title,body,files,commits,baseRefName,headRefName,url`
- `rg -n "<symbol-or-feature>" driftshield/src driftshield/frontend/src driftshield/tests`

## Spec and plan

Write a short implementation spec in the user update before coding. Cover only the parts that matter for the issue:

- architecture or service shape
- state model, schema, or contract changes
- persistence or migration impact
- API, CLI, and frontend surfaces that must stay aligned
- test and verification plan

Then move directly into implementation unless a true blocker appears.

## Test-first implementation

- Add or update failing tests near the changed behavior first.
- Prefer targeted suites while iterating:
  - API: `driftshield/tests/api/`
  - DB and persistence: `driftshield/tests/db/`
  - CLI: `driftshield/tests/cli/`
  - Core logic: `driftshield/tests/core/`
  - Parsers and integration: `driftshield/tests/parsers/`, `driftshield/tests/integration/`
- Reuse existing implementation seams instead of creating parallel paths when the issue can extend current behavior.
- Keep changes bounded to the issue unless cleanup is necessary for correctness.

## Verification rules

### Backend-only changes

- Run targeted tests for the touched area.
- Run broader backend tests if the code path is shared, stateful, or persistence-heavy.
- Run full `cd driftshield && uv run pytest` before finishing if the change is substantial.

### DB or migration changes

- Check model, migration, and persistence parity.
- Verify behavior in tests that run on SQLite, and think about PostgreSQL semantics before finishing.

### API plus frontend changes

- Check `api/schemas.py` against frontend `src/types/*`.
- Check route behavior against frontend hooks in `src/api/*`.
- Run frontend build and lint.
- Run a real browser flow for the changed UI.

### UI behavior changes

- Do not treat unit tests, build output, or lint as sufficient.
- Exercise the changed route, state transition, filter, or form in a real browser and report what was tested.

## Finish checklist

- Acceptance criteria are covered by code and tests.
- User-visible surfaces are aligned across backend, CLI, and frontend where applicable.
- Verification results are recorded in the final summary.
- Remaining risks are called out explicitly if any checks could not be run or if unrelated repo-wide issues remain.
