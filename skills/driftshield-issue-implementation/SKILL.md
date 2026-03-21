---
name: driftshield-issue-implementation
description: Implement GitHub issues, issue-driven tasks, and bounded feature work in the DriftShield repository with repo-specific context across the FastAPI backend, SQLAlchemy and Alembic database layer, Typer CLI, transcript ingest and analysis pipeline, and React/Vite frontend. Use when asked to implement a DriftShield issue, linked PR task, or feature request and the work should start by gathering context, writing a short spec and plan, then executing tests, code changes, verification, and summary end to end.
---

# DriftShield Issue Implementation

Implement DriftShield work autonomously and end to end. Start from the issue, read the surrounding code before editing, write a short spec and plan in a user update, then move through failing tests, implementation, verification, and a concise close-out without waiting for extra approval unless there is a real blocker or a risky irreversible choice.

## Workflow

1. Gather issue context first.
- If the user gives an issue number, read it with `gh issue view <issue> --json number,title,body,url,labels,state`.
- If the issue references a PR, parent epic, or acceptance criteria, read those details before designing the change.
- Read `AGENTS.md` and any user-provided starting files before editing.

2. Map the affected system.
- Read [references/repo-map.md](references/repo-map.md) to identify the right backend, DB, CLI, or frontend surfaces.
- Read nearby tests before coding so the change extends current behavior instead of replacing it.
- If the issue spans layers, follow the whole chain: migration -> model -> service -> API schema -> frontend types/hooks -> UI.

3. Write a short spec and plan in the user update.
- Keep it brief but concrete.
- Cover architecture, state model or contracts, verification plan, and any cross-layer updates that will be needed.
- Continue into implementation immediately after the plan unless a real blocker appears.

4. Start test-first.
- Add or update failing tests near the changed behavior before making the implementation green.
- Prefer the narrowest tests that prove the issue requirements, then widen coverage if the area is shared or high risk.

5. Implement end to end.
- Reuse existing persistence, parser, API, and frontend patterns where possible.
- Update all affected layers in the same pass so the repository stays coherent.
- Avoid speculative refactors that are not needed to close the issue.

6. Verify with the right depth.
- Read [references/implementation-checklist.md](references/implementation-checklist.md) for DriftShield-specific verification rules.
- Run targeted tests during development and the relevant broader suite before finishing.
- If UI behavior changed, run a real browser flow and report exactly what was exercised.

7. Close out clearly.
- Summarize what changed, how it was verified, and any remaining risks.
- Mention if full lint or unrelated repo-wide checks still fail for pre-existing reasons.

## DriftShield Priorities

- Read the issue and surrounding code before editing.
- Write the short spec and plan before implementation.
- Prefer end-to-end delivery in one pass.
- Treat ingest idempotency, provenance, migrations, API/frontend schema parity, and timezone handling as high-risk areas.
- Expect browser verification for frontend behavior changes because the repo guidance requires it.

## Reference Guide

- Read [references/repo-map.md](references/repo-map.md) for architecture, key files, and validation entry points.
- Read [references/implementation-checklist.md](references/implementation-checklist.md) for issue execution, test-first guidance, and verification commands.
