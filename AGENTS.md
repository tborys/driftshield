# Project Agent Guidance

## Implementation Workflow

- For issue or PR driven work, read the linked issue or PR and the relevant code paths before making changes.
- Before implementing, write a short spec and plan in your working notes or user update, then continue into implementation without waiting for extra human approval unless there is a real blocker or a risky irreversible decision.
- Prefer end to end execution. Do not stop at analysis, planning or partial scaffolding when the task can reasonably be completed in one pass.
- If a change touches frontend or UI behaviour, include browser based verification as part of completion, not just static or unit checks.
- When browser testing is needed, use the real browser tooling available in the environment and report what flow was exercised.
- After local verification passes, push the working branch and open or update a PR linked to the issue.

## Git Naming

- Use standard conventional commit messages such as `feat:`, `fix:`, `docs:`, `chore:`, and `test:`.
- Do not prefix PR titles with `[codex]`.
- Do not add tool-provenance prefixes to commit subjects or squash-merge commit titles unless explicitly requested.

## Issue Hygiene

- When working from GitHub issues, keep the issue body, linked parent issue, and GitHub Project status in sync with the real state of the work.
- If an issue is closed as completed, update all relevant checkboxes in the issue body first.
- If an issue is closed as superseded, cancelled, or intentionally not completed, leave incomplete checkboxes only if the closing comment explains why.
- When a child issue is completed, update any parent issue checklist entry that tracks it.
- Do not mark an issue done until acceptance criteria, test plan, linked parent checklist, and project status all reflect the actual outcome.
- If work is blocked, prefer leaving the issue open with a clear blocker comment and the `blocked` label instead of closing it.

## Handoffs

- When preparing a prompt for another agent, make it autonomous by default.
- Tell the agent to inspect the issue and codebase first, produce a concrete spec and plan, then implement, verify and summarise the result without waiting for a human in the loop.
