---
name: driftshield-pr-review
description: Review GitHub PRs and patches for the DriftShield repository with repo-specific context across the FastAPI backend, SQLAlchemy and Alembic database layer, Typer CLI, transcript ingest and analysis pipeline, and React/Vite frontend. Use when asked to review a DriftShield PR, branch, diff, or implementation for regressions, missing tests, schema drift, migration gaps, incomplete verification, or backend/frontend mismatches.
---

# DriftShield PR Review

Review DriftShield changes in findings-first mode. Read the PR or diff, the linked issue, and the surrounding code before judging the patch. Focus on bugs, regressions, missing tests, schema and type mismatches, migration gaps, and verification holes rather than style nits.

## Workflow

1. Establish scope.
- If the user gives a PR number, inspect it with `gh pr view <pr> --json title,body,files,commits,baseRefName,headRefName,url`.
- Read the linked issue or acceptance criteria before reviewing implementation details.
- Read changed files and nearby code paths; do not review the diff in isolation.

2. Map the touched system.
- Read [references/repo-map.md](references/repo-map.md) to identify the relevant backend, DB, CLI, or frontend surfaces.
- If the change spans multiple layers, review the whole chain: migration -> model -> service -> API schema -> frontend types/hooks -> UI.

3. Hunt for concrete findings.
- Prefer behavior regressions, data integrity risks, broken workflows, and missing coverage over subjective cleanup notes.
- Treat missing tests as findings when risky behavior changed and coverage did not follow.
- Check whether CLI, API, and frontend status surfaces still agree after the change.

4. Verify intelligently.
- Read [references/review-checklist.md](references/review-checklist.md) for DriftShield-specific failure modes and validation commands.
- Run targeted checks first, then widen if risk is still high.
- If UI behavior changed, run real browser verification. Do not stop at static analysis, lint, or build output.

5. Report clearly.
- Present findings first, ordered by severity, with precise file references.
- Keep summaries brief and secondary.
- If there are no findings, say so explicitly and mention remaining risks or testing gaps.

## DriftShield Priorities

- Read the linked issue or PR context before reviewing.
- Treat ingest provenance, dedupe and idempotency, UTC timestamps, migration safety, and API/frontend schema parity as high-risk areas.
- Expect tests near the changed area in `tests/api`, `tests/db`, `tests/cli`, `tests/core`, or `tests/integration`.
- Expect browser-based verification for UI behavior changes because the repo guidance requires it.

## Reference Guide

- Read [references/repo-map.md](references/repo-map.md) for architecture, key paths, and validation entry points.
- Read [references/review-checklist.md](references/review-checklist.md) for review heuristics, cross-layer invariants, and verification expectations.
